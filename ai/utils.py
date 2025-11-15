import json
import re
import numpy as np, time
from asgiref.sync import sync_to_async
from django.conf import settings
from django.utils import timezone
from typing import List, Dict, Any
from google import genai
from google.genai import types
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from common.logging_config import logger, get_current_user
from ai.models import save_ai_request_with_attachment
from ai.prompts import (
    PROMPT_GET_INSTITUTION,
    PROMPT_NORMALIZE_PRODUCT_NAME,
    PROMPT_PARSE_TRANSACTIONS,
    PROMPT_SUGGEST_ACCOUNT_DETAILS,
    PROMPT_DETECT_CURRENCY,
)
from user.models import User


MODEL = "gemini-2.5-flash-lite"

# ---------------------------------------------------------------------
# 🔧 Helper: Initialize Gemini Client
# ---------------------------------------------------------------------
def get_gemini_client():
    """Return an authenticated Gemini client for the current user or fallback to default key."""
    user = get_current_user()
    api_key = getattr(user, "gemini_key", None) if user and user.is_authenticated else None
    if not api_key:
        api_key = settings.GEMINI_KEY
        user = None
        logger.debug("[ai.utils] Using default GEMINI_KEY (no user-specific key found)")
    else:
        logger.debug(f"[ai.utils] Using user-specific Gemini key for {user.email}")
    try:
        return genai.Client(api_key=api_key), user
    except Exception as e:
        logger.warning("[ai.utils] Failed to initialize Gemini client", exc_info=True)
        raise e


@sync_to_async
def get_llm_for_user(user_id: int):
    logger.debug(f"[LLM] Loading Gemini model for user_id={user_id}")
    user = User.objects.get(pk=user_id)
    api_key = getattr(user, "gemini_key", None) if user else None
    if not api_key:
        api_key = settings.GEMINI_KEY
        user = None
        logger.debug("[ai.utils] Using default GEMINI_KEY (no user-specific key found)")
    else:
        logger.debug(f"[ai.utils] Using user-specific Gemini key for {user.email}")
        
    try:
        return ChatGoogleGenerativeAI(model=MODEL, google_api_key=api_key, temperature=0.2)
    except Exception as e:
        logger.warning("[ai.utils] Failed to initialize Gemini client", exc_info=True)
        raise e

# ---------------------------------------------------------------------
# 🧠 Text-only call
# ---------------------------------------------------------------------
def call_gemini_api(prompt: str) -> str:
    """Call Gemini API with a text-only prompt."""
    logger.debug("[ai.utils] call_gemini_api invoked")

    try:
        client, user = get_gemini_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=[types.Part(text=prompt)],
        )
        result = response.text.strip()
        # ✅ Log both request and response
        save_ai_request_with_attachment(
            model_name=MODEL,
            prompt=prompt,
            response=result,
            user=user,
            filename=f"gemini_input_{timezone.now().strftime('%Y%m%d_%H%M%S')}.bin",
        )
        logger.debug(f"[ai.utils] Gemini text response length={len(result)}")
        return result
    except Exception as e:
        logger.warning("[ai.utils] Gemini text API call failed", exc_info=True)
        raise e


# ---------------------------------------------------------------------
# 📎 File + prompt (image, PDF, text, etc.)
# ---------------------------------------------------------------------
def call_gemini_api_file(file_bytes: bytes, mime_type: str, prompt: str) -> str:
    """Call Gemini API with any file type (image, PDF, text, etc.) and a prompt."""
    logger.debug(f"[ai.utils] call_gemini_api_file → MIME={mime_type}, size={len(file_bytes)} bytes")

    try:
        client, user = get_gemini_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=[
                types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                types.Part.from_text(text=prompt),
            ],
        )
        result = response.text.strip()
        # ✅ Log both request and response
        save_ai_request_with_attachment(
            model_name=MODEL,
            prompt=prompt,
            response=result,
            file_bytes=file_bytes,
            mime_type=mime_type,
            user=user,
            filename=f"gemini_input_{timezone.now().strftime('%Y%m%d_%H%M%S')}.bin",
        )
        logger.debug(f"[ai.utils] Gemini file response length={len(result)}")
        return result
    except Exception as e:
        logger.warning("[ai.utils] Gemini multi-modal API call failed", exc_info=True)
        raise e


# ---------------------------------------------------------------------
# 🏦 Institution classification
# ---------------------------------------------------------------------
def get_institution_data(institutions, existing_institutions):
    """
    Use Gemini to classify institution names and enrich them
    with metadata (short name, type, country, website, logo).
    """
    logger.info(f"[ai.utils] Classifying {len(institutions)} institution(s) via Gemini")

    prompt = PROMPT_GET_INSTITUTION.format(
        institutions=", ".join(institutions or []),
        existing_institutions=", ".join(existing_institutions or []),
    )

    try:
        raw = call_gemini_api(prompt)

        if raw.startswith("```"):
            raw = raw.strip("`").replace("json", "").strip()

        ai_data = json.loads(raw)
        ai_lookup = {
            entry["input"].strip(): entry
            for entry in ai_data
            if isinstance(entry, dict) and "input" in entry
        }

        logger.info(f"[ai.utils] Gemini returned {len(ai_lookup)} classified institutions")
        return ai_lookup

    except json.JSONDecodeError as e:
        logger.warning(f"[ai.utils] Invalid JSON from Gemini: {e}", exc_info=True)
        return {}
    except Exception as e:
        logger.warning("[ai.utils] Gemini institution classification failed", exc_info=True)
        return {}


# ---------------------------------------------------------------------
# 📎 Transaction Attachment Type Detection
# ---------------------------------------------------------------------
def process_transaction_attachment_type(file_bytes, mime_type, prompt) -> str:
    """
    Identify the type of an uploaded transaction attachment
    (e.g., invoice, bill, bank alert, receipt, statement, email, etc.)
    using Gemini multimodal understanding.
    """
    logger.debug(f"[ai.utils] Detecting attachment type (MIME={mime_type})")

    try:
        raw_text = call_gemini_api_file(
            file_bytes=file_bytes,
            mime_type=mime_type,
            prompt=prompt,
        )

        if not raw_text:
            logger.warning("[ai.utils] Empty response from Gemini while detecting attachment type")
            return "unknown"

        result = (
            raw_text.strip().lower().replace('"', "").replace("'", "")
        )
        logger.info(f"[ai.utils] Detected attachment type: {result}")
        return result

    except Exception as e:
        logger.warning("[ai.utils] Gemini error during attachment type detection", exc_info=True)
        raise e


def fetch_total_emails(service) -> int:
    """Count total number of unique Gmail messages."""
    total_unique = 0
    next_page_token = None
    while True:
        res = service.users().messages().list(userId="me", maxResults=1000, pageToken=next_page_token).execute()
        total_unique += len(res.get("messages", []))
        next_page_token = res.get("nextPageToken")
        if not next_page_token:
            break
    return total_unique


def get_embedding(text: str, model="models/text-embedding-004"):
    """Return a normalized embedding vector using Gemini."""
    if not text:
        return []

    text = text.strip().replace("\n", " ")[:8000]
    client, user = get_gemini_client()

    for attempt in range(3):
        try:
            res = client.models.embed_content(model=model, contents=text)
            emb = getattr(res.embeddings[0], "values", None)
            if not emb:
                raise ValueError("Empty embedding")

            arr = np.array(emb, dtype=float)
            norm = np.linalg.norm(arr)
            return (arr / norm).tolist() if norm > 0 else arr.tolist()
        except Exception as e:
            logger.warning(
                f"[get_embedding] Gemini embedding failed (attempt {attempt+1}) for user={getattr(user, 'email', None)}: {e}"
            )
            time.sleep(1)

    logger.error("[get_embedding] All retry attempts failed.")
    return []


def analyze_email_batch_with_llm(llm, emails) -> List[Dict[str, str]]:
    """Send batch of emails to LLM and parse response."""
    summaries = "\n\n".join(
        f"--- EMAIL {idx+1} ---\n"
        f"Email ID: {e['id']}\nFrom: {e['from']}\nSubject: {e['subject']}\nSnippet:\n{e['snippet']}"
        for idx, e in enumerate(emails)
    )

    prompt = (
        "From the following emails, identify which ones are *likely* to describe a financial transaction.\n\n"
        "Return ONLY JSON array: [{ email_id, subject, from, reason }].\n\n"
        f"{summaries}\n\nReturn ONLY JSON."
    )

    res = llm.invoke([HumanMessage(content=prompt)])
    return safe_parse_json(res.content)


def safe_parse_json(text: str) -> List[Dict[str, Any]]:
    """Extract JSON list from arbitrary text safely."""
    if not text:
        return []
    match = re.search(r"\[.*\]", text.strip(), re.S)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        logger.warning(f"[safe_parse_json] JSON decode error: {text[:200]}...")
        return []


def safe_parse_json_object(text: str) -> Dict[str, Any]:
    """Extract a JSON object from arbitrary text safely."""
    if not text:
        return {}
    match = re.search(r"\{.*\}", text.strip(), re.S)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning(f"[safe_parse_json_object] JSON decode error: {text[:200]}...")
        return {}


def parse_transactions_with_llm(
        llm,
        email: Dict[str, Any],
        existing_accounts=None,
        existing_stores=None,
        existing_categories=None,
        existing_products=None,
        existing_institutions=None,
        existing_account_types=None,
        existing_currencies=None,
    ) -> List[Dict[str, Any]]:
    """
    Use LLM to extract structured transactions from a single email,
    grounded to existing DB values for consistency.
    """
    VALID_TRANSACTION_TYPES = ["debit", "credit", "transfer_debit", "transfer_credit"]

    prompt = PROMPT_PARSE_TRANSACTIONS.format(
        from_addr=email.get("from", ""),
        subject=email.get("subject", ""),
        body=email.get("body", "")[:4000],
        transaction_types=", ".join(VALID_TRANSACTION_TYPES),
        existing_accounts=", ".join(existing_accounts or []),
        existing_stores=", ".join(existing_stores or []),
        existing_categories=", ".join(existing_categories or []),
        existing_products=", ".join(existing_products or []),
        existing_institutions=", ".join(existing_institutions or []),
        existing_account_types=", ".join(existing_account_types or []),
        existing_currencies=", ".join(existing_currencies or []),
    )

    try:
        res = llm.invoke([HumanMessage(content=prompt)])
        txs = safe_parse_json(res.content)
        return txs or []
    except Exception as e:
        logger.warning(f"[ai.utils] LLM failed to parse email {email.get('id')}: {e}", exc_info=True)
        return []


def suggest_account_details_with_llm(
    llm,
    tx: Dict[str, Any],
    account_types: List[str] | None = None,
    currencies: List[str] | None = None,
    institutions: List[str] | None = None,
    email_timestamp: str | None = None,
) -> Dict[str, Any]:
    """
    Ask the LLM to suggest account metadata for a transaction.
    Returns a dict with optional account_type, currency, institution, needs_review.
    """
    if not llm:
        return {}

    try:
        payload = {
            "transaction": tx,
            "email_timestamp": email_timestamp,
        }
        prompt = PROMPT_SUGGEST_ACCOUNT_DETAILS.format(
            account_types=", ".join(account_types or []),
            currencies=", ".join(currencies or []),
            institutions=", ".join(institutions or []),
            transaction_json=json.dumps(payload, default=str, ensure_ascii=False, indent=2),
        )
        res = llm.invoke([HumanMessage(content=prompt)])
        suggestion = safe_parse_json_object(res.content)
        if not suggestion:
            logger.debug("[AccountSuggestion] Empty or invalid response from LLM, returning {}")
        return suggestion or {}
    except Exception as e:
        logger.warning(f"[AccountSuggestion] LLM failed to suggest account details: {e}", exc_info=True)
        return {}


def normalize_product_name_with_llm(llm, name: str) -> str:
    """Normalize and clean product names using LLM."""
    if not name or not llm:
        return name.strip() if name else ""
    try:
        prompt = PROMPT_NORMALIZE_PRODUCT_NAME.format(product_name=name)
        res = llm.invoke([HumanMessage(content=prompt)])
        clean = (res.content or name).strip()
        return clean.split("\n")[0][:100]  # Keep short and safe
    except Exception as e:
        logger.warning(f"[ProductName] LLM normalization failed for '{name}': {e}")
        return name.strip()


def detect_currency_with_llm(
    llm,
    email: Dict[str, Any],
    existing_currencies: List[str] | None = None,
) -> Dict[str, Any]:
    """
    Use LLM to detect the currency from email content.
    Returns a dict with 'currency' (ISO code) and 'confidence' (high|medium|low).
    """
    if not llm:
        return {"currency": None, "confidence": "low"}

    try:
        prompt = PROMPT_DETECT_CURRENCY.format(
            from_addr=email.get("from", ""),
            subject=email.get("subject", ""),
            body=email.get("body", "")[:4000],
            existing_currencies=", ".join(existing_currencies or []),
        )
        res = llm.invoke([HumanMessage(content=prompt)])
        result = safe_parse_json_object(res.content)
        if not result:
            logger.debug("[CurrencyDetection] Empty or invalid response from LLM")
            return {"currency": None, "confidence": "low"}
        
        currency_code = result.get("currency")
        confidence = result.get("confidence", "low")
        
        logger.info(
            "[CurrencyDetection] Detected currency=%s (confidence=%s) for email=%s",
            currency_code,
            confidence,
            email.get("id", "unknown"),
        )
        return {"currency": currency_code, "confidence": confidence}
    except Exception as e:
        logger.warning(f"[CurrencyDetection] LLM failed to detect currency: {e}", exc_info=True)
        return {"currency": None, "confidence": "low"}
