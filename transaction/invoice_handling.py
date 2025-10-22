import json
import pytz
from datetime import datetime
from ai.utils import call_gemini_api
from catalog.models import PurchaseCategory, Store, Product, Brand, Currency
from catalog.utils import (
    get_or_create_brand,
    get_or_create_product_name,
    get_or_create_store,
)
from common.utils import convert_quantity, get_or_create_unit


def process_bill_image_llm(image_path: str, prompt_addition: str) -> str:
    """Handles OCR + LLM-based receipt parsing using Gemini."""
    try:
        if hasattr(image_path, "read"):  # UploadedFile object
            image_bytes = image_path.read()
        else:  # File path
            with open(image_path, "rb") as f:
                image_bytes = f.read()
    except Exception as e:
        print(f"⚠️ Error reading image: {e}")
        return "{}"

    # --- Get data for normalization ---
    all_categories = list(PurchaseCategory.objects.values_list("name", flat=True))
    categories_list = ", ".join(all_categories)

    preferred_shops_data = (
        Store.objects.filter(preferred__isnull=True)
        .prefetch_related("categories")
    )
    preferred_shops_list = ", ".join(
        f"{s.name} ({', '.join(c.name for c in s.categories.all()[:2]) or 'Uncategorized'})"
        for s in preferred_shops_data
    )

    preferred_items_data = (
        Product.objects.filter(preferred__isnull=True)
        .select_related("preferred_unit")
    )
    preferred_items_list = ", ".join(
        f"{i.name} ({i.preferred_unit.symbol or i.preferred_unit.name if i.preferred_unit else ''})"
        for i in preferred_items_data
    )

    preferred_brands_list = ", ".join(
        Brand.objects.filter(preferred__isnull=True).values_list("name", flat=True)
    )

    # --- Prompt for Gemini ---
    prompt = f"""
        You are an expert receipt parser and normalizer.
        From the uploaded bill image, extract and normalize all details.
        Return JSON in this exact structure:
        {{
            "store_name_raw": "string",
            "store_name_normalized": "string maybe in [{preferred_shops_list}]",
            "date": "YYYY-MM-DDTHH:MM:SS",
            "amount": number,
            "category": "one of [{categories_list}]",
            "currency": "ISO code like 'USD', 'EUR', 'INR'",
            "items": [
                {{
                    "name_raw": "string",
                    "name_normalized": "string maybe in [{preferred_items_list}]",
                    "brand_raw": "string or null",
                    "brand_normalized": "string maybe in [{preferred_brands_list}]",
                    "quantity": number,
                    "category": "one of [{categories_list}]",
                    "unit": "string",
                    "price": number
                }}
            ]
        }}
        Notes:
        - Normalize store & product names to their most common English equivalents.
        - Use the `preferred_items_list` for reference of normalized items + units.
        - Each item should have price and quantity; quantity defaults to 1.
        - Ensure total matches sum of item prices; if not, fix it.
    """

    print("🤖 Prompt prepared for Gemini.")
    raw_text = call_gemini_api(image_bytes=image_bytes, prompt=prompt + "\n" + prompt_addition)
    return raw_text


def process_bill_image(image_path: str):
    """
    Uses Gemini LLM to extract and normalize data from a receipt image.
    Returns structured transaction data ready for DB creation.
    """
    prompt_addition = ""
    tries = 0
    max_tries = 3
    print("📄 Starting bill image processing for:", image_path)

    while True:
        raw_text = process_bill_image_llm(image_path, prompt_addition=prompt_addition)
        prompt_addition = ""  # reset for next loop
        print(raw_text)

        # --- Clean code block output ---
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`").replace("json", "", 1).strip()

        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            print("⚠️ Invalid JSON returned by Gemini:", raw_text)
            return {
                "store": None,
                "date": None,
                "category": None,
                "currency": None,
                "amount": 0,
                "items": [],
            }

        # --- Currency ---
        currency_code = (data.get("currency") or "EUR").upper().strip()
        currency_ref = Currency.objects.filter(code=currency_code).first()

        # --- Store ---
        store_name_raw = data.get("store_name_raw") or data.get("store_name") or ""
        store_name_normalized = data.get("store_name_normalized") or store_name_raw
        store_ref = get_or_create_store(store_name_raw, store_name_normalized)

        # --- Date ---
        date_val = None
        if date_str := data.get("date"):
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    amsterdam_tz = pytz.timezone("Europe/Amsterdam")
                    naive_dt = datetime.strptime(date_str, fmt)
                    date_val = amsterdam_tz.localize(naive_dt)
                    break
                except ValueError:
                    continue

        # --- Category ---
        category_name = data.get("category") or "Others"
        category_ref = PurchaseCategory.objects.filter(name__iexact=category_name).first()
        if not category_ref:
            category_ref, _ = PurchaseCategory.objects.get_or_create(name="Others")
        print("🏷️ Parsed category:", category_name, "->", category_ref)

        # --- Total consistency ---
        items = data.get("items", [])
        total_from_items = round(sum(float(i.get("price", 0) or 0) for i in items), 2)
        amount = float(data.get("amount", total_from_items))

        if abs(amount - total_from_items) > 0.05:
            print(f"⚠️ Total mismatch: {amount} vs item sum {total_from_items}")
            prompt_addition = f"""
                The total amount you extracted ({amount}) does not match sum of item prices ({total_from_items}).
                Please correct and ensure they match.
            """

        # --- Parse items ---
        parsed_items = []
        for item in items:
            raw_name = str(item.get("name_raw") or "").strip()
            norm_name = str(item.get("name_normalized") or raw_name).strip()
            raw_brand = str(item.get("brand_raw") or "").strip()
            norm_brand = str(item.get("brand_normalized") or raw_brand).strip()

            unit_str = str(item.get("unit") or "").strip()
            unit_ref = get_or_create_unit(unit_str)

            brand_ref = get_or_create_brand(raw_brand, norm_brand)

            product_category_name = item.get("category") or "Others"
            product_category = PurchaseCategory.objects.filter(name__iexact=product_category_name).first()
            if not product_category:
                product_category, _ = PurchaseCategory.objects.get_or_create(name="Others")

            item_ref = get_or_create_product_name(
                raw_name,
                norm_name,
                brand_ref,
                unit_ref=unit_ref,
                category=product_category
            )

            canonical_unit = getattr(item_ref, "preferred_unit", None)
            try:
                if canonical_unit and unit_ref and unit_ref != canonical_unit:
                    quantity, _ = convert_quantity(
                        value=float(item.get("quantity", 1)),
                        from_unit=unit_ref,
                        to_unit=canonical_unit,
                    )
                    unit_ref = canonical_unit
                else:
                    quantity = float(item.get("quantity", 1))
            except Exception as e:
                print(f"⚠️ Unit conversion failed for {raw_name}: {e}")
                quantity = float(item.get("quantity", 1))

            parsed_items.append({
                "item_ref": item_ref,
                "brand_ref": brand_ref,
                "unit_ref": unit_ref,
                "quantity": quantity,
                "price": float(item.get("price", 0)),
                "name_raw": raw_name,
                "name_normalized": norm_name,
            })

        if prompt_addition:
            tries += 1
            if tries >= max_tries:
                print("⚠️ Max retries reached. Proceeding with available data.")
                break
            else:
                print("🔄 Retrying Gemini with correction prompt...")
                continue

        print("✅ Parsed and validated transaction successfully.")
        break

    return {
        "store": store_ref,
        "date": date_val,
        "category": category_ref,
        "currency": currency_ref,
        "amount": amount,
        "items": parsed_items,
    }
