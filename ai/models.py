# ai/models.py
import mimetypes
import os
import uuid
from datetime import datetime

from django.db import models
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.core.files.base import ContentFile

from user.models import BaseUserModel, Attachment, get_attachment_type
from common.logging_config import logger


# -------------------------------------------------------------------
# PATH FUNCTION
# -------------------------------------------------------------------
def ai_log_attachment_path(instance, filename):
    """
    Generates and ensures structured path for uploaded AI log attachments.

    Example:
        attachments/ai_logs/42_tony_example_com/20251025_152400_prompt_receipt.png
    """
    func_name = "ai_log_attachment_path"
    try:
        # --- User info ---
        user_email = getattr(instance.created_by, "email", "unknown_user")
        user_pk = getattr(instance.created_by, "pk", None)
        safe_user = f"{user_pk}_" if user_pk else ""
        safe_user += user_email.replace("@", "_at_").replace(".", "_")

        # --- File info ---
        extension = filename.split(".")[-1]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # --- Context info ---
        ai_request = getattr(instance, "content_object", None)
        model_name = getattr(ai_request, "model_name", "prompt")
        model_name = model_name.replace("/", "_").replace(" ", "_")

        # --- Construct custom filename ---
        custom_name = f"{timestamp}_{model_name}_{filename}"

        # --- Build relative + absolute paths ---
        relative_dir = os.path.join("ai_logs", safe_user)
        relative_path = os.path.join(relative_dir, custom_name)
        full_dir = os.path.join(settings.MEDIA_ROOT, "attachments", relative_dir)

        # --- Ensure directories exist ---
        os.makedirs(full_dir, exist_ok=True)

        logger.debug(f"[{func_name}] Path resolved: {relative_path}")
        return relative_path
    except Exception as e:
        logger.exception(f"[{func_name}] Error creating AI log path: {e}")
        # fallback path if something fails
        return os.path.join("ai_logs", "unknown_user", filename)


# -------------------------------------------------------------------
# MODEL
# -------------------------------------------------------------------
class AIRequestLog(BaseUserModel):
    """Stores every AI request (prompt + file + response)."""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_name = models.CharField(max_length=255)
    prompt_text = models.TextField(blank=True, null=True)
    response_text = models.TextField(blank=True, null=True)
    mime_type = models.CharField(max_length=100, blank=True, null=True)

    attachment = models.ForeignKey(
        Attachment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_logs",
        help_text="Attachment linked to this AI request (input file, image, or document).",
    )

    def __str__(self):
        return f"{self.model_name} | {self.created_at.strftime('%Y-%m-%d %H:%M:%S')}"


def save_ai_request_with_attachment(
    model_name,
    prompt,
    response,
    file_bytes=None,
    mime_type=None,
    user=None,
    filename=None
):
    """
    Create an AIRequestLog entry and optionally attach the uploaded file.
    Automatically detects and assigns Attachment.type using MIME type or filename.
    """
    func_name = "save_ai_request_with_attachment"
    attachment = None
    log_entry = None

    try:
        # -----------------------------------------------------------
        # 1️⃣ Detect file type using shared utility
        # -----------------------------------------------------------
        file_type = get_attachment_type(filename, mime_type)

        # -----------------------------------------------------------
        # 2️⃣ Create Attachment if a file is provided
        # -----------------------------------------------------------
        if file_bytes and filename:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            superuser = User.objects.filter(is_superuser=True).first()

            # --- Build new filename ---
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = os.path.splitext(filename)[1].lstrip(".") or "bin"
            clean_name = os.path.splitext(filename)[0]
            new_filename = f"{timestamp}_{clean_name}.{ext}"

            # --- Create Attachment record ---
            attachment = Attachment.objects.create(
                type=file_type,
                description=f"{file_type.capitalize()} uploaded for AI request - {filename}",
                content_type=ContentType.objects.get_for_model(AIRequestLog),
                object_id=uuid.uuid4(),  # temporary placeholder until log created
                created_by=user or superuser,
            )

            # --- Save file ---
            attachment.file.save(new_filename, ContentFile(file_bytes), save=True)
            logger.debug(f"[{func_name}] Saved attachment ({file_type}) as {new_filename}")

        # -----------------------------------------------------------
        # 3️⃣ Create the AIRequestLog entry
        # -----------------------------------------------------------
        log_entry = AIRequestLog.objects.create(
            model_name=model_name,
            prompt_text=prompt,
            response_text=response,
            mime_type=mime_type,
            created_by=user,
            attachment=attachment,
        )

        logger.info(f"[{func_name}] Created AIRequestLog for model={model_name} by {getattr(user, 'email', 'unknown')}")

        # -----------------------------------------------------------
        # 4️⃣ Link attachment to the real log entry
        # -----------------------------------------------------------
        if attachment:
            attachment.content_type = ContentType.objects.get_for_model(log_entry)
            attachment.object_id = log_entry.id
            attachment.save(update_fields=["content_type", "object_id"])
            logger.debug(f"[{func_name}] Linked attachment {attachment.id} → AIRequestLog {log_entry.id}")

    except Exception as e:
        logger.exception(f"[{func_name}] Error saving AI request log: {e}")

    return log_entry
