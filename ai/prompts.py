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
Institution names to classify: [{institutions}]
Try to pick if exist from: [{existing_institutions}]
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
- date, if no year given, use current year, if there is doubt in the format choose the date closest to the date of request.
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
]
Notes:
- Normalize store & product names to their most common English equivalents.
- Use the `preferred_items_list` for reference of normalized items + units.
- Each item should have price and quantity; quantity defaults to 1.
- Ensure total matches sum of item prices; if not, fix it.
- date, if no year given, use current year, if there is doubt in the format choose the date closest to the date of request.
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
- Normalize store & product names to their most common English equivalents.
- Use the `preferred_items_list` for reference of normalized items + units.
- Each item should have price and quantity; quantity defaults to 1.
- Ensure total matches sum of item prices; if not, fix it.
- date, if no year given, use current year, if there is doubt in the format choose the date closest to the date of request.
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
- Normalize store & product names to their most common English equivalents.
- Use the `preferred_items_list` for reference of normalized items + units.
- Each item should have price and quantity; quantity defaults to 1.
- Ensure total matches sum of item prices; if not, fix it.
- date, if no year given, use current year, if there is doubt in the format choose the date closest to the date of request.
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
- Normalize store & product names to their most common English equivalents.
- Use the `preferred_items_list` for reference of normalized items + units.
- Each item should have price and quantity; quantity defaults to 1.
- Ensure total matches sum of item prices; if not, fix it.
- date, if no year given, use current year, if there is doubt in the format choose the date closest to the date of request.
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
- Normalize store & product names to their most common English equivalents.
- Use the `preferred_items_list` for reference of normalized items + units.
- Each item should have price and quantity; quantity defaults to 1.
- Ensure total matches sum of item prices; if not, fix it.
- date, if no year given, use current year, if there is doubt in the format choose the date closest to the date of request.
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

SYSTEM_INSTRUCTIONS = (
    "You are an AI finance assistant that helps the user manage transactions.\n"
    "- You can work from natural language (voice transcriptions) or emails.\n"
    "- You must extract transactions as structured JSON with fields like:\n"
    "  date, amount, currency, description, source (voice/email), category.\n"
    "- Be conservative: if something is ambiguous, mark it as 'needs_review'."
)

# ---------------------------------------------------------------------
# 💳 Transaction Extraction Prompt
# ---------------------------------------------------------------------
PROMPT_PARSE_TRANSACTIONS = """
You are a financial transactions parser.

From the email below, extract *all* transaction details and return a JSON array with:
[
    date,
    amount,
    currency,
    transaction_type,
    description,
    store,
    category,
    account,              # The account name (from existing_accounts if relevant)
    account_type,         # One of: {account_types}
    institution,          # Pick from existing_institutions if relevant
    items[],
    needs_review
]

You can use these known options for grounding:
- Accounts: {existing_accounts}
- Account types: {account_types}
- Institutions: {existing_institutions}
- Currencies: {existing_currencies}
- Transaction types: {transaction_types}

--- EMAIL START ---
From: {from_addr}
Subject: {subject}
Body:
{body}
--- EMAIL END ---
"""

PROMPT_PARSE_TRANSACTIONS = """
You are a financial transaction extraction expert.

Your job is to determine whether the email below represents a **real financial transaction**
where actual money was **debited, credited, transferred, invested, or refunded**.
If no actual movement of funds occurred, return an empty array `[]`.

Ignore all emails that:
- Mention only **authentication attempts**, **card verification**, **login alerts**, or **OTP confirmations**
    (e.g., “Verified by Visa,” “successful authentication,” “your card was used for verification”).
- Contain no clear evidence of a debit, credit, or transfer amount.
- Are **promotional, marketing, or offer-based** (e.g., “Get 50% off,” “You’ve earned cashback,” “Your order has shipped”).
- Are **status updates**, **password resets**, **account alerts**, or **security notifications**.
- Are **newsletters, tips, or product updates**.
- Do not mention a payment, transfer, refund, or any movement of money.

If the email **does describe** a transaction (e.g., payment successful, refund processed, transfer completed),
extract all transaction details and return them as a JSON array of objects with fields:
[
    date,
    amount,
    currency,
    transaction_type,
    description,
    account,
    card_number,        # Last 4-6 digits of debit/credit card if mentioned (e.g., "ending 1234", "xxxx1234")
    store,
    category,
    items[],
    needs_review
]

IMPORTANT for debit/credit card transactions:
- Extract card_number (last 4-6 digits) from patterns like:
  * "debit card ending 1234"
  * "card xxxx1234"
  * "Card: 1234567890" → extract "7890" or "123456"
  * "ending in 1234"
- If card_number is found, include it in the transaction object.
- The account name should be the bank/institution name + "Card" + last digits (e.g., "HDFC Bank Card 1234")

Guidelines:
- Only include transactions where funds were actually debited, credited, invested, withdrawn, or transferred.
- Exclude “offers,” “subscriptions available,” “pre-orders,” “coupons,” “rewards,” or “pending approval” without confirmed monetary movement.
- If uncertain, mark the transaction with `"needs_review": true`.
- Use ONLY these transaction types: {transaction_types}.
- If the email contains keywords like “paid,” “debited,” “credited,” “refunded,” “transaction ID,” or “payment successful,” it likely represents a valid transaction.

When assigning names:
- Prefer matches from existing lists.
- Only create new account/store/category names if no close match exists.

Existing Accounts: {existing_accounts}
Existing Stores: {existing_stores}
Existing Categories: {existing_categories}
Existing Products: {existing_products}

Examples of emails to IGNORE:
1. “Your card was used for verification on eBay India Pvt. Ltd (Verified by Visa).”
2. “Login alert: Someone signed in to your HDFC NetBanking account.”
3. “Your order has been shipped.”
4. “Special offer: Get 20% cashback on your next order.”
5. “Your investment portfolio report is ready.”

Examples of VALID transaction emails:
1. “₹419 debited from your account for Swiggy order #12345.”
2. “INR 999 credited to your account as Amazon Pay refund.”
3. “You transferred $500 to John Doe via PayPal.”
4. “Your SIP of ₹2,000 in Axis Bluechip Fund has been executed.”

--- EMAIL START ---
From: {from_addr}
Subject: {subject}
Body:
{body}
--- EMAIL END ---
"""



PROMPT_SUGGEST_ACCOUNT_DETAILS = """
You are assisting a personal finance assistant in classifying accounts and normalizing account names.

Given the transaction JSON below, you need to:
1. Normalize the account name to a clean, standard format
2. Extract the account number (if available)
3. Suggest appropriate account metadata

IMPORTANT: Account Name Normalization Rules:
- Remove transaction-specific details: "online bank transfer", "UPI payment", "NEFT", "IMPS", "card payment", etc.
- Remove redundant words: "account", "bank account", "savings account" (unless needed for clarity)
- Keep only: Institution name + Account type (if needed) + Account number (last 4 digits if available)
- Format: "[Institution] [Account Type] [Last 4 digits]" or "[Institution] Account"
- Examples:
  * "State Bank of Travancore online bank transfer" → "State Bank of Travancore Account"
  * "HDFC Bank Savings Account 1234" → "HDFC Bank Savings 1234"
  * "ICICI Credit Card ending 5678" → "ICICI Credit Card 5678"
  * "Axis Bank Account 9012" → "Axis Bank Account 9012"

Always respond with a single JSON object containing:
{{
    "account_name": "normalized account name (clean, without transaction details)",
    "account_number": "last 4-6 digits of account/card number if found, or null",
    "account_type": "one of [{account_types}] or null",
    "currency": "three-letter ISO code from [{currencies}] or null",
    "institution": "institution short name preferably from [{institutions}] or null",
    "needs_review": true|false
}}

- Prefer existing names (case-insensitive matches are fine).
- If you are unsure about any field, return null for it and set needs_review=true.
- If the suggested value is not in the provided list, return null and needs_review=true.
- Extract account numbers from the transaction description (look for patterns like "ending 1234", "xxxx1234", "Account: 1234567890", etc.)

Transaction context:
{transaction_json}
"""


PROMPT_NORMALIZE_PRODUCT_NAME = """
You are a product name cleaner.

Input product name: "{product_name}"

Output a short, clean, and standardized version of this name, fixing spelling errors
and removing redundant words like "offer", "discount", or "pack of". 
Do not describe or explain—return only the corrected product name text.
"""


PROMPT_DETECT_CURRENCY = """
You are a currency detection assistant for financial transactions.

Given the email content below, identify the currency used in the transaction.
Return ONLY a JSON object with this structure:
{{
    "currency": "three-letter ISO code (e.g., 'USD', 'INR', 'EUR', 'GBP') or null if unclear",
    "confidence": "high|medium|low"
}}

Look for:
- Currency symbols (₹, $, €, £, ¥, etc.)
- Currency codes mentioned in the text
- Amount formats that suggest currency (e.g., "Rs. 500", "$50.00", "€100")
- Context clues from the sender or transaction description

If you cannot determine the currency with confidence, return {{"currency": null, "confidence": "low"}}.

Available currencies: {existing_currencies}

--- EMAIL START ---
From: {from_addr}
Subject: {subject}
Body:
{body}
--- EMAIL END ---
"""
