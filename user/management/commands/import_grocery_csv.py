import csv
import os
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
import pytz
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.db.models import Q, F, ExpressionWrapper, DecimalField

from catalog.models import CategoryGroup, PurchaseCategory, Store, Product, Currency
from common.models import Unit
from transaction.models import Transaction, TransactionItem
from user.models import User
from common.logging_config import logger


class Command(BaseCommand):
    help = "🧾 Import grocery CSV and update matched transactions (store + date + amount)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to the grocery CSV file")

    def handle(self, *args, **opts):
        logger.info("🚀 [import_grocery_csv] Starting CSV import process...")
        csv_path = opts["csv_path"]

        if not os.path.exists(csv_path):
            logger.error(f"❌ [import_grocery_csv] File not found: {csv_path}")
            return

        try:
            with open(csv_path, newline="", encoding="utf-8") as f:
                rows = list(csv.reader(f))
        except Exception as e:
            logger.exception(f"🔥 [import_grocery_csv] Failed to read CSV: {e}")
            return

        if len(rows) < 4:
            logger.error("❌ [import_grocery_csv] CSV too short — expected ≥4 rows (dates, stores, totals, items).")
            return

        date_row, store_row, total_row = rows[0], rows[1], rows[2]
        ncols = len(date_row)
        if (ncols - 1) % 2 != 0:
            logger.error("❌ [import_grocery_csv] After first column, columns must come in pairs (price, quantity).")
            return

        # ----------------------------------------
        # Setup constants
        # ----------------------------------------
        amsterdam_tz = pytz.timezone("Europe/Amsterdam")
        buffer_hours = 48
        amount_tolerance = 0.05

        UNIT_ALIASES = {
            "g": "Gram", "gram": "Gram", "grams": "Gram",
            "kg": "Kilogram", "kgs": "Kilogram",
            "ml": "Millilitre", "l": "Litre", "ltr": "Litre",
            "pc": "Piece", "pcs": "Piece", "piece": "Piece",
            "pack": "Packet", "packs": "Packet",
            "dz": "Dozen", "dozen": "Dozen",
        }
        qty_pattern = re.compile(r"(?P<value>\d*\.?\d+)\s*(?P<unit>[a-zA-Z]+)?", re.I)

        # ----------------------------------------
        # Ensure base objects exist
        # ----------------------------------------
        try:
            user = User.objects.get(email="kichujyothis@gmail.com")
        except User.DoesNotExist:
            logger.error("❌ [import_grocery_csv] Default user not found (kichujyothis@gmail.com).")
            return

        group, _ = CategoryGroup.objects.get_or_create(name="Household")
        grocery_cat, _ = PurchaseCategory.objects.get_or_create(
            name="Grocery",
            group=group,
            defaults={"created_by": user},
        )
        currency = Currency.objects.filter(is_base_currency=True).first() or Currency.objects.create(
            code="EUR", name="Euro", symbol="€"
        )

        updated_count, skipped_count, updated_items = 0, 0, 0

        # ----------------------------------------
        # Loop through each store column
        # ----------------------------------------
        for col in range(1, ncols, 2):
            date_str = date_row[col].strip()
            store_name = store_row[col].strip()
            total_str = total_row[col].strip()

            if not store_name:
                logger.warning(f"⚠️ [import_grocery_csv] Missing store name in column {col}, skipping.")
                continue

            # --- Parse date ---
            bill_date = None
            for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    dt = datetime.strptime(date_str, fmt)
                    bill_date = amsterdam_tz.localize(dt)
                    break
                except Exception:
                    continue
            if not bill_date:
                bill_date = timezone.now().astimezone(amsterdam_tz)

            # --- Parse total ---
            try:
                total_amount = float(total_str)
            except Exception:
                total_amount = 0.0

            # --- Store setup ---
            store_ref, _ = Store.objects.get_or_create(
                name=store_name, defaults={"created_by": user}
            )
            store_ref.categories.add(grocery_cat)
            store_ref.save()
            preferred_store = store_ref.preferred or store_ref

            # --- Candidate transactions ---
            amount_lower = total_amount - amount_tolerance
            amount_upper = total_amount + amount_tolerance
            date_lower = bill_date - timedelta(hours=buffer_hours)
            date_upper = bill_date + timedelta(hours=buffer_hours)

            candidate_qs = (
                Transaction.objects.filter(
                    Q(store=preferred_store) | Q(store__preferred=preferred_store),
                    date__gte=date_lower,
                    date__lte=date_upper,
                )
                .select_related("exchange_rate_record")
                .annotate(
                    converted_amount=ExpressionWrapper(
                        F("amount") / F("exchange_rate_record__provider_rate"),
                        output_field=DecimalField(max_digits=14, decimal_places=2),
                    )
                )
            )

            matched_tx = (
                candidate_qs.filter(
                    Q(amount__gte=amount_lower, amount__lte=amount_upper)
                    | Q(converted_amount__gte=amount_lower, converted_amount__lte=amount_upper)
                )
                .order_by("-date")
                .first()
            )

            if not matched_tx:
                logger.warning(
                    f"⚡ [import_grocery_csv] No match found for {store_name} ({bill_date.date()}, €{total_amount:.2f})"
                )
                skipped_count += 1
                continue

            # ----------------------------------------
            # Transaction item updates
            # ----------------------------------------
            old_item_count = matched_tx.items.count()
            matched_tx.items.all().delete()
            new_item_count = 0

            for row in rows[3:]:
                if not row or not row[0].strip():
                    continue
                product_name = row[0].strip()

                price_str = row[col].strip() if col < len(row) else ""
                qty_str = row[col + 1].strip() if col + 1 < len(row) else ""
                if not price_str and not qty_str:
                    continue

                try:
                    price = float(price_str)
                except Exception:
                    continue

                # Parse quantity & unit
                quantity = 1.0
                unit_ref = Unit.objects.filter(name="Piece").first()
                if qty_str:
                    m = qty_pattern.search(qty_str)
                    if m:
                        val = m.group("value")
                        unit = (m.group("unit") or "").lower().strip()
                        quantity = float(val) if val else 1.0
                        canonical_name = UNIT_ALIASES.get(unit, "Piece")
                        unit_ref = Unit.objects.filter(name=canonical_name).first() or unit_ref

                product_ref, _ = Product.objects.get_or_create(
                    name=product_name,
                    defaults={"category": grocery_cat, "preferred_unit": unit_ref, "created_by": user},
                )
                if not product_ref.category:
                    product_ref.category = grocery_cat
                    product_ref.save(update_fields=["category"])
                if not product_ref.preferred_unit:
                    product_ref.preferred_unit = unit_ref
                    product_ref.save(update_fields=["preferred_unit"])

                TransactionItem.objects.create(
                    transaction=matched_tx,
                    product=product_ref,
                    quantity=quantity,
                    unit=unit_ref,
                    price=price,
                    created_by=user,
                    date=matched_tx.date,
                )
                new_item_count += 1
                updated_items += 1

            # --- Update transaction ---
            matched_tx.date = bill_date
            expected_amount = Decimal(str(total_amount))
            if matched_tx.amount != expected_amount:
                diff = matched_tx.amount - expected_amount
                logger.warning(
                    f"⚠️ [import_grocery_csv] Amount mismatch for TX#{matched_tx.id} "
                    f"({matched_tx.store.name if matched_tx.store else 'No Store'}) "
                    f"→ Expected: {total_amount:.2f}, Found: {matched_tx.amount:.2f}, Diff: {diff:+.2f}"
                )

            matched_tx.processed = True
            matched_tx.save()
            updated_count += 1

            logger.info(
                f"🔁 [import_grocery_csv] Updated {store_name} ({bill_date.date()}): "
                f"{old_item_count} → {new_item_count} items | €{total_amount:.2f}"
            )

        # ----------------------------------------
        # Summary
        # ----------------------------------------
        logger.info("=========================================")
        logger.info(f"🔁 Transactions updated: {updated_count}")
        logger.info(f"⚡ Transactions skipped: {skipped_count}")
        logger.info(f"📦 Total items updated:  {updated_items}")
        logger.info("=========================================")
        logger.info("✅ [import_grocery_csv] Completed successfully.")
