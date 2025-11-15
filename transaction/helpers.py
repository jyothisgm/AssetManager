# transaction/helpers.py
from django.db.models import Q
from ai.utils import normalize_product_name_with_llm
from catalog.models import Product, Store, PurchaseCategory, Institution
from account.models import Account
from common.models import Unit
from common.utils import safe_decimal
from transaction.models import Transaction
from common.logging_config import logger
from django.db import models, IntegrityError
from common.models import Currency
from common.logging_config import logger
from decimal import Decimal
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from transaction.models import Transaction, TransactionItem
from transaction.utils import find_possible_duplicate
from common.logging_config import logger
from common.models import Unit
from datetime import datetime



def _resolve_currency(code_or_symbol: str):
    """
    Match an existing Currency record by code, symbol, or name.
    Never creates a new one.
    Returns None if not found.
    """
    if not code_or_symbol:
        return None

    value = str(code_or_symbol).strip().upper()
    try:
        # Try ISO code first
        currency = Currency.objects.filter(code__iexact=value).first()
        if currency:
            return currency

        # Try symbol or name (case-insensitive)
        currency = Currency.objects.filter(
            models.Q(symbol__iexact=value) | models.Q(name__iexact=value)
        ).first()
        if currency:
            return currency

        # Common fallback for symbols if user/LLM returns only symbol
        symbol_map = {
            "$": "USD",
            "₹": "INR",
            "€": "EUR",
            "£": "GBP",
            "¥": "JPY",
            "₿": "BTC",
        }
        mapped = symbol_map.get(value)
        if mapped:
            return Currency.objects.filter(code__iexact=mapped).first()

        logger.warning(f"[CurrencyResolver] No matching currency for '{code_or_symbol}'")
        return None

    except Exception:
        logger.exception(f"[CurrencyResolver] Failed to resolve currency '{code_or_symbol}'")
        return None


def get_or_match_related_models(user, email_from: str, description: str, category_hint: str = None, store_hint: str = None):
    """
    Attempts to find related models (Account, Store, Category, Unit) for a transaction.
    - Uses email sender to infer Account via Institution.
    - Reuses stores and categories used in past similar transactions.
    - Never creates a new Category (reuses only).
    - Creates Store only if not found and no preferred match exists.
    """
    store = None
    category = None
    unit = None

    try:
        # 1️⃣ Guess Account based on sender domain or known institution
        if email_from:
            domain = email_from.split("@")[-1].split(">")[0].lower()
            inst = Institution.objects.filter(
                Q(short_name__icontains=domain.split(".")[0]) | Q(name__icontains=domain.split(".")[0])
            ).first()

        # 2️⃣ Guess Store
        if store_hint:
            store = Store.objects.filter(name__icontains=store_hint).first()
        if not store:
            # Check previous similar descriptions
            past_tx = (
                Transaction.objects.filter(created_by=user, description__icontains=description[:30])
                .exclude(store__isnull=True)
                .order_by("-date")
                .first()
            )
            if past_tx:
                store = past_tx.store
                logger.debug(f"[ModelFinder] Reused store from similar transaction: {store}")
        if not store and store_hint:
            # fallback: create new store if none preferred exists
            existing_pref = Store.objects.filter(preferred__isnull=True, name__iexact=store_hint.strip()).first()
            if existing_pref:
                store = existing_pref
            else:
                store = Store.objects.create(created_by=user, name=store_hint.strip())
                logger.info(f"[ModelFinder] Created new store '{store.name}'")

        # 3️⃣ Guess Category
        if category_hint:
            category = PurchaseCategory.objects.filter(name__iexact=category_hint.strip()).first()
        if not category and store:
            past_tx = (
                Transaction.objects.filter(created_by=user, store=store)
                .exclude(category__isnull=True)
                .order_by("-date")
                .first()
            )
            if past_tx:
                category = past_tx.category
                logger.debug(f"[ModelFinder] Reused category '{category}' for store '{store}'")

        # 4️⃣ Guess Unit from description
        unit = None
        if description:
            units = Unit.objects.all()
            for u in units:
                if u.name.lower() in description.lower() or (u.symbol and u.symbol.lower() in description.lower()):
                    unit = u
                    break

    except Exception:
        logger.exception("[ModelFinder] Error while matching related models")

    return store, category, unit


def create_transaction_from_llm_tx(user, tx_data, account, llm=None, card=None):
    """
    Creates a Transaction and TransactionItems from an LLM transaction dict.
    
    Args:
        user: User instance
        tx_data: Transaction data dict from LLM
        account: Account instance to link transaction to
        llm: Optional LLM instance
        card: Optional Card instance to link transaction to
    """
    try:
        # 1️⃣ Basic field parsing
        date = None
        raw_date = tx_data.get("date")
        email_timestamp = tx_data.get("email_timestamp")
        email_timestamp_dt = tx_data.get("_email_timestamp_dt")
        candidates = [raw_date, email_timestamp, email_timestamp_dt]

        for candidate in candidates:
            if not candidate:
                continue
            parsed = None

            if isinstance(candidate, datetime):
                parsed = candidate
            elif isinstance(candidate, str):
                cleaned = candidate.strip()
                parsed = parse_datetime(cleaned)
                if not parsed:
                    try:
                        parsed = timezone.datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
                    except Exception:
                        parsed = None
            elif hasattr(candidate, "isoformat"):
                try:
                    parsed = parse_datetime(candidate.isoformat())
                except Exception:
                    parsed = None

            if parsed:
                if timezone.is_naive(parsed):
                    parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
                date = parsed
                break

        if not date:
            date = timezone.now()

        logger.info(
            "[TxCreate] Date resolution → final=%s | llm_date=%s | email_ts=%s | raw_email_dt=%s",
            date.isoformat(),
            (raw_date or ""),
            (email_timestamp or ""),
            (email_timestamp_dt.isoformat() if isinstance(email_timestamp_dt, datetime) else email_timestamp_dt),
        )

        from decimal import Decimal, InvalidOperation

        raw_amount = tx_data.get("amount")
        try:
            # Convert None, '', or text like 'N/A' to 0
            if raw_amount in (None, "", "N/A", "null", "none"):
                amount = Decimal("0.00")
            else:
                # Remove commas and stray currency symbols if any
                cleaned = str(raw_amount).replace(",", "").replace("₹", "").replace("$", "").strip()
                amount = Decimal(cleaned).quantize(Decimal("0.01"))
        except (InvalidOperation, ValueError):
            logger.warning(f"[TxCreate] Could not parse amount='{raw_amount}', defaulting to 0")
            amount = Decimal("0.00")

        description = tx_data.get("description", "").strip()[:255]
        category_hint = tx_data.get("category")
        store_hint = tx_data.get("store")
        email_from = tx_data.get("from", "")
        currency_code = tx_data.get("currency")

        # 2️⃣ Resolve currency
        currency = _resolve_currency(currency_code)

        # 3️⃣ Related models
        store, category, unit = get_or_match_related_models(
            user,
            email_from=email_from,
            description=description,
            category_hint=category_hint,
            store_hint=store_hint,
        )

        # 4️⃣ Duplicate check
        duplicate = find_possible_duplicate(user, account, date, amount, description)
        if duplicate:
            logger.info(f"[TxCreate] Skipping duplicate transaction: {duplicate}")
            return duplicate, "duplicate"

        # 5️⃣ Create Transaction
        txn = Transaction.objects.create(
            created_by=user,
            transaction_type="debit",
            amount=amount,
            date=date,
            description=description,
            currency=currency,
            account=account,
            card=card,
            category=category,
            store=store,
            notes="auto-imported via Gmail/LLM" + (" | needs_review" if tx_data.get("needs_review") else ""),
        )
        card_info = f" with card={card.display_name}" if card else ""
        logger.info(f"[TxCreate] Created Transaction {txn.id} ({description}) with account={txn.account.name if txn.account else 'None'}{card_info}")

        # 6️⃣ Items
        items = tx_data.get("items", [])
        subtotal = Decimal("0.00")

        for item in items:
            # Handle both string items and dict items from LLM
            if isinstance(item, str):
                name = item.strip() or "Unnamed Product"
                qty = Decimal("1")
                price = Decimal("0.00")
                unit_name = ""
            elif isinstance(item, dict):
                name = item.get("name", "").strip() or "Unnamed Product"
                qty = safe_decimal(item.get("quantity") or 1)
                price = safe_decimal(item.get("price"))
                unit_name = item.get("unit", "")
            else:
                # Fallback for any other type
                name = str(item).strip() or "Unnamed Product"
                qty = Decimal("1")
                price = Decimal("0.00")
                unit_name = ""
            
            matched_unit = unit
            # 🧩 Normalize product name using LLM
            normalized_name = normalize_product_name_with_llm(llm, name)
            # 🧩 Reuse or create product
            product = Product.objects.filter(name__iexact=normalized_name).first()
            if not product:
                try:
                    product = Product.objects.create(name=normalized_name, created_by=user)
                    logger.info(f"[TxCreate] Created new Product '{normalized_name}'")
                except IntegrityError:
                    # Handle race conditions or existing product created by another user
                    product = Product.objects.filter(name__iexact=normalized_name).first()
                    if not product:
                        raise

            if unit_name:
                matched_unit = Unit.objects.filter(name__iexact=unit_name).first() or unit

            TransactionItem.objects.create(
                created_by=user,
                transaction=txn,
                product=product,
                price=price,
                quantity=qty,
                unit=matched_unit,
                date=date,
            )
            subtotal += price

        # 7️⃣ Total verification
        diff = abs(amount - subtotal)
        if items and diff > Decimal("0.05"):
            logger.warning(f"[TxCreate] Total mismatch ({amount} vs {subtotal}), retrying correction...")
            if llm:
                from langchain_core.messages import HumanMessage
                import json

                correction_prompt = (
                    "The item totals do not match the transaction total.\n"
                    f"Transaction total: {amount}\n"
                    f"Items:\n{json.dumps(items, indent=2)}\n"
                    "Please reallocate prices or quantities so totals match. "
                    "Return ONLY JSON array of corrected items."
                )
                res = llm.invoke([HumanMessage(content=correction_prompt)])
                try:
                    corrected = json.loads(res.content)
                    if isinstance(corrected, list):
                        txn.items.all().delete()
                        subtotal = Decimal("0.00")
                        for item in corrected:
                            price = safe_decimal(item.get("price") or 0)
                            qty = safe_decimal(item.get("quantity"))
                            TransactionItem.objects.create(
                                created_by=user,
                                transaction=txn,
                                price=price,
                                quantity=qty,
                                date=date,
                            )
                            subtotal += price
                except Exception:
                    logger.warning("[TxCreate] LLM correction failed; keeping original items.")
        txn.update_total_match_status()
        return txn, "created"

    except Exception as e:
        logger.exception(f"[TxCreate] Failed for tx_data={tx_data}: {e}")
        return None, "error"

