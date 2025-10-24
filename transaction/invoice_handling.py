import json
import mimetypes
import pytz
from datetime import datetime

from ai.prompts import (
    PROMPT_PARSE_TRANSACTION_ATTACHMENT,
    TRANSACTION_ATTACHMENT_PROMPT_MAP,
    TRANSACTION_ATTACHMENT_TYPES,
)
from ai.utils import call_gemini_api_file, process_transaction_attachment_type
from catalog.models import Brand, Product, PurchaseCategory, Currency, Store
from catalog.utils import (
    get_or_create_brand,
    get_or_create_product_name,
    get_or_create_store,
)
from common.utils import convert_quantity, get_or_create_unit
from common.logging_config import logger


def process_transaction_file(transaction_file):
    """
    Uses Gemini LLM to:
    1. Identify the document type (invoice, bill, bank statement, etc.)
    2. Extract and normalize structured transaction data accordingly.
    Returns structured transaction data ready for DB creation.
    """
    func_name = "process_transaction_file"
    try:
        logger.info(f"[{func_name}] Starting file processing for: {transaction_file}")

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
            logger.exception(f"[{func_name}] Error reading file {transaction_file}")
            raise e

        mime_type, _ = mimetypes.guess_type(file_name)
        mime_type = mime_type or "application/octet-stream"
        logger.debug(f"[{func_name}] MIME type detected: {mime_type}")

        # --- Document type detection via LLM ---
        doc_type = process_transaction_attachment_type(transaction_file_bytes, mime_type, prompt=type_prompt)
        if doc_type not in TRANSACTION_ATTACHMENT_PROMPT_MAP:
            logger.warning(f"[{func_name}] Unsupported attachment type '{doc_type}', using fallback 'invoice'")
            doc_type = "invoice"
        logger.info(f"[{func_name}] Detected document type: {doc_type}")

        # --- Prepare parsing prompt ---
        parsing_prompt_template = TRANSACTION_ATTACHMENT_PROMPT_MAP[doc_type]
        parsing_prompt = parsing_prompt_template.format(
            preferred_shops_list=", ".join(Store.objects.values_list("name", flat=True)),
            preferred_items_list=", ".join(Product.objects.values_list("name", flat=True)),
            preferred_brands_list=", ".join(Brand.objects.values_list("name", flat=True)),
            categories_list=", ".join(PurchaseCategory.objects.values_list("name", flat=True)),
            current_year=datetime.now().year,
        )

        prompt_addition = ""
        tries = 0
        max_tries = 3

        while True:
            try:
                raw_text = call_gemini_api_file(
                    file_bytes=transaction_file_bytes,
                    mime_type=mime_type,
                    prompt=parsing_prompt + prompt_addition,
                )
            except Exception as e:
                logger.exception(f"[{func_name}] Gemini API call failed")
                raise e

            if raw_text.startswith("```"):
                raw_text = raw_text.strip("`").replace("json", "", 1).strip()

            try:
                data = json.loads(raw_text)
            except json.JSONDecodeError:
                logger.warning(f"[{func_name}] Invalid JSON returned by Gemini.")
                return {"document_type": doc_type, "transactions": []}

            # --- Ensure data is a list ---
            transactions = [data] if isinstance(data, dict) else data if isinstance(data, list) else []
            if not transactions:
                logger.warning(f"[{func_name}] Unexpected data structure from Gemini response.")
                return {"document_type": doc_type, "transactions": []}

            parsed_transactions = []
            logger.debug(f"[{func_name}] Parsed {len(transactions)} transaction(s) from raw JSON")

            for tx_data in transactions:
                try:
                    currency_code = (tx_data.get("currency") or "EUR").upper().strip()
                    currency_ref = Currency.objects.filter(code=currency_code).first()

                    store_name_raw = tx_data.get("store_name_raw") or tx_data.get("store_name") or ""
                    store_name_normalized = tx_data.get("store_name_normalized") or store_name_raw
                    store_ref = get_or_create_store(store_name_raw, store_name_normalized)

                    # Parse date safely
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

                    # Category handling
                    category_name = tx_data.get("category") or "Others"
                    category_ref = PurchaseCategory.objects.filter(name__iexact=category_name).first()
                    if not category_ref:
                        category_ref, _ = PurchaseCategory.objects.get_or_create(name="Others")

                    # Compute total
                    items = tx_data.get("items", [])
                    total_from_items = round(sum(float(i.get("price", 0) or 0) for i in items), 2)
                    amount = float(tx_data.get("amount", total_from_items))

                    if abs(amount - total_from_items) > 0.05 and items:
                        logger.warning(
                            f"[{func_name}] Total mismatch for store={store_ref}: {amount} vs items={total_from_items}"
                        )
                        prompt_addition = (
                            f"The total ({amount}) does not match sum of items ({total_from_items}). Please correct."
                        )

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
                        product_category = (
                            PurchaseCategory.objects.filter(name__iexact=product_category_name).first()
                            or PurchaseCategory.objects.get_or_create(name="Others")[0]
                        )

                        item_ref = get_or_create_product_name(
                            raw_name, norm_name, brand_ref, unit_ref=unit_ref, category=product_category
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
                            logger.warning(f"[{func_name}] Unit conversion failed for {raw_name}: {e}")
                            quantity = float(item.get("quantity", 1))

                        parsed_items.append(
                            {
                                "item_ref": item_ref,
                                "brand_ref": brand_ref,
                                "unit_ref": unit_ref,
                                "quantity": quantity,
                                "price": float(item.get("price", 0)),
                                "name_raw": raw_name,
                                "name_normalized": norm_name,
                            }
                        )

                    parsed_transactions.append(
                        {
                            "store": store_ref,
                            "date": date_val,
                            "category": category_ref,
                            "currency": currency_ref,
                            "amount": amount,
                            "items": parsed_items,
                        }
                    )

                except Exception as e:
                    logger.exception(f"[{func_name}] Error parsing transaction data: {tx_data}")
                    raise e

            if prompt_addition:
                tries += 1
                if tries >= max_tries:
                    logger.warning(f"[{func_name}] Max retries reached. Using partial data.")
                    break
                else:
                    logger.debug(f"[{func_name}] Retrying Gemini parsing (attempt {tries + 1})")
                    continue

            logger.info(f"[{func_name}] Successfully parsed {len(parsed_transactions)} transaction(s).")
            break

        return {"document_type": doc_type, "transactions": parsed_transactions}

    except Exception as e:
        logger.exception(f"[{func_name}] Critical failure in transaction parsing.")
        raise e
