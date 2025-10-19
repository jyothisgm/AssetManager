


import csv, re
from datetime import datetime

def validate_grocery_csv(path):
    with open(path, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    if len(rows) < 4:
        raise ValueError("File too short: need at least 4 rows (dates, stores, totals, items)")

    date_row, store_row, total_row = rows[0], rows[1], rows[2]
    ncols = len(date_row)
    print(f"🧾 Columns detected: {ncols}")

    # Validate column pairing pattern
    if (ncols - 1) % 2 != 0:
        raise ValueError("After first column, columns should come in pairs (price + qty)")

    # Validate header rows
    store_info = []
    for i in range(1, ncols, 2):
        date_str = date_row[i].strip()
        store = store_row[i].strip()
        total = total_row[i].strip()

        # date check
        ok_date = False
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                datetime.strptime(date_str, fmt)
                ok_date = True
                break
            except ValueError:
                continue
        if not ok_date:
            print(f"⚠️ Bad date format in column {i+1}: {date_str}")

        # store name
        if not store:
            print(f"⚠️ Missing store name in column {i+1}")

        # total
        try:
            float(total)
        except ValueError:
            print(f"⚠️ Invalid total value in column {i+1}: {total}")

        store_info.append((store, date_str, total))

    # Validate item rows
    bad_qty = re.compile(
        r"^\s*\d*\.?\d+\s*(kg|kilo|g|grm|grams?|ml|l|ltr|lit(er)?s?|pcs?|piece|packs?|sticks?|pages?|tabs?|tablets?|rolls?)?\s*$",
        re.I
    )
    for r_idx, row in enumerate(rows[3:], start=4):
        if not row or not row[0].strip():
            continue
        item = row[0].strip()
        for i in range(1, ncols, 2):
            price, qty = (row[i].strip() if i < len(row) else "", row[i+1].strip() if i+1 < len(row) else "")
            if price or qty:
                try:
                    float(price)
                except ValueError:
                    print(f"⚠️ Row {r_idx} ({item}) invalid price '{price}' in store col {i+1}")
                if qty and not bad_qty.match(qty):
                    print(f"⚠️ Row {r_idx} ({item}) invalid quantity '{qty}'")

    print("✅ Validation complete.")

# Example usage
validate_grocery_csv("NetherlandsGrocery.csv")
