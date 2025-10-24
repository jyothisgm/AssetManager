import json
import mimetypes
import sys

from google import genai
from google.genai import types
from django.conf import settings

from ai.prompts import PROMPT_GET_INSTITUTION, PROMPT_PARSE_INVOICE
from catalog.models import Brand, Product, PurchaseCategory, Store
from common.helpers import raise_with_line_info
from main.middleware import get_current_user


MODEL = "gemini-2.0-flash-lite"


# ---------------------------------------------------------------------
# 🔧 Helper: Initialize Gemini Client
# ---------------------------------------------------------------------
def get_gemini_client():
    """Return an authenticated Gemini client for the current user or default key."""
    user = get_current_user()
    api_key = getattr(user, "gemini_key", None) if user and user.is_authenticated else None
    if not api_key:
        api_key = settings.GEMINI_KEY
    return genai.Client(api_key=api_key)


# ---------------------------------------------------------------------
# 🧠 Text-only call
# ---------------------------------------------------------------------
def call_gemini_api(prompt: str) -> str:
    """Call Gemini API with a text-only prompt."""
    client = get_gemini_client()
    response = client.models.generate_content(
        model=MODEL,
        contents=[types.Part(text=prompt),],
    )
    return response.text.strip()


# ---------------------------------------------------------------------
# 📎 File + prompt (image, PDF, text, etc.)
# ---------------------------------------------------------------------
def call_gemini_api_file(file_bytes: bytes, mime_type: str, prompt: str) -> str:
    """Call Gemini API with any file type (image, PDF, text, JSON, etc.) and a prompt."""
    client = get_gemini_client()
    response = client.models.generate_content(
        model=MODEL,
        contents=[
            types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
            types.Part.from_text(text=prompt),
        ],
    )
    return response.text.strip()


# ---------------------------------------------------------------------
# 🏦 Institution classification
# ---------------------------------------------------------------------
def get_institution_data(institutions, existing_institutions):
    """
    Use Gemini to classify a list of institution names and enrich them
    with metadata (short name, type, country, website, logo).
    """

    # --- Build the prompt safely ---
    prompt = PROMPT_GET_INSTITUTION.format(
        institutions=", ".join(institutions or []),
        existing_institutions=", ".join(existing_institutions or []),
    )

    # --- Call Gemini using the existing helper ---
    try:
        raw = call_gemini_api(prompt)

        # Handle Markdown code-fenced JSON output
        if raw.startswith("```"):
            raw = raw.strip("`").replace("json", "").strip()

        ai_data = json.loads(raw)
        ai_lookup = {
            entry["input"].strip(): entry
            for entry in ai_data
            if isinstance(entry, dict) and "input" in entry
        }

        print(f"✅ Gemini returned {len(ai_lookup)} institution entries")

    except Exception as e:
        print(f"❌ Gemini institution classification failed: {e}")
        ai_lookup = {}

    return ai_lookup


# ---------------------------------------------------------------------
# 📎 Transaction Attachment Type Detection
# ---------------------------------------------------------------------

def process_transaction_attachment_type(file_bytes, mime_type, prompt) -> str:
    """
    Identify the type of an uploaded transaction attachment
    (e.g., invoice, bill, bank alert, receipt, statement, email, etc.)
    using Gemini multimodal understanding.
    """

    # --- Send to Gemini ---
    try:
        raw_text = call_gemini_api_file(
            file_bytes=file_bytes,
            mime_type=mime_type,
            prompt=prompt,
        )

        if not raw_text:
            print("⚠️ Empty response from Gemini.")
            return "unknown"

        # Normalize Gemini output
        result = raw_text.strip().lower()
        result = result.replace('"', "").replace("'", "")
        print(f"🧾 Detected attachment type: {result}")

        return result

    except Exception as e:
        print(f"⚠️ Gemini API error while processing attachment: {e}")
        return "unknown"
