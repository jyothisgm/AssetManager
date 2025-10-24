PROMPT_GET_INSTITUTION = """
You are classifying financial or commercial institutions.
Return a JSON list of objects, one per institution name, using this format:
[
    {{
        "input": "institution name",
        "name": "institution name cleaned",
        "short_name": "short form (e.g., HDFC Bank, SBI Bank, Amex)",
        "type": "one of ['bank','credit_card','broker','insurance','fintech','other']",
        "country": "Country or 'Unknown'",
        "website": "Official website URL if known, else null",
        "logo": "Official logo image URL (SVG/PNG) if available, else null like https://upload.wikimedia.org/wikipedia/commons/7/73/Revolut_logo.svg"
    }}
]
Ignore cash as an institution.
Make sure the logo URLs point directly to image files. Usually you are returning invalid logo URLs.
Institution names to classify: {institutions}
Try to pick if exist from: {existing_institutions}
"""

TRANSACTION_ATTACHMENT_TYPES = [
    "invoice",
    "bill",
    "purchase receipt",
    "email alert",
    "bank statement",
    "payment confirmation",
]

PROMPT_PARSE_TRANSACTION_ATTACHMENT = """
You are a document classification assistant.
Given the attached file, identify what kind of financial or transactional document it is.
Possible types: {transaction_attachment_type}, credit card statement, grocery list, personal note, or other.
Reply with only the most appropriate single type in lowercase (e.g., "invoice").
"""


# 1️⃣ Single transaction with items
PROMPT_PARSE_INVOICE = """
You are an expert receipt parser and normalizer.
From the uploaded bill or invoice, extract and normalize all details.
Return JSON in this exact structure:
{{
    "store_name_raw": "string",
    "store_name_normalized": "string maybe in [{preferred_shops_list}]",
    "date": "YYYY-MM-DDTHH:MM:SS",
    "amount": number,
    "category": "one of [{categories_list}]",
    "transaction_type": "string" in [debit, credit, transfer_credit, transfer_debit],
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
- date, if no year given, use current year.
- If the year cannot be identified, use the year {current_year}.
"""


# 2️⃣ List of transactions with items
PROMPT_PARSE_BILL = """
You are an expert bill parser and normalizer.
From the uploaded bill, extract and normalize all details.
Return JSON in this exact structure:
[
    {{
        "store_name_raw": "string",
        "store_name_normalized": "string maybe in [{preferred_shops_list}]",
        "date": "YYYY-MM-DDTHH:MM:SS",
        "amount": number,
        "category": "one of [{categories_list}]",
        "transaction_type": "string" in [debit, credit, transfer_credit, transfer_debit],
        "currency": "ISO code like 'USD', 'EUR', 'INR'",
        "items": [
            {
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
]
Notes:
- Extract tax, subtotal, or service items if available.
- Normalize vendor and product names using preferred lists.
- If the year cannot be identified, use the year {current_year}.
"""


# 3️⃣ Single transaction with items (retail receipt)
PROMPT_PARSE_PURCHASE_RECEIPT = """
You are an expert purchase receipt parser and normalizer.
From the uploaded purchase receipt, extract and normalize all details.
Return JSON in this exact structure:
{{
    "store_name_raw": "string",
    "store_name_normalized": "string maybe in [{preferred_shops_list}]",
    "date": "YYYY-MM-DDTHH:MM:SS",
    "amount": number,
    "category": "one of [{categories_list}]",
    "transaction_type": "string" in [debit, credit, transfer_credit, transfer_debit],
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
- Focus on extracting items purchased and the total amount.
- If subtotal and tax exist, ensure their sum matches total.
- If the year cannot be identified, use the year {current_year}.
"""


# 4️⃣ Single transaction without items (alerts)
PROMPT_PARSE_EMAIL_ALERT = """
You are an expert transaction alert parser and normalizer.
From the uploaded or extracted email alert, extract and normalize all details.
Return JSON in this exact structure:
{{
    "store_name_raw": "string or null",
    "store_name_normalized": "string maybe in [{preferred_shops_list}]",
    "date": "YYYY-MM-DDTHH:MM:SS",
    "amount": number,
    "category": "one of [{categories_list}]",
    "transaction_type": "string" in [debit, credit, transfer_credit, transfer_debit],
    "currency": "ISO code like 'USD', 'EUR', 'INR'"
}}
Notes:
- Extract sender, merchant, and transaction info if available.
- Handle both debit and credit alerts accurately.
- If the year cannot be identified, use the year {current_year}.
"""


# 5️⃣ List of transactions (bank statement, no items)
PROMPT_PARSE_BANK_STATEMENT = """
You are an expert bank statement parser and normalizer.
From the uploaded statement, extract and normalize all transactions.
Return JSON in this exact structure:
[
    {{
        "store_name_raw": "string",
        "store_name_normalized": "string maybe in [{preferred_shops_list}]",
        "date": "YYYY-MM-DDTHH:MM:SS",
        "amount": number,
        "category": "one of [{categories_list}]",
        "transaction_type": "string" in [debit, credit, transfer_credit, transfer_debit],
        "currency": "ISO code like 'USD', 'EUR', 'INR'"
    }}
]
Notes:
- Each line represents one transaction.
- Normalize payee or merchant names.
- Ensure total debits and credits balance correctly.
- If the year cannot be identified, use the year {current_year}.
"""


# 6️⃣ List of transactions without items (multi-transfer confirmations)
PROMPT_PARSE_PAYMENT_CONFIRMATION = """
You are an expert payment confirmation parser and normalizer.
From the uploaded confirmation (email, screenshot, or PDF), extract and normalize all details.
Return JSON in this exact structure:
[
    {{
        "store_name_raw": "string",
        "store_name_normalized": "string maybe in [{preferred_shops_list}]",
        "date": "YYYY-MM-DDTHH:MM:SS",
        "amount": number,
        "category": "one of [{categories_list}]",
        "transaction_type": "string" in [debit, credit, transfer_credit, transfer_debit],
        "currency": "ISO code like 'USD', 'EUR', 'INR'"
    }}
]
Notes:
- Identify payer, payee, and payment reference if available.
- Works for single or batched payments.
- If the year cannot be identified, use the year {current_year}.
"""


TRANSACTION_ATTACHMENT_PROMPT_MAP = {
    "invoice": PROMPT_PARSE_INVOICE,
    "bill": PROMPT_PARSE_BILL,
    "purchase receipt": PROMPT_PARSE_PURCHASE_RECEIPT,
    "email alert": PROMPT_PARSE_EMAIL_ALERT,
    "bank statement": PROMPT_PARSE_BANK_STATEMENT,
    "payment confirmation": PROMPT_PARSE_PAYMENT_CONFIRMATION,
}
