import csv
import os
import re
import uuid
from datetime import datetime
from django.utils import timezone
import pytz
from django.core.management.base import BaseCommand
from django.utils import timezone
from bills.models import (
    Store, Bill, BillItem, ItemName, Unit,
    PurchaseCategory, CategoryGroup
)


class Command(BaseCommand):
    help = "Import grocery data from a multi-store CSV file into Bill, BillItem, and related models."

    def add_arguments(self, parser):
        parser.add_argument("csv_path", type=str, help="Path to the grocery CSV file")

    def handle(self, *args, **opts):
        csv_path = opts["csv_path"]

        if not os.path.exists(csv_path):
            self.stderr.write(self.style.ERROR(f"❌ File not found: {csv_path}"))
            return

        self.stdout.write(f"📦 Importing grocery CSV: {csv_path}")

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

        # ------------------------------------------
        # 0️⃣ Ensure Grocery-Household category exists
        # ------------------------------------------
        group, _ = CategoryGroup.objects.get_or_create(name="Household")
        grocery_cat, _ = PurchaseCategory.objects.get_or_create(name="Grocery")
        grocery_cat.groups.add(group)

        # ------------------------------------------
        # 1️⃣ Unit alias mapping (must exist in Unit table)
        # ------------------------------------------
        UNIT_ALIASES = {
            "g": "Gram", "gram": "Gram", "grams": "Gram", "grm": "Gram", "gms": "Gram",
            "kg": "Kilogram", "kgs": "Kilogram", "kilo": "Kilogram",
            "ml": "Millilitre", "millilitre": "Millilitre", "milliliter": "Millilitre",
            "l": "Litre", "ltr": "Litre", "litre": "Litre", "liter": "Litre", "lt": "Litre",
            "m": "Metre", "metre": "Metre", "meter": "Metre",
            "cm": "Centimetre", "cms": "Centimetre",
            "mm": "Millimetre",
            "pc": "Piece", "pcs": "Piece", "piece": "Piece", "pieces": "Piece", "unit": "Piece",
            "pack": "Packet", "packs": "Packet", "packet": "Packet", "packets": "Packet",
            "dz": "Dozen", "dozen": "Dozen",
            "stick": "Piece", "sticks": "Piece",
            "tab": "Piece", "tabs": "Piece", "tablet": "Piece", "tablets": "Piece",
            "roll": "Piece", "rolls": "Piece",
            "page": "Piece", "pages": "Piece",
        }

        qty_pattern = re.compile(r"(?P<value>\d*\.?\d+)\s*(?P<unit>[a-zA-Z]+)?", re.I)

        created_bills = 0
        created_items = 0

        # ------------------------------------------
        # 2️⃣ Process each store column pair
        # ------------------------------------------
        for col in range(1, ncols, 2):
            date_str = date_row[col].strip()
            store_name = store_row[col].strip()
            total_str = total_row[col].strip()

            if not store_name:
                self.stdout.write(self.style.WARNING(f"⚠️ Missing store name in columns {col}-{col+1}, skipping."))
                continue

            # Parse date
            amsterdam_tz = pytz.timezone("Europe/Amsterdam")

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

            # Store reference
            store_ref, _ = Store.objects.get_or_create(name=store_name, defaults={"category": grocery_cat})
            if not store_ref.category:
                store_ref.category = grocery_cat
                store_ref.save(update_fields=["category"])

            # Bill record
            bill = Bill.objects.create(
                id=uuid.uuid4(),
                uploaded_at=bill_date,
                bill_date=bill_date,
                store=store_ref,
                store_name_raw=store_name,
                purchase_category=grocery_cat,
                processed=True,
                total_amount=total_amount,
            )
            created_bills += 1

            # ------------------------------------------
            # 3️⃣ Parse item rows
            # ------------------------------------------
            total_items_price = 0.0

            for row in rows[3:]:
                if not row or not row[0].strip():
                    continue
                item_name = row[0].strip()

                price_str = row[col].strip() if col < len(row) else ""
                qty_str = row[col + 1].strip() if col + 1 < len(row) else ""
                if not price_str and not qty_str:
                    continue

                # Price
                try:
                    price = float(price_str)
                except Exception:
                    self.stdout.write(f"⚠️ Invalid price '{price_str}' for {item_name}")
                    continue

                total_items_price += price

                # Quantity + Unit
                quantity = 1.0
                unit_ref = Unit.objects.get(name="Piece")  # default
                if qty_str:
                    m = qty_pattern.search(qty_str)
                    if m:
                        val = m.group("value")
                        unit = (m.group("unit") or "").lower().strip()
                        quantity = float(val) if val else 1.0

                        canonical_name = UNIT_ALIASES.get(unit)
                        if not canonical_name:
                            self.stdout.write(self.style.WARNING(
                                f"⚠️ Unknown unit '{unit}' for {item_name}, defaulting to Piece"
                            ))
                            canonical_name = "Piece"

                        try:
                            unit_ref = Unit.objects.get(name=canonical_name)
                        except Unit.DoesNotExist:
                            self.stdout.write(self.style.WARNING(
                                f"⚠️ Unit '{canonical_name}' not found in DB, defaulting to Piece"
                            ))
                            unit_ref = Unit.objects.get(name="Piece")
                    else:
                        self.stdout.write(f"⚠️ Could not parse quantity '{qty_str}' for {item_name}")

                # Item
                item_ref, _ = ItemName.objects.get_or_create(name=item_name)

                BillItem.objects.create(
                    bill=bill,
                    item_name=item_ref,
                    item_name_raw=item_name,
                    quantity=quantity,
                    unit=unit_ref,
                    unit_raw=unit_ref.symbol,
                    price=price,
                )
                created_items += 1

            # ✅ Validate total amount vs item sum
            if abs(total_items_price - total_amount) > 0.05:  # allow small rounding error
                self.stdout.write(self.style.WARNING(
                    f"⚠️ Total mismatch for {store_name} ({bill_date.date()}): "
                    f"Bill total {total_amount:.2f}, sum of items {total_items_price:.2f}"
                ))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f"✅ Imported bill for {store_name} ({bill_date.date()}) with {bill.items.count()} items."
                ))

        self.stdout.write(self.style.SUCCESS(
            f"\n🎉 Import complete: {created_bills} bills, {created_items} items total."
        ))
