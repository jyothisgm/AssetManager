import json
import mimetypes
import pytz
from datetime import datetime
from ai.prompts import PROMPT_PARSE_TRANSACTION_ATTACHMENT, TRANSACTION_ATTACHMENT_PROMPT_MAP, TRANSACTION_ATTACHMENT_TYPES
from ai.utils import call_gemini_api_file, process_transaction_attachment_type
from catalog.models import Brand, Product, PurchaseCategory, Currency, Store
from catalog.utils import (
    get_or_create_brand,
    get_or_create_product_name,
    get_or_create_store,
)
from common.helpers import raise_with_line_info
from common.utils import convert_quantity, get_or_create_unit


# def process_transaction_file(image_path: str):
#     """
#     Uses Gemini LLM to extract and normalize data from a receipt image.
#     Returns structured transaction data ready for DB creation.
#     """
#     prompt_addition = ""
#     tries = 0
#     max_tries = 3
#     print("📄 Starting bill image processing for:", image_path)
    
    

#     while True:
#         raw_text = process_transaction_file_llm(image_path, prompt_addition=prompt_addition)
#         prompt_addition = ""  # reset for next loop

#         # --- Clean code block output ---
#         if raw_text.startswith("```"):
#             raw_text = raw_text.strip("`").replace("json", "", 1).strip()

#         try:
#             data = json.loads(raw_text)
#         except json.JSONDecodeError:
#             print("⚠️ Invalid JSON returned by Gemini:", raw_text)
#             return {
#                 "store": None,
#                 "date": None,
#                 "category": None,
#                 "currency": None,
#                 "amount": 0,
#                 "items": [],
#             }

#         # --- Currency ---
#         currency_code = (data.get("currency") or "EUR").upper().strip()
#         currency_ref = Currency.objects.filter(code=currency_code).first()

#         # --- Store ---
#         store_name_raw = data.get("store_name_raw") or data.get("store_name") or ""
#         store_name_normalized = data.get("store_name_normalized") or store_name_raw
#         store_ref = get_or_create_store(store_name_raw, store_name_normalized)

#         # --- Date ---
#         date_val = None
#         if date_str := data.get("date"):
#             for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
#                 try:
#                     amsterdam_tz = pytz.timezone("Europe/Amsterdam")
#                     naive_dt = datetime.strptime(date_str, fmt)
#                     date_val = amsterdam_tz.localize(naive_dt)
#                     break
#                 except ValueError:
#                     continue

#         # --- Category ---
#         category_name = data.get("category") or "Others"
#         category_ref = PurchaseCategory.objects.filter(name__iexact=category_name).first()
#         if not category_ref:
#             category_ref, _ = PurchaseCategory.objects.get_or_create(name="Others")
#         print("🏷️ Parsed category:", category_name, "->", category_ref)

#         # --- Total consistency ---
#         items = data.get("items", [])
#         total_from_items = round(sum(float(i.get("price", 0) or 0) for i in items), 2)
#         amount = float(data.get("amount", total_from_items))

#         if abs(amount - total_from_items) > 0.05:
#             print(f"⚠️ Total mismatch: {amount} vs item sum {total_from_items}")
#             prompt_addition = f"""
#                 The total amount you extracted ({amount}) does not match sum of item prices ({total_from_items}).
#                 Please correct and ensure they match.
#             """

#         # --- Parse items ---
#         parsed_items = []
#         for item in items:
#             raw_name = str(item.get("name_raw") or "").strip()
#             norm_name = str(item.get("name_normalized") or raw_name).strip()
#             raw_brand = str(item.get("brand_raw") or "").strip()
#             norm_brand = str(item.get("brand_normalized") or raw_brand).strip()

#             unit_str = str(item.get("unit") or "").strip()
#             unit_ref = get_or_create_unit(unit_str)

#             brand_ref = get_or_create_brand(raw_brand, norm_brand)

#             product_category_name = item.get("category") or "Others"
#             product_category = PurchaseCategory.objects.filter(name__iexact=product_category_name).first()
#             if not product_category:
#                 product_category, _ = PurchaseCategory.objects.get_or_create(name="Others")

#             item_ref = get_or_create_product_name(
#                 raw_name,
#                 norm_name,
#                 brand_ref,
#                 unit_ref=unit_ref,
#                 category=product_category
#             )

#             canonical_unit = getattr(item_ref, "preferred_unit", None)
#             try:
#                 if canonical_unit and unit_ref and unit_ref != canonical_unit:
#                     quantity, _ = convert_quantity(
#                         value=float(item.get("quantity", 1)),
#                         from_unit=unit_ref,
#                         to_unit=canonical_unit,
#                     )
#                     unit_ref = canonical_unit
#                 else:
#                     quantity = float(item.get("quantity", 1))
#             except Exception as e:
#                 print(f"⚠️ Unit conversion failed for {raw_name}: {e}")
#                 quantity = float(item.get("quantity", 1))

#             parsed_items.append({
#                 "item_ref": item_ref,
#                 "brand_ref": brand_ref,
#                 "unit_ref": unit_ref,
#                 "quantity": quantity,
#                 "price": float(item.get("price", 0)),
#                 "name_raw": raw_name,
#                 "name_normalized": norm_name,
#             })

#         if prompt_addition:
#             tries += 1
#             if tries >= max_tries:
#                 print("⚠️ Max retries reached. Proceeding with available data.")
#                 break
#             else:
#                 print("🔄 Retrying Gemini with correction prompt...")
#                 continue

#         print("✅ Parsed and validated transaction successfully.")
#         break

#     return {
#         "store": store_ref,
#         "date": date_val,
#         "category": category_ref,
#         "currency": currency_ref,
#         "amount": amount,
#         "items": parsed_items,
#     }



def process_transaction_file(transaction_file):
    """
    Uses Gemini LLM to:
    1. Identify the document type (invoice, bill, bank statement, etc.)
    2. Extract and normalize structured transaction data accordingly.
    Supports single/multiple transaction JSONs with or without items.
    Returns structured transaction data ready for DB creation.
    """

    print("📄 Starting transaction file processing for:", transaction_file)

    # --- Step 1: Detect document type ---
    type_prompt = PROMPT_PARSE_TRANSACTION_ATTACHMENT.format(
        transaction_attachment_type=", ".join(TRANSACTION_ATTACHMENT_TYPES)
    )
        # --- Read file bytes ---
    try:
        if hasattr(transaction_file, "read"):  # UploadedFile object
            transaction_file_bytes = transaction_file.read()
            file_name = getattr(transaction_file, "name", "uploaded_file")
        else:  # Local file path
            file_name = str(transaction_file)
            with open(transaction_file, "rb") as f:
                transaction_file_bytes = f.read()
    except Exception as e:
        print(f"⚠️ Error reading file: {e}")
        return "unknown"

    # --- Detect MIME type ---
    mime_type, _ = mimetypes.guess_type(file_name)
    mime_type = mime_type or "application/octet-stream"

    print(f"📄 Processing attachment: {file_name} ({mime_type})")

    doc_type = process_transaction_attachment_type(transaction_file_bytes, mime_type, prompt=type_prompt)
    if doc_type not in TRANSACTION_ATTACHMENT_PROMPT_MAP:
        print(f"⚠️ Unknown or unsupported attachment type detected: {doc_type}")
        doc_type = "invoice"  # fallback

    print(f"🧾 Detected document type: {doc_type}")

    try:
        # --- Step 2: Get correct parsing prompt ---
        parsing_prompt_template = TRANSACTION_ATTACHMENT_PROMPT_MAP[doc_type]
        parsing_prompt = parsing_prompt_template.format(
            preferred_shops_list=", ".join(Store.objects.values_list("name", flat=True)),
            preferred_items_list=", ".join(Product.objects.values_list("name", flat=True)),
            preferred_brands_list=", ".join(Brand.objects.values_list("name", flat=True)),
            categories_list=", ".join(PurchaseCategory.objects.values_list("name", flat=True)),
            current_year=datetime.now().year,  # ✅ pass it here
        )

        # --- Step 3: Parse content using Gemini ---
        prompt_addition = ""
        tries = 0
        max_tries = 3

        while True:
            raw_text = call_gemini_api_file(
                file_bytes=transaction_file_bytes,
                mime_type=mime_type,
                prompt=parsing_prompt+prompt_addition,
            )
            prompt_addition = ""  # reset

            # Clean fenced markdown output if needed
            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`").replace("json", "", 1).strip()

            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                print("⚠️ Invalid JSON returned by Gemini:", raw_text)
                return {
                    "document_type": doc_type,
                    "transactions": [],
                }

            # --- Normalize shape ---
            # Force into list of transactions
            if isinstance(data, dict):
                transactions = [data]
            elif isinstance(data, list):
                transactions = data
            else:
                print("⚠️ Unexpected JSON shape:", type(data))
                return {
                    "document_type": doc_type,
                    "transactions": [],
                }

            parsed_transactions = []

            for tx_data in transactions:
                # --- Currency ---
                currency_code = (tx_data.get("currency") or "EUR").upper().strip()
                currency_ref = Currency.objects.filter(code=currency_code).first()

                # --- Store ---
                store_name_raw = tx_data.get("store_name_raw") or tx_data.get("store_name") or ""
                store_name_normalized = tx_data.get("store_name_normalized") or store_name_raw
                store_ref = get_or_create_store(store_name_raw, store_name_normalized)

                # --- Date ---
                date_val = None
                if date_str := tx_data.get("date"):
                    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
                        try:
                            amsterdam_tz = pytz.timezone("Europe/Amsterdam")
                            naive_dt = datetime.strptime(date_str, fmt)
                            date_val = amsterdam_tz.localize(naive_dt)
                            break
                        except ValueError:
                            continue

                # --- Category ---
                category_name = tx_data.get("category") or "Others"
                category_ref = PurchaseCategory.objects.filter(name__iexact=category_name).first()
                if not category_ref:
                    category_ref, _ = PurchaseCategory.objects.get_or_create(name="Others")

                # --- Total amount ---
                items = tx_data.get("items", [])
                total_from_items = round(sum(float(i.get("price", 0) or 0) for i in items), 2)
                amount = float(tx_data.get("amount", total_from_items))

                if abs(amount - total_from_items) > 0.05 and items:
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
                    product_category = PurchaseCategory.objects.filter(
                        name__iexact=product_category_name
                    ).first()
                    if not product_category:
                        product_category, _ = PurchaseCategory.objects.get_or_create(name="Others")

                    item_ref = get_or_create_product_name(
                        raw_name,
                        norm_name,
                        brand_ref,
                        unit_ref=unit_ref,
                        category=product_category,
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

                parsed_transactions.append({
                    "store": store_ref,
                    "date": date_val,
                    "category": category_ref,
                    "currency": currency_ref,
                    "amount": amount,
                    "items": parsed_items,
                })

            if prompt_addition:
                tries += 1
                if tries >= max_tries:
                    print("⚠️ Max retries reached. Proceeding with available data.")
                    break
                else:
                    print("🔄 Retrying Gemini with correction prompt...")
                    continue

            print(f"✅ Parsed {len(parsed_transactions)} transaction(s) successfully.")
            break

        return {
            "document_type": doc_type,
            "transactions": parsed_transactions,
        }
    except Exception as e:
        raise_with_line_info("⚠️ LLM parsing failed", e)

