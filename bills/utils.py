import json
from datetime import datetime
from google import genai
from google.genai import types
from django.conf import settings
from .models import Store, ItemName, Unit, PurchaseCategory, CategoryGroup, Brand

client = genai.Client(api_key=settings.GEMINI_KEY)

def get_or_create_store(raw_name: str, normalized_name: str | None = None) -> Store | None:
    """Find or create a Store using both raw and normalized names."""
    if not raw_name and not normalized_name:
        return None

    normalized_name = normalized_name or raw_name

    # 1️⃣ Try matching the canonical name (normalized)
    store = Store.objects.filter(name__iexact=normalized_name).first()

    # 2️⃣ Try matching a variant (raw name)
    if not store:
        variant = Store.objects.filter(name__iexact=raw_name).first()
        if variant and variant.preferred:
            store = variant.preferred
        elif variant:
            store = variant

    # 3️⃣ If nothing exists, create canonical + variant if names differ
    if not store:
        store = Store.objects.create(name=normalized_name)
        if raw_name.lower() != normalized_name.lower():
            variant = Store.objects.create(name=raw_name, preferred=store)
            # Optional: maintain explicit reverse link consistency
            store.variants.add(variant)

    return store


def get_or_create_item_name(raw_name: str, normalized_name: str | None = None, unit_ref=None) -> ItemName | None:
    """Find or create an ItemName using both raw and normalized names."""
    if not raw_name and not normalized_name:
        return None

    normalized_name = normalized_name or raw_name

    # 1️⃣ Try matching the canonical item
    item = ItemName.objects.filter(name__iexact=normalized_name).first()

    # 2️⃣ Try matching a variant
    if not item:
        variant = ItemName.objects.filter(name__iexact=raw_name).first()
        if variant and variant.preferred:
            item = variant.preferred
        elif variant:
            item = variant

    # 3️⃣ If still missing, create canonical + variant if needed
    if not item:
        item = ItemName.objects.create(name=normalized_name)
        if raw_name.lower() != normalized_name.lower():
            variant = ItemName.objects.create(name=raw_name, preferred=item)
            item.variants.add(variant)

    # 4️⃣ Auto-set preferred_unit for canonical if missing
    if unit_ref and not item.preferred_unit:
        item.preferred_unit = unit_ref
        item.save(update_fields=["preferred_unit"])


    # 5️⃣ Ensure variant inherits canonical preferred_unit
    if item.preferred and item.preferred.preferred_unit and not item.preferred_unit:
        item.preferred_unit = item.preferred.preferred_unit
        item.save(update_fields=["preferred_unit"])
    return item


def get_or_create_unit(name: str):
    """Return existing Unit (case-insensitive), else create a new one."""
    if not name:
        return None
    unit = Unit.objects.filter(name__iexact=name).first()
    if not unit:
        unit = Unit.objects.create(name=name, category="pieces")  # default fallback
    return unit

def get_or_create_brand(raw_name: str, normalized_name: str | None = None):
    """Find or create a Brand using both raw and normalized names."""
    if not raw_name and not normalized_name:
        return None

    normalized_name = normalized_name or raw_name

    # 1️⃣ Try canonical
    brand = Brand.objects.filter(name__iexact=normalized_name).first()

    # 2️⃣ Try variant
    if not brand:
        variant = Brand.objects.filter(name__iexact=raw_name).first()
        if variant and variant.preferred:
            brand = variant.preferred
        elif variant:
            brand = variant

    # 3️⃣ Create new canonical + variant if needed
    if not brand:
        brand = Brand.objects.create(name=normalized_name)
        if raw_name.lower() != normalized_name.lower():
            variant = Brand.objects.create(name=raw_name, preferred=brand)
            brand.variants.add(variant)

    return brand


def process_bill_image_llm(image_path: str, prompt_addition: str) -> str:

    # --- 1️⃣ Prepare image bytes ---
    with open(image_path, "rb") as f:
        image_bytes = f.read()

    # --- 2️⃣ Available categories ---
    all_categories = list(PurchaseCategory.objects.values_list("name", flat=True))
    categories_list = ", ".join(all_categories)
    
    all_shops = list(Store.objects.values_list("name", flat=True))
    shop_list = ", ".join(all_shops)
    
    preferred_shops_data = Store.objects.filter(preferred__isnull=True).select_related("category")
    preferred_shops_list = ", ".join(
        f"{s.name} ({s.category.name if s.category else 'Uncategorized'})"
        for s in preferred_shops_data
    )
    
    all_items = list(ItemName.objects.values_list("name", flat=True))
    items_list = ", ".join(all_items)
    
    preferred_items_data = ItemName.objects.filter(preferred__isnull=True).select_related("preferred_unit")
    preferred_items_list = ", ".join(
        f"{i.name} ({i.preferred_unit.symbol or i.preferred_unit.name if i.preferred_unit else 'unit'})"
        for i in preferred_items_data
    )
    print(preferred_items_list)
    
    preferred_brands_list = ", ".join(Brand.objects.filter(preferred__isnull=True).values_list("name", flat=True))
    
    # --- 3️⃣ Build prompt ---
    prompt = f"""
    You are an expert receipt parser and normalizer.

    From the uploaded bill image, extract and normalize all details.
    Return JSON in this exact structure:
    {{
        "store_name_raw": "string maybe in [{shop_list}]",
        "store_name_normalized": "string maybe in [{preferred_shops_list}]",
        "bill_date": "YYYY-MM-DDTHH:MM:SS",
        "total_amount": number,
        "category": "one of [{categories_list}]",
        "items": [
            {{
                "name_raw": "string maybe in [{items_list}]",
                "name_normalized": "string maybe in [{preferred_items_list}]",
                "brand_raw": "string or null",
                "brand_normalized": "string maybe in [{preferred_brands_list}]",
                "quantity": number,
                "unit": "string",
                "price": number,
            }}
        ]
    }}

    Notes:
    - Normalize store & product names to their most common English equivalents.
    - Classify each shop into the *single best* category from the list.
    - preferred_items_list contains the most common English names for items + its unit of measurement. Unit is a string like "kg", "liters", "pieces", etc. Return without the unit and use the `unit` field for getting the quantity unit.
    - Normalized item names should not include brand or quantity.
    - `brand_normalized` should represent the official brand name (e.g., 'Nestlé', 'Coca Cola').
    - If unsure, use "Others".
    - Unit in weight, volume, length or pieces as applicable.
    - Quantity should be a number in weight, volume, length or pieces as applicable; default to 1 if missing. Quantity might be also given in the item name.
    - Also make sure the total_amount matches the sum of item prices. This is important for data integrity. Price is total for quantity.
    """
    
    print("🤖 Prompt prepared for Gemini: " + prompt)

    # --- 4️⃣ Call Gemini once ---
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
            prompt_addition + prompt,
        ],
    )

    raw_text = response.text.strip()
    return raw_text

# --- LLM helper ---

def process_bill_image(image_path: str):
    """
    Single Gemini call:
    - Extracts structured bill info
    - Normalizes store and item names
    - Classifies each item into PurchaseCategories
    """
    prompt_addition = ""
    tries = 0
    max_tries = 3
    while True:
        raw_text = process_bill_image_llm(image_path, prompt_addition=prompt_addition)
        prompt_addition = ""  # reset for next iteration
        print(raw_text)
        if raw_text.startswith("```"):
            raw_text = raw_text.strip("`").replace("json", "", 1).strip()

        # --- 5️⃣ Parse response ---
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            print("⚠️ Invalid JSON returned by Gemini:", raw_text)
            return {
                "store": None,
                "store_name_raw": "",
                "store_name_normalized": "",
                "bill_date": None,
                "category": "",
                "total_amount": None,
                "items": [],
            }
            
        
        # --- 9️⃣ Total amount ---
        items = data.get("items", [])
        total_amount = float(data.get("total_amount", 0) or 0)
        if items:
            total = round(sum(float(i["price"]) for i in items if i["price"]), 2)
        
        if not total_amount:
            total_amount = total
        elif total_amount == total:
            print("✅ Total amount matches sum of items.")
        else:
            print(f"⚠️ Mismatch in total amount: extracted {total_amount} vs sum of items {total}")
            prompt_addition = f"""
            The total amount you provided ({total_amount}) does not match the sum of item prices ({total}).
            Please re-extract the data and ensure the total amount matches the sum of item prices.\n
            """

        # --- 6️⃣ Store setup ---
        store_name_raw = data.get("store_name_raw") or data.get("store_name") or ""
        store_name_normalized = data.get("store_name_normalized") or store_name_raw
        store_ref = get_or_create_store(store_name_raw, store_name_normalized)

        # --- 7️⃣ Bill date ---
        bill_date = None
        if date_str := data.get("bill_date"):
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                try:
                    bill_date = datetime.strptime(date_str, fmt)
                    break
                except ValueError:
                    continue

        # --- 8️⃣ Parse items ---
        items = []
        for item in data.get("items", []):
            raw_name = str(item.get("name_raw", ""))
            normalized_name = str(item.get("name_normalized", "")) or raw_name
            
            raw_brand = item.get("brand_raw", "")
            norm_brand = item.get("brand_normalized", "") or raw_brand
            
            detected_unit = str(item.get("unit", "")).strip()
            unit_ref = get_or_create_unit(detected_unit)

            item_ref = get_or_create_item_name(raw_name, normalized_name, unit_ref=unit_ref)
            brand_ref = get_or_create_brand(raw_brand, norm_brand)
            
            canonical_unit = item_ref.get_preferred_unit() if hasattr(item_ref, "get_preferred_unit") else None
            if canonical_unit:
                # ⚖️ Handle unit conversion if different
                if unit_ref and canonical_unit and unit_ref != canonical_unit:
                    try:
                        quantity, comment = convert_quantity(
                            value=float(item.get("quantity", 1)),
                            from_unit=unit_ref,
                            to_unit=canonical_unit
                        )
                        if comment:
                            prompt_addition += f"""
                                Item "{raw_name}" has unit "{unit_ref.name}" which differs from its canonical unit "{canonical_unit.name}". {comment}\n
                            """
                        unit_ref = canonical_unit  # use canonical for final storage
                    except Exception as e:
                        print(f"⚠️ Unit conversion failed {unit_ref.name} → {canonical_unit.name}: {e}")
                        quantity = float(item.get("quantity", 1))
                        prompt_addition += f"""
                            Item "{raw_name}" has unit "{unit_ref.name}" which differs from its canonical unit "{canonical_unit.name}". Please ensure correct unit conversion is applied.\n
                        """
                else:
                    quantity = float(item.get("quantity", 1))
                    unit_ref = canonical_unit
            else:
                # Canonical doesn’t have a preferred unit yet
                if unit_ref and not item_ref.preferred_unit:
                    item_ref.preferred_unit = unit_ref
                    item_ref.save(update_fields=["preferred_unit"])
                quantity = float(item.get("quantity", 1))

            items.append({
                "item_ref": item_ref,
                "unit_ref": unit_ref,
                "brand_ref": brand_ref,
                "name_raw": raw_name,
                "name_normalized": normalized_name,
                "brand_raw": raw_brand,
                "brand_normalized": norm_brand,
                "quantity": quantity,
                "unit": item.get("unit", ""),
                "price": float(item.get("price", 0)),
                "category": item.get("category", "Others"),
            })

        if prompt_addition:
            print("🔄 Retrying Gemini with prompt addition:", prompt_addition)
            tries += 1
            if tries >= max_tries:
                print("⚠️ Max retries reached. Proceeding with available data.")
                break
        else:
            print("✅ All data validated successfully.", prompt_addition)
            break  # all good, exit loop

    # --- 🔟 Bill category ---
    category_name = data.get("category") or "Others"
    category_ref = PurchaseCategory.objects.filter(name__iexact=category_name).first()

    return {
        "store": store_ref,
        "store_name_raw": store_name_raw,
        "store_name_normalized": store_name_normalized,
        "bill_date": bill_date,
        "purchase_category": category_ref,
        "total_amount": total_amount,
        "items": items,
    }


def get_or_create_unit(name: str):
    """Return existing Unit (case-insensitive), else create a new one."""
    if not name:
        return None
    unit = Unit.objects.filter(name__iexact=name).first()
    if not unit:
        unit = Unit.objects.create(name=name, category="pieces")  # default fallback
    return unit



def get_or_create_purchase_category(name: str, group_names: list[str] | None = None):
    """Return or create a PurchaseCategory and link it to one or more groups."""
    if not name:
        return None

    category, _ = PurchaseCategory.objects.get_or_create(name__iexact=name, defaults={"name": name})

    if group_names:
        for gname in group_names:
            group, _ = CategoryGroup.objects.get_or_create(name=gname)
            category.groups.add(group)

    return category


def normalize_with_llm(prompt: str):
    """Call Gemini to get structured normalization output."""
    response = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=prompt,
    )
    try:
        return json.loads(response.text)
    except Exception:
        return None


def normalize_store_name(store_name: str):
    """Use LLM to find the common English name for the store."""
    if not store_name:
        return None

    prompt = f"""
    You are a text normalization assistant.
    Input store name: "{store_name}"
    Output a JSON object with the most common English name for this store.

    Example:
    Input: "JUMBO supermarkten"
    Output: {{"common_name": "Jumbo"}}
    """
    data = normalize_with_llm(prompt)
    return data.get("common_name") if data else store_name


def normalize_item_name(item_name: str):
    """Use LLM to convert an item name to its common English equivalent."""
    if not item_name:
        return None

    prompt = f"""
    You are a text normalization assistant for grocery receipts.
    Input product name: "{item_name}"
    Output a JSON with a short, clean English name that best represents the item.

    Example:
    Input: "FAIRTRAD CACAOPODER"
    Output: {{"common_name": "Cocoa Powder"}}
    """
    data = normalize_with_llm(prompt)
    return data.get("common_name") if data else item_name


def classify_category(item_name: str):
    """Use LLM to decide which of our PurchaseCategory entries fits best."""
    all_categories = list(PurchaseCategory.objects.values_list("name", flat=True))
    categories_list = ", ".join(all_categories)

    prompt = f"""
    You are a purchase classifier.
    Choose the single most suitable category from this list for the item below.

    Categories: {categories_list}

    Item: "{item_name}"

    Respond strictly as JSON: {{"category": "chosen_category_name"}}
    """
    data = normalize_with_llm(prompt)
    if data and "category" in data:
        category_name = data["category"]
        return PurchaseCategory.objects.filter(name__iexact=category_name).first()
    return None


def convert_quantity(value: float, from_unit, to_unit) -> float:
    """
    Convert a quantity between two compatible units based on Unit model relationships.
    - Handles conversion via each unit's base_unit and conversion_to_base factor.
    - Returns the converted value if compatible, else raises ValidationError.
    """
    if not from_unit or not to_unit or not value:
        return value

    # Check for same object (no conversion needed)
    if from_unit.id == to_unit.id:
        return value

    # Check same category (e.g. both are 'weight')
    if from_unit.category != to_unit.category:
        print(f"⚠️ Conversion skipped: category mismatch ({from_unit.category} → {to_unit.category})")
        return value, f"⚠️ Conversion skipped: category mismatch ({from_unit.category} → {to_unit.category})"

    # Ensure both have valid conversion paths
    if not from_unit.conversion_to_base or not to_unit.conversion_to_base:
        print(f"⚠️ Conversion skipped: missing conversion factors for {from_unit.name} or {to_unit.name}")
        return value, ''

    # Step 1️⃣: Convert from source to base
    if from_unit.base_unit:
        base_value = value * from_unit.conversion_to_base
    else:
        base_value = value  # already base

    # Step 2️⃣: Convert from base to target
    if to_unit.base_unit:
        converted_value = base_value / to_unit.conversion_to_base
    else:
        converted_value = base_value  # already base

    return converted_value, ''
