import json
import mimetypes
import sys
from google import genai
from google.genai import types
from django.conf import settings
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils import timezone

from ai.models import save_ai_request_with_attachment
from ai.prompts import PROMPT_GET_INSTITUTION
from common.logging_config import logger, get_current_user
from common.models import AIModelConfig


DEFAULT_MODEL_ID = "gemini-2.5-flash-lite"
TEXT_MODEL_TYPE = "text"
MULTIMODAL_MODEL_TYPE = "multimodal"
PRIORITY_BUMP = 5
PRIORITY_RECOVERY = 1


# ---------------------------------------------------------------------
# 🔧 Helper: Initialize Gemini Client
# ---------------------------------------------------------------------
def get_gemini_client(override_api_key: str | None = None):
    """
    Return an authenticated Gemini client for the current user or fallback to default key.
    If override_api_key is provided it takes precedence so we can bind to a specific provider credential.
    """
    user = get_current_user()
    user_key = getattr(user, "gemini_key", None) if user and user.is_authenticated else None
    api_key = user_key or override_api_key or settings.GEMINI_KEY

    if user_key:
        logger.debug(f"[ai.utils] Using user-specific Gemini key for {user.email}")
    elif override_api_key:
        logger.debug("[ai.utils] Using override Gemini API key from AIModelConfig")
    else:
        logger.debug("[ai.utils] Using default GEMINI_KEY (no override/user-specific key found)")
        user = None

    try:
        return genai.Client(api_key=api_key), user
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
        response, user, model_used = _execute_with_failover(
            model_type=TEXT_MODEL_TYPE,
            executor=lambda client, model_id: client.models.generate_content(
                model=model_id,
                contents=[types.Part(text=prompt)],
            ),
        )
        result = response.text.strip()
        # ✅ Log both request and response
        save_ai_request_with_attachment(
            model_name=model_used,
            prompt=prompt,
            response=result,
            user=user,
            filename=f"gemini_input_{timezone.now().strftime('%Y%m%d_%H%M%S')}.bin",
        )
        logger.debug(
            f"[ai.utils] Gemini text response length={len(result)} using model={model_used}"
        )
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
        response, user, model_used = _execute_with_failover(
            model_type=MULTIMODAL_MODEL_TYPE,
            executor=lambda client, model_id: client.models.generate_content(
                model=model_id,
                contents=[
                    types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
                    types.Part.from_text(text=prompt),
                ],
            ),
        )
        result = response.text.strip()
        # ✅ Log both request and response
        save_ai_request_with_attachment(
            model_name=model_used,
            prompt=prompt,
            response=result,
            file_bytes=file_bytes,
            mime_type=mime_type,
            user=user,
            filename=f"gemini_input_{timezone.now().strftime('%Y%m%d_%H%M%S')}.bin",
        )
        logger.debug(
            f"[ai.utils] Gemini file response length={len(result)} using model={model_used}"
        )
        return result
    except Exception as e:
        logger.warning("[ai.utils] Gemini multimodal API call failed", exc_info=True)
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


# ---------------------------------------------------------------------
# ⚙️ Model selection + failover helpers
# ---------------------------------------------------------------------
def _fetch_active_models(model_type: str) -> list[AIModelConfig]:
    """
    Return active models ordered by priority. If no entries exist for the requested type,
    fall back to text models so callers still have a pool to cycle through.
    """
    try:
        primary = list(
            AIModelConfig.objects.filter(is_active=True, type=model_type)
            .order_by("priority", "modified_at")
        )
        if primary:
            return primary
        if model_type != TEXT_MODEL_TYPE:
            logger.warning(
                "[ai.utils] No active %s models; falling back to text models",
                model_type,
            )
            return list(
                AIModelConfig.objects.filter(is_active=True, type=TEXT_MODEL_TYPE)
                .order_by("priority", "modified_at")
            )
    except Exception as e:
        logger.warning("[ai.utils] Failed to load AIModelConfig entries", exc_info=True)
    return []


def _execute_with_failover(model_type: str, executor):
    """
    Execute Gemini call against the highest priority model.
    On failure, bump priority so the model rests and try the next.
    Returns (response, user, model_name_used).
    """
    candidates = _fetch_active_models(model_type)
    last_exception = None

    if not candidates:
        logger.warning("[ai.utils] No AIModelConfig entries found; using DEFAULT_MODEL_ID fallback")
        client, user = get_gemini_client()
        response = executor(client, DEFAULT_MODEL_ID)
        return response, user, DEFAULT_MODEL_ID

    for model_cfg in candidates:
        model_display = f"{model_cfg.provider}:{model_cfg.model_id}"
        try:
            client, user = get_gemini_client(override_api_key=model_cfg.api_key)
            logger.debug(f"[ai.utils] Attempting Gemini call via {model_display} (priority={model_cfg.priority})")
            response = executor(client, model_cfg.model_id)
            _promote_model(model_cfg)
            return response, user, model_cfg.model_id
        except Exception as exc:
            last_exception = exc
            logger.warning(
                f"[ai.utils] Model {model_display} failed, bumping priority for cooldown",
                exc_info=True,
            )
            _bump_model_priority(model_cfg)

    if last_exception:
        raise last_exception
    raise RuntimeError("Gemini call failed without raising an explicit exception")


def _bump_model_priority(model_cfg: AIModelConfig):
    AIModelConfig.objects.filter(pk=model_cfg.pk).update(priority=F("priority") + PRIORITY_BUMP)


def _promote_model(model_cfg: AIModelConfig):
    AIModelConfig.objects.filter(pk=model_cfg.pk).update(
        priority=Greatest(Value(0), F("priority") - PRIORITY_RECOVERY)
    )
