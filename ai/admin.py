from django.contrib import admin
from django.utils.html import format_html
from ai.models import AIRequestLog
from user.admin import RestrictedAdmin


@admin.register(AIRequestLog)
class AIRequestLogAdmin(RestrictedAdmin):
    list_display = (
        "short_id",
        "model_name",
        "created_by",
        "created_at",
        "has_attachment",
        "prompt_excerpt",
        "response_excerpt",
    )
    list_filter = ("model_name", "created_by", "mime_type", "created_at")
    search_fields = ("prompt_text", "response_text", "model_name")
    readonly_fields = (
        "id",
        "model_name",
        "prompt_text",
        "response_text",
        "mime_type",
        "attachment_link",
        "created_at",
    )
    fieldsets = (
        ("Request Info", {
            "fields": ("id", "model_name", "created_by", "mime_type", "created_at"),
        }),
        ("Prompt", {
            "fields": ("prompt_text", "attachment_link"),
        }),
        ("Response", {
            "fields": ("response_text",),
        }),
    )
    ordering = ("-created_at",)

    # --- Custom display helpers ---

    def short_id(self, obj):
        return str(obj.id)[:8]
    short_id.short_description = "ID"

    def has_attachment(self, obj):
        return bool(obj.attachment)
    has_attachment.boolean = True
    has_attachment.short_description = "File"

    def prompt_excerpt(self, obj):
        if not obj.prompt_text:
            return "-"
        text = obj.prompt_text.strip().replace("\n", " ")
        return (text[:80] + "...") if len(text) > 80 else text
    prompt_excerpt.short_description = "Prompt Preview"

    def response_excerpt(self, obj):
        if not obj.response_text:
            return "-"
        text = obj.response_text.strip().replace("\n", " ")
        return (text[:80] + "...") if len(text) > 80 else text
    response_excerpt.short_description = "Response Preview"

    def attachment_link(self, obj):
        """
        Display a download or preview link for the linked attachment.
        """
        if not obj.attachment or not getattr(obj.attachment, "file", None):
            return "-"
        url = obj.attachment.file.url
        filename = obj.attachment.file.name.split("/")[-1]

        mime = (obj.mime_type or "").lower()
        if "image" in mime:
            return format_html('<img src="{}" style="max-height:200px;border-radius:4px;"/>', url)
        return format_html('<a href="{}" target="_blank">📎 Download {}</a>', url, filename)
    attachment_link.short_description = "Attachment"
