import json
import mimetypes
import sys
from google import genai
from google.genai import types
from django.conf import settings

from ai.prompts import PROMPT_GET_INSTITUTION
from main.middleware import get_current_user
from common.logging_config import logger


MODEL = "gemini-2.0-flash-lite"


# ---------------------------------------------------------------------
# 🔧 Helper: Initialize Gemini Client
# ---------------------------------------------------------------------
def get_gemini_client():
    """Return an authenticated Gemini client for the current user or fallback to default key."""
    user = get_current_user()
    api_key = getattr(user, "gemini_key", None) if user and user.is_authenticated else None

    if not api_key:
        api_key = settings.GEMINI_KEY
        logger.debug("[ai.utils] Using default GEMINI_KEY (no user-specific key found)")
    else:
        logger.debug(f"[ai.utils] Using user-specific Gemini key for {user.email}")

    try:
        return genai.Client(api_key=api_key)
    except Exception as e:
        logger.exception("[ai.utils] Failed to initialize Gemini client")
        raise e


# ---------------------------------------------------------------------
# 🧠 Text-only call
# ---------------------------------------------------------------------
def call_gemini_api(prompt: str) -> str:
    """Call Gemini API with a text-only prompt."""
    logger.debug("[ai.utils] call_gemini_api invoked")

    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=[types.Part(text=prompt)],
        )
        result = response.text.strip()
        logger.debug(f"[ai.utils] Gemini text response length={len(result)}")
        return result
    except Exception as e:
        logger.exception("[ai.utils] Gemini text API call failed")
        raise e


# ---------------------------------------------------------------------
# 📎 File + prompt (image, PDF, text, etc.)
# ---------------------------------------------------------------------
def call_gemini_api_file(file_bytes: bytes, mime_type: str, prompt: str) -> str:
    """Call Gemini API with any file type (image, PDF, text, etc.) and a prompt."""
    logger.debug(f"[ai.utils] call_gemini_api_file → MIME={mime_type}, size={len(file_bytes)} bytes")

    try:
        client = get_gemini_client()
        response = client.models.generate_content(
            model=MODEL,
            contents=[
                types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                types.Part.from_text(text=prompt),
            ],
        )
        result = response.text.strip()
        logger.debug(f"[ai.utils] Gemini file response length={len(result)}")
        return result
    except Exception as e:
        logger.exception("[ai.utils] Gemini multimodal API call failed")
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
        logger.warning(f"[ai.utils] Invalid JSON from Gemini: {e}")
        return {}
    except Exception as e:
        logger.exception("[ai.utils] Gemini institution classification failed")
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
        logger.exception("[ai.utils] Gemini error during attachment type detection")
        return "unknown"
