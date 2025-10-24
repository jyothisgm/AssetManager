import csv
import os
import re
import uuid
from datetime import datetime, timedelta
import pytz

from django.db.models import Q, F, ExpressionWrapper, DecimalField
from decimal import Decimal
from django.core.management.base import BaseCommand
from django.utils import timezone
from catalog.models import (
    CategoryGroup,
    PurchaseCategory,
    Store,
    Product,
    Currency,
)
from common.models import Unit
from transaction.models import Transaction, TransactionItem
from user.models import User


class Command(BaseCommand):
    help = "🧾 Import grocery CSV → update existing transactions if matched (store+date+amount)."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to the grocery CSV file")

    def handle(self, *args, **opts):
        csv_path = opts["csv_path"]
        if not os.path.exists(csv_path):
            self.stderr.write(self.style.ERROR(f"❌ File not found: {csv_path}"))
            return

        self.stdout.write(f"📦 Importing grocery CSV: {csv_path}\n")

        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.reader(f))

        if len(rows) < 4:
            self.stderr.write("❌ CSV too short. Expect ≥4 rows (dates, stores, totals, then items).")
            return

        date_row, store_row, total_row = rows[0], rows[1], rows[2]
        ncols = len(date_row)
        if (ncols - 1) % 2 != 0:
            self.stderr.write("❌ After first column, columns must come in pairs (price, quantity).")
            return

        # --- Setup constants ---
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

        user = User.objects.get(email="kichujyothis@gmail.com")
        # Ensure Grocery category exists
        group, _ = CategoryGroup.objects.get_or_create(name="Household")
        grocery_cat, _ = PurchaseCategory.objects.get_or_create(name="Grocery", group=group, defaults={"created_by": user,})

        # Default currency
        currency = Currency.objects.filter(is_base_currency=True).first()
        if not currency:
            currency, _ = Currency.objects.get_or_create(code="EUR", defaults={"name": "Euro", "symbol": "€"})

        updated_count, skipped_count, updated_items = 0, 0, 0

        # --- Loop through stores (columns) ---
        for col in range(1, ncols, 2):
            date_str = date_row[col].strip()
            store_name = store_row[col].strip()
            total_str = total_row[col].strip()

            if not store_name:
                self.stdout.write(self.style.WARNING(f"⚠️ Missing store name in column {col}, skipping."))
                continue

            # Parse date
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

            # Parse total
            try:
                total_amount = float(total_str)
            except Exception:
                total_amount = 0.0

            # Find store (or its preferred)
            store_ref = Store.objects.filter(name__iexact=store_name).first()
            if not store_ref:
                store_ref, _ = Store.objects.get_or_create(name=store_name, defaults={"created_by": user,})
                store_ref.categories.add(grocery_cat)
                store_ref.save()

            preferred_store = store_ref.preferred or store_ref
            # Look for candidates by store or preferred

            candidate_qs = Transaction.objects.filter(
                Q(store=preferred_store) | Q(store__preferred=preferred_store)
            ).order_by('-date')

            # Define tolerance and date window
            amount_lower = total_amount - amount_tolerance
            amount_upper = total_amount + amount_tolerance
            date_lower = bill_date - timedelta(hours=buffer_hours)
            date_upper = bill_date + timedelta(hours=buffer_hours)

            # 🔍 Candidate transactions (ignore store name)
            candidate_qs = (
                candidate_qs.filter(
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

            # ✅ Try to match by normal or converted amount
            if amount_lower < 0:
                amount_lower = -amount_lower
                amount_upper = -amount_upper
            matched_tx = (
                candidate_qs.filter(
                    Q(amount__gte=amount_lower, amount__lte=amount_upper)
                    | Q(converted_amount__gte=amount_lower, converted_amount__lte=amount_upper)
                )
                .order_by("-date")
                .first()
            )

            if not matched_tx:
                # 🔍 Debug: show what we’re trying to match
                # self.stdout.write(
                #     f"\n🔍 Checking store: {store_name} ({bill_date.date()}, €{total_amount:.2f})"
                # )
                # self.stdout.write(f"   Preferred store: {preferred_store.name}")
                # self.stdout.write(f"   Matching window: ±{buffer_hours}h | Amount ±{amount_tolerance:.2f}")
                # self.stdout.write(f"   Found {candidate_qs.count()} transactions for this store")
                self.stdout.write(
                    f"\033[93m⚡ No match found for {store_name} ({bill_date.date()}, €{total_amount:.2f})\033[0m"
                )
                skipped_count += 1
                continue

            # --- Parse item rows ---
            old_item_count = matched_tx.items.count()
            matched_tx.items.all().delete()
            new_item_count = 0
            total_items_price = 0.0

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
                total_items_price += price

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
                    date=matched_tx.date
                )
                new_item_count += 1
                updated_items += 1

            # Update date to CSV date
            matched_tx.date = bill_date
            expected_amount = Decimal(str(total_amount))  # convert safely from float or str
            if matched_tx.amount != expected_amount:
                diff = matched_tx.amount - expected_amount
                print(
                    f"⚠️ Amount mismatch for Transaction #{matched_tx.id} "
                    f"({matched_tx.store.name if matched_tx.store else 'No Store'}) "
                    f"on {matched_tx.date.strftime('%Y-%m-%d')} [{matched_tx.currency.code if matched_tx.currency else 'No Currency'}]\n"
                    f"→ Expected: {total_amount:.2f}, Found: {matched_tx.amount:.2f}, Difference: {diff:+.2f}"
                )

            # matched_tx.amount = Decimal(str(total_amount))
            matched_tx.processed = True
            matched_tx.save()

            updated_count += 1

            # self.stdout.write(
            #     f"\033[92m🔁 Updated: {store_name} ({bill_date.date()})\n"
            #     f"    🧾 Old items: {old_item_count} → New items: {new_item_count}\n"
            #     f"    💰 Amount: €{total_amount:.2f}\033[0m"
            # )

        # --- Summary ---
        self.stdout.write("\n================ Summary ================")
        self.stdout.write(f"🔁  Transactions updated: {updated_count}")
        self.stdout.write(f"⚡  Transactions skipped: {skipped_count}")
        self.stdout.write(f"📦  Total items updated:  {updated_items}")
        self.stdout.write("=========================================\n")
