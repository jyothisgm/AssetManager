import json
import re
import sys
import requests
import pytz

from decimal import Decimal
from django.core.management.base import BaseCommand
from django.core.files.base import ContentFile
from django.utils import timezone

from account.models import Account, AccountType
from ai.utils import get_institution_data
from transaction.models import Transaction
from catalog.models import Currency, ExchangeRateRecord, PurchaseCategory, Store, Institution
from google import genai
from django.conf import settings
from user.models import User
from common.logging_config import logger  # ✅ unified logging


client = genai.Client(api_key=settings.GEMINI_KEY)


class Command(BaseCommand):
    help = "Import legacy AssetGroup, Assets, and Transactions JSON into Django models."

    # --------------------------- helpers ---------------------------

    def add_arguments(self, parser):
        parser.add_argument("--assetgroup", type=str, default="assetgroup.json", help="Path to assetgroup.json")
        parser.add_argument("--assets", type=str, default="assets.json", help="Path to assets.json")
        parser.add_argument("--transactions", type=str, default="transactions.json", help="Path to transactions.json")
        parser.add_argument("--categories", type=str, default="category.json", help="Path to category.json")

    def _slug(self, s: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", (s or "").lower()).strip("_")

    def _localize_amsterdam(self, dt):
        """Ensure all datetimes are timezone-aware in Europe/Amsterdam."""
        amsterdam_tz = pytz.timezone("Europe/Amsterdam")
        if timezone.is_naive(dt):
            return amsterdam_tz.localize(dt)
        return dt.astimezone(amsterdam_tz)

    def _strip_emojis(self, text: str) -> str:
        """Remove emojis and extra spaces from a string."""
        EMOJI_PATTERN = re.compile(
            "["
            "\U0001F1E0-\U0001F1FF"  # flags
            "\U0001F300-\U0001F5FF"  # symbols & pictographs
            "\U0001F600-\U0001F64F"  # emoticons
            "\U0001F680-\U0001F6FF"  # transport & map symbols
            "\U0001F700-\U0001F77F"  # alchemical symbols
            "\U0001F780-\U0001F7FF"  # geometric shapes extended
            "\U0001F800-\U0001F8FF"  # supplemental arrows-C
            "\U0001F900-\U0001F9FF"  # supplemental symbols and pictographs
            "\U0001FA00-\U0001FA6F"  # chess pieces etc.
            "\U0001FA70-\U0001FAFF"  # symbols & pictographs extended-A
            "\U00002700-\U000027BF"  # dingbats
            "\U000024C2-\U0001F251"  # enclosed characters
            "\U0000200D"             # zero width joiner
            "\U00002300-\U000023FF"  # technical symbols
            "\U00002600-\U000026FF"  # misc symbols
            "\U00002B00-\U00002BFF"  # arrows
            "\U0000FE0F"             # variation selector
            "]+", flags=re.UNICODE
        )
        if not text:
            return ""
        return EMOJI_PATTERN.sub("", text).strip()

    def _infer_group(self, name: str) -> str:
        """Infer general type category from the group name."""
        s = (name or "").lower().replace("-", " ").replace("_", " ")

        if any(k in s for k in ["insurance", "policy", "premium", "coverage", "insur"]):
            g = "Insurance"
        elif any(k in s for k in ["loan", "credit", "debt", "overdraft", "payable", "liability", "card"]):
            g = "Liability"
        elif any(k in s for k in ["salary", "bonus", "interest", "income", "profit", "dividend", "refund"]):
            g = "Income"
        elif any(k in s for k in ["expense", "bill", "rent", "grocery", "fuel", "shopping", "utilities", "payment", "spend"]):
            g = "Expense"
        elif any(k in s for k in ["equity", "capital", "share", "stock", "ownership"]):
            g = "Equity"
        else:
            g = "Asset"
        return g

    def _currency_from_uid(self, uid: str) -> str:
        """Extract currency code from UID (last '_' part uppercased)."""
        if not uid:
            return "EUR"
        return uid.split("_")[-1].upper().strip()

    # --------------------------- main ---------------------------

    def handle(self, *args, **options):
        logger.info("🚀 [import_legacy_assets] Starting legacy data import...")

        assetgroup_path = options["assetgroup"]
        assets_path = options["assets"]
        transactions_path = options["transactions"]
        categories_path = options["categories"]

        logger.info(
            f"📦 [import_legacy_assets] Paths → "
            f"AssetGroup: {assetgroup_path}, Assets: {assets_path}, "
            f"Transactions: {transactions_path}, Categories: {categories_path}"
        )

        # Resolve user
        try:
            user = User.objects.get(email="kichujyothis@gmail.com")
        except User.DoesNotExist:
            logger.error("❌ [import_legacy_assets] Default user not found: 'kichujyothis@gmail.com'. Aborting.")
            return

        # Load JSON
        try:
            with open(assetgroup_path, "r", encoding="utf-8") as f:
                assetgroups = json.load(f)
            with open(assets_path, "r", encoding="utf-8") as f:
                assets = json.load(f)
            with open(transactions_path, "r", encoding="utf-8") as f:
                transactions = json.load(f)
            with open(categories_path, "r", encoding="utf-8") as f:
                categories = json.load(f)
        except Exception as e:
            logger.exception(f"🔥 [import_legacy_assets] Error reading JSON files: {e}")
            return

        logger.info(
            f"✅ [import_legacy_assets] Loaded "
            f"{len(assetgroups)} asset groups, {len(assets)} assets, "
            f"{len(transactions)} transactions, {len(categories)} categories."
        )

        asset_by_uid = {a.get("uid"): a for a in assets}
        used_asset_uids = {t.get("assetUid") for t in transactions if t.get("assetUid")}

        try:
            # ------------------------------------------------------------------
            # 1️⃣ AccountTypes → import ALL AssetGroups
            # ------------------------------------------------------------------
            uid_to_type = {}
            fallback_type, _ = AccountType.objects.get_or_create(
                name="Others", defaults={"code": "others", "description": "Fallback"},
            )

            for group in assetgroups:
                name = (group.get("ACC_GROUP_NAME") or "").strip()
                if not name:
                    continue

                inferred = self._infer_group(name)
                code = self._slug(name)

                atype, _ = AccountType.objects.get_or_create(
                    name=name,
                    defaults={
                        "code": code,
                        "group": inferred.lower(),
                        "description": f"Imported as {inferred} (legacy TYPE={group.get('TYPE')})",
                    },
                )
                uid_to_type[group.get("uid")] = atype
                logger.debug(f"🧩 [import_legacy_assets] AccountType created/loaded: {atype.name} → {inferred}")

            logger.info("✅ [import_legacy_assets] AccountTypes processed.")

            # ------------------------------------------------------------------
            # 2️⃣ Accounts → only those used in transactions
            # ------------------------------------------------------------------
            uid_to_account = {}
            for uid in used_asset_uids:
                asset = asset_by_uid.get(uid)
                if not asset:
                    continue

                name = (asset.get("NIC_NAME") or "").strip()
                if not name:
                    continue

                currency_code = self._currency_from_uid(asset.get("currencyUid"))
                currency, _ = Currency.objects.get_or_create(code=currency_code, defaults={"name": currency_code})
                account_type = uid_to_type.get(asset.get("groupUid"), fallback_type)

                acc, _ = Account.objects.get_or_create(
                    name=name,
                    defaults={
                        "account_type": account_type,
                        "currency": currency,
                        "created_by": user,
                    },
                )
                uid_to_account[uid] = acc
                logger.debug(
                    f"🏦 [import_legacy_assets] Account loaded: {acc.name} "
                    f"(Type: {account_type.name}, Currency: {currency.code})"
                )

            logger.info(f"✅ [import_legacy_assets] Accounts processed: {len(uid_to_account)}")

            # ------------------------------------------------------------------
            # 2️⃣b Institutions (AI-based batch inference)
            # ------------------------------------------------------------------
            logger.info("🤖 [import_legacy_assets] Using Gemini to infer institutions (batch)...")

            inst_names = sorted({acc.name.strip() for acc in uid_to_account.values() if acc.name.strip()})
            ai_lookup = get_institution_data(inst_names, [])

            for acc in uid_to_account.values():
                inst_name = acc.name.strip()
                if not inst_name or inst_name.lower() == "cash":
                    continue

                ai_info = ai_lookup.get(inst_name, {})
                name = ai_info.get("name", inst_name)
                short_name = ai_info.get("short_name", inst_name[:50])
                itype = ai_info.get("type", "other").lower()
                country = ai_info.get("country", "Unknown")
                website = ai_info.get("website")
                logo_url = ai_info.get("logo")

                inst, _ = Institution.objects.get_or_create(
                    short_name=short_name,
                    defaults={
                        "name": name,
                        "type": itype,
                        "country": country,
                        "website": website,
                        "created_by": user,
                        "is_deleted": True,
                    },
                )

                # ✅ download logo if available
                if logo_url:
                    try:
                        logger.debug(f"🔗 [import_legacy_assets] Fetching logo for {inst_name}: {logo_url}")
                        resp = requests.get(logo_url, timeout=10, stream=True)
                        content_type = resp.headers.get("content-type", "")
                        if resp.status_code == 200 and content_type.startswith("image"):
                            ext = content_type.split("/")[-1].split(";")[0]
                            if len(ext) > 4 or not ext.isalpha():
                                ext = "png"
                            file_name = f"{(short_name or inst_name).replace(' ', '_')}.{ext}"
                            inst.logo.save(file_name, ContentFile(resp.content))
                            inst.save(update_fields=["logo"])
                            logger.info(f"🖼️ [import_legacy_assets] Added logo for {inst_name} ({file_name})")
                        else:
                            logger.warning(
                                f"⚠️ [import_legacy_assets] Skipped logo for {inst_name}: "
                                f"invalid response ({resp.status_code}, {content_type})"
                            )
                    except Exception as e:
                        logger.warning(f"⚠️ [import_legacy_assets] Could not fetch logo for {inst_name}: {e}", exc_info=True)

            # ------------------------------------------------------------------
            # 3️⃣ Transactions
            # ------------------------------------------------------------------
            created = 0
            tx_uid_map = {}         # maps legacy AID -> new Transaction
            tx_transfer_map = {}    # maps txUidTrans -> list of Django Transactions
            category_map = {c["uid"]: c["NAME"].strip() for c in categories}
            category_alias_map = {"Eating out": "Restaurant", "Kitchen": "Grocery"}

            conversion_map = {}
            conversion_fees_map = {}

            for tx in transactions:
                try:
                    asset_uid = tx.get("assetUid")
                    acc_ref = uid_to_account.get(asset_uid)
                    if not acc_ref:
                        continue

                    # date
                    date_str = tx.get("ZDATE") or tx.get("date")
                    if date_str:
                        if str(date_str).isdigit():
                            raw_date = timezone.datetime.fromtimestamp(int(date_str) / 1000)
                        else:
                            try:
                                raw_date = timezone.datetime.strptime(date_str, "%Y-%m-%d")
                            except Exception:
                                raw_date = timezone.now()
                    else:
                        raw_date = timezone.now()

                    date_val = self._localize_amsterdam(raw_date)

                    # type
                    do_type = str(tx.get("DO_TYPE") or "").lower()
                    if do_type in ("income", "in", "credit", "0"):
                        ttype = "credit"
                    elif do_type in ("expense", "debit", "out", "1"):
                        ttype = "debit"
                    elif do_type in ("transfer", "move", "3"):
                        ttype = "transfer_debit"
                    elif do_type in ("transfer", "move", "4"):
                        ttype = "transfer_credit"
                    else:
                        ttype = "debit"  # sensible default

                    # category
                    cat_uid = tx.get("ctgUid")
                    cat_ref = None
                    if cat_uid and cat_uid in category_map:
                        cat_name = self._strip_emojis(category_map[cat_uid]).strip()
                        cat_ref = PurchaseCategory.objects.filter(name__icontains=cat_name).first()

                        if not cat_ref:
                            aliased = category_alias_map.get(cat_name)
                            if aliased:
                                cat_ref = PurchaseCategory.objects.filter(name__icontains=aliased).first()
                            else:
                                logger.debug(
                                    f"❌ [import_legacy_assets] No category matched: '{cat_name}' "
                                    f"(AID={tx.get('AID')})"
                                )

                    # store/shop
                    content = tx.get("ZCONTENT") or tx.get("store")
                    store_ref = None
                    if content:
                        store_ref, _ = Store.objects.get_or_create(
                            name=content.strip(), defaults={"created_by": user}
                        )
                        if cat_ref:
                            store_ref.categories.add(cat_ref)
                        store_ref.save()

                    tx_fee_uid = tx.get("txUidFee") or None
                    tx_trans_uid = tx.get("txUidTrans") or None
                    exchange_rate_record = conversion_map.get(tx_trans_uid, None) or conversion_fees_map.get(tx_fee_uid, None)

                    currency_codes = (tx.get("currencyUid") or "EUR_EUR").split("_")
                    amount = Decimal(str(tx.get("AMOUNT_ACCOUNT") or tx.get("amount") or 0))

                    # Currency logic branches — keep logs as debug/warning
                    if float(tx.get("IN_ZMONEY", 0)) == float(tx.get("AMOUNT_ACCOUNT", 0)) == float(tx.get("ZMONEY", 0)):
                        currency_code = currency_codes[1].upper().strip()
                        if currency_codes[0].upper().strip() != currency_codes[1].upper().strip():
                            logger.warning(
                                f"❌ [import_legacy_assets] Anomaly 'all-equal' but currencies differ: {currency_codes}"
                            )
                    else:
                        if float(tx.get("ZMONEY", 0)) == float(tx.get("IN_ZMONEY", 0)):
                            logger.warning(
                                "❌ [import_legacy_assets] Should not exist (transfer to other currency but ZMONEY==IN_ZMONEY): "
                                f"{acc_ref}, {ttype}, {store_ref}, {tx.get('ZMONEY')}, {tx.get('IN_ZMONEY')}, {tx.get('AMOUNT_ACCOUNT')}"
                            )

                        elif float(tx.get("ZMONEY", 0)) == float(tx.get("AMOUNT_ACCOUNT", 0)):
                            # transfer credited in Euros
                            currency_code = currency_codes[0].upper().strip()
                            provider_rate = (
                                float(tx.get("IN_ZMONEY", 0)) / float(tx.get("ZMONEY", 1))
                                if float(tx.get("ZMONEY", 0)) != 0 else 1
                            )

                            if tx_trans_uid or tx_fee_uid:
                                if exchange_rate_record:
                                    # validations (debug-level)
                                    if any(
                                        value is not None
                                        for value in (
                                            exchange_rate_record.get("base_currency"),
                                            exchange_rate_record.get("quote_currency"),
                                            exchange_rate_record.get("provider_rate"),
                                        )
                                    ):
                                        if exchange_rate_record.get("tx_fee_uid") != tx_fee_uid:
                                            logger.debug("❌ [import_legacy_assets] Wrong Fee ID (branch 1)")
                                        if exchange_rate_record.get("base_currency") != currency_codes[1].upper().strip():
                                            logger.debug("❌ [import_legacy_assets] Base currency wrong (branch 1)")
                                        if exchange_rate_record.get("quote_currency") != currency_codes[0].upper().strip():
                                            logger.debug("❌ [import_legacy_assets] Quote currency wrong (branch 1)")
                                        if exchange_rate_record.get("provider_rate") != provider_rate:
                                            logger.debug(
                                                f"❌ [import_legacy_assets] Wrong provider rate "
                                                f"{exchange_rate_record.get('provider_rate')} != {provider_rate}"
                                            )
                                            logger.debug(
                                                f"❌ [import_legacy_assets] Amounts mismatch "
                                                f"{exchange_rate_record.get('base_amount')} != {tx.get('IN_ZMONEY')} ; "
                                                f"{exchange_rate_record.get('quote_amount')} != {float(tx.get('ZMONEY', 0))}"
                                            )
                                    exchange_rate_record.update({
                                        "base_currency": currency_codes[1].upper().strip(),
                                        "quote_currency": currency_codes[0].upper().strip(),
                                        "provider_rate": provider_rate,
                                    })
                                else:
                                    exchange_rate_record = {
                                        "base_currency": currency_codes[1].upper().strip(),
                                        "quote_currency": currency_codes[0].upper().strip(),
                                        "provider_rate": provider_rate,
                                        "tx_fee_uid": tx_fee_uid,
                                        "fee": 0,
                                        "tx": [],
                                        "base_amount": tx.get("IN_ZMONEY"),
                                        "quote_amount": float(tx.get("ZMONEY", 0)),
                                    }
                            else:
                                logger.warning(
                                    "❌ [import_legacy_assets] Rogue transfer credited in EUR without IDs: "
                                    f"{acc_ref}, {ttype}, {store_ref}, {tx.get('ZMONEY')}, {tx.get('IN_ZMONEY')}, {tx.get('AMOUNT_ACCOUNT')}"
                                )

                        elif float(tx.get("ZMONEY", 0)) == 0:
                            currency_code = currency_codes[1].upper().strip()
                            if float(tx.get("IN_ZMONEY", 0)) != float(tx.get("AMOUNT_ACCOUNT", 0)):
                                logger.warning(
                                    "❌ [import_legacy_assets] Rogue transaction (ZMONEY=0, IN_ZMONEY!=AMOUNT_ACCOUNT): "
                                    f"{acc_ref}, {ttype}, {store_ref}, {tx.get('ZMONEY')}, {tx.get('IN_ZMONEY')}, {tx.get('AMOUNT_ACCOUNT')}"
                                )

                        elif float(tx.get("IN_ZMONEY", 0)) == float(tx.get("AMOUNT_ACCOUNT", 0)):
                            # other currency account → EUR
                            currency_code = currency_codes[1].upper().strip()
                            provider_rate = (
                                float(tx.get("AMOUNT_ACCOUNT", 0)) / float(tx.get("ZMONEY", 1))
                                if float(tx.get("ZMONEY", 0)) != 0 else 1
                            )

                            if tx_fee_uid and not tx_trans_uid:
                                if exchange_rate_record:
                                    exchange_rate_record["tx_fee_uid"] = tx_fee_uid
                                    exchange_rate_record["fee"] = float(tx.get("AMOUNT_ACCOUNT", 0))
                                else:
                                    exchange_rate_record = {
                                        "base_currency": None,
                                        "quote_currency": None,
                                        "provider_rate": None,
                                        "tx_fee_uid": tx_fee_uid,
                                        "fee": float(tx.get("AMOUNT_ACCOUNT", 0)),
                                        "tx": [],
                                        "base_amount": None,
                                        "quote_amount": None,
                                    }
                            else:
                                if exchange_rate_record:
                                    if any(
                                        value is not None
                                        for value in (
                                            exchange_rate_record.get("base_currency"),
                                            exchange_rate_record.get("quote_currency"),
                                            exchange_rate_record.get("provider_rate"),
                                        )
                                    ):
                                        if exchange_rate_record.get("tx_fee_uid") != tx_fee_uid:
                                            logger.debug("❌ [import_legacy_assets] Wrong Fee ID (branch 2)")
                                        if exchange_rate_record.get("base_currency") != currency_codes[1].upper().strip():
                                            logger.debug("❌ [import_legacy_assets] Base currency wrong (branch 2)")
                                        if exchange_rate_record.get("quote_currency") != currency_codes[0].upper().strip():
                                            logger.debug("❌ [import_legacy_assets] Quote currency wrong (branch 2)")
                                        if exchange_rate_record.get("provider_rate") != provider_rate:
                                            logger.debug(
                                                f"❌ [import_legacy_assets] Wrong provider rate "
                                                f"{exchange_rate_record.get('provider_rate')} != {provider_rate}"
                                            )
                                            logger.debug(
                                                f"❌ [import_legacy_assets] Amounts mismatch "
                                                f"{exchange_rate_record.get('base_amount')} != {tx.get('AMOUNT_ACCOUNT')} ; "
                                                f"{exchange_rate_record.get('quote_amount')} != {float(tx.get('ZMONEY', 0))}"
                                            )
                                    exchange_rate_record.update({
                                        "base_currency": currency_codes[1].upper().strip(),
                                        "quote_currency": currency_codes[0].upper().strip(),
                                        "provider_rate": provider_rate,
                                        "base_amount": float(tx.get("IN_ZMONEY", 0)),
                                        "quote_amount": float(tx.get("ZMONEY", 0)),
                                    })
                                else:
                                    exchange_rate_record = {
                                        "base_currency": currency_codes[1].upper().strip(),
                                        "quote_currency": currency_codes[0].upper().strip(),
                                        "provider_rate": provider_rate,
                                        "tx_fee_uid": tx_fee_uid,
                                        "fee": 0,
                                        "tx": [],
                                        "base_amount": float(tx.get("IN_ZMONEY", 0)),
                                        "quote_amount": float(tx.get("ZMONEY", 0)),
                                    }

                    # Create transaction
                    new_tx = Transaction.objects.create(
                        transaction_type=ttype,
                        amount=amount,
                        date=date_val,
                        store=store_ref,
                        description="",
                        account=acc_ref,
                        category=cat_ref,
                        currency=Currency.objects.get(code=currency_code),
                        processed=True,
                        created_by=user,
                    )

                    # Attach exchange record inline if no IDs present
                    if exchange_rate_record:
                        if not tx_trans_uid and not tx_fee_uid:
                            try:
                                base_code = exchange_rate_record.get("base_currency")
                                quote_code = exchange_rate_record.get("quote_currency")
                                provider_rate = exchange_rate_record.get("provider_rate")
                                base_currency = Currency.objects.get(code=base_code)
                                quote_currency = Currency.objects.get(code=quote_code)
                                provider = None
                                if store_ref:
                                    provider, _ = Institution.objects.get_or_create(
                                        short_name__iexact=acc_ref.name.strip(),
                                        defaults={"created_by": user},
                                    )

                                exch = ExchangeRateRecord.objects.create(
                                    base_currency=base_currency,
                                    quote_currency=quote_currency,
                                    provider_rate=Decimal(str(provider_rate)),
                                    provider=provider,
                                    fee_percent=Decimal(str(round(exchange_rate_record.get("fee", 0), 3))),
                                    date=new_tx.date,
                                    created_by=user,
                                )
                                new_tx.exchange_rate_record = exch
                                new_tx.save()
                            except Exception as e:
                                tb = sys.exc_info()[2]
                                line_number = getattr(tb, "tb_lineno", "?")
                                logger.warning(
                                    f"⚠️ [import_legacy_assets] Could not create standalone ExchangeRateRecord: {e} (line {line_number})"
                                )

                        if tx_trans_uid:
                            exchange_rate_record.setdefault("tx", []).append(new_tx)
                            exchange_rate_record["tx_fee"] = exchange_rate_record.get("tx_fee")
                            conversion_map[tx_trans_uid] = exchange_rate_record
                        if tx_fee_uid:
                            if not tx_trans_uid:
                                exchange_rate_record["tx_fee"] = new_tx
                            conversion_fees_map[tx_fee_uid] = exchange_rate_record

                    aid = tx.get("AID")
                    if aid:
                        tx_uid_map[str(aid)] = new_tx

                    tx_uid_trans = tx.get("txUidTrans")
                    if tx_uid_trans:
                        tx_transfer_map.setdefault(tx_uid_trans, []).append(new_tx)

                    created += 1

                except Exception as e:
                    tb = sys.exc_info()[2]
                    line_number = getattr(tb, "tb_lineno", "?")
                    logger.warning(
                        f"❌ [import_legacy_assets] Skipping transaction (AID={tx.get('AID')}): {e} (line {line_number})"
                    )

            # ------------------------------------------------------------------
            # 4️⃣ Link transfer transactions (by txUidTrans)
            # ------------------------------------------------------------------
            logger.info("🔄 [import_legacy_assets] Linking transfer transactions...")
            linked_count = 0
            for uid_trans, tx_list in tx_transfer_map.items():
                if len(tx_list) == 2:
                    a, b = tx_list
                    a.linked_transaction = b
                    b.linked_transaction = a
                    a.save(update_fields=["linked_transaction"])
                    b.save(update_fields=["linked_transaction"])
                    linked_count += 1
                else:
                    logger.warning(f"⚠️ [import_legacy_assets] Skipping transfer {uid_trans}: {len(tx_list)} entries found")

            logger.info(f"✅ [import_legacy_assets] Linked {linked_count} transfer pairs")

            # ------------------------------------------------------------------
            # 5️⃣ Create ExchangeRateRecord from conversion_map + link to transactions
            # ------------------------------------------------------------------
            logger.info("💱 [import_legacy_assets] Creating ExchangeRateRecords and linking transactions...")
            for key, record_data in conversion_map.items():
                try:
                    base_code = record_data.get("base_currency")
                    quote_code = record_data.get("quote_currency")
                    provider_rate = record_data.get("provider_rate") or 1
                    tx_fee = record_data.get("tx_fee") if "tx_fee" in record_data else None
                    base_amount = record_data.get("base_amount") or 0
                    quote_amount = record_data.get("quote_amount") or 0

                    if not (base_code and quote_code):
                        logger.warning(f"❌ [import_legacy_assets] Skipping ExchangeRateRecord {key}: missing currencies")
                        continue

                    base_currency = Currency.objects.get(code=base_code)
                    quote_currency = Currency.objects.get(code=quote_code)
                    provider = None

                    first_tx = record_data["tx"][0] if record_data.get("tx") else None
                    if first_tx and first_tx.store:
                        provider, _ = Institution.objects.get_or_create(
                            short_name__iexact=first_tx.store.name,
                            defaults={"short_name": first_tx.store.name.strip(), "created_by": user},
                        )
                    elif tx_fee and tx_fee.store:
                        provider, _ = Institution.objects.get_or_create(
                            short_name__iexact=tx_fee.store.name,
                            defaults={"short_name": tx_fee.store.name.strip(), "created_by": user},
                        )

                    try:
                        fee_percent = (float(tx_fee.amount) / float(base_amount)) * 100 if base_amount else 0
                    except Exception:
                        fee_percent = 0

                    exch = ExchangeRateRecord.objects.create(
                        base_currency=base_currency,
                        quote_currency=quote_currency,
                        provider_rate=Decimal(str(provider_rate)),
                        provider=provider,
                        fee_percent=Decimal(str(round(fee_percent, 3))),
                        created_by=user,
                    )

                    # Link to transactions
                    for t in record_data.get("tx", []):
                        t.exchange_rate_record = exch
                        exch.date = t.date
                        if tx_fee:
                            t.fee = tx_fee
                        t.save()
                        exch.save()

                    logger.info(
                        f"✅ [import_legacy_assets] ExchangeRateRecord {base_code}->{quote_code} @ {provider_rate:.4f} "
                        f"({len(record_data.get('tx', []))} tx, fee_tx={tx_fee.id if tx_fee else 'None'})"
                    )
                except Exception as e:
                    logger.warning(f"⚠️ [import_legacy_assets] Skipping ExchangeRateRecord {key}: {e}")

            logger.info(f"✅ [import_legacy_assets] Imported {created} transactions")
            logger.info("🎉 [import_legacy_assets] Import complete")

        except Exception as e:
            logger.exception("🔥 [import_legacy_assets] Unhandled error during import:")
            raise
