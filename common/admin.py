from django.contrib import admin
from common.models import Unit, Attachment


# ------------------------------
# UNIT ADMIN
# ------------------------------
@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "symbol",
        "category",
        "preferred_display",
        "base_unit_display",
        "conversion_to_base",
        "variant_count",
        "created_at",
    )
    list_filter = ("category",)
    search_fields = ("name", "symbol")
    readonly_fields = ("created_at", "modified_at")

    def preferred_display(self, obj):
        return obj.preferred.name if obj.preferred else "-"
    preferred_display.short_description = "Preferred Unit"

    def base_unit_display(self, obj):
        return obj.base_unit.name if obj.base_unit else "-"
    base_unit_display.short_description = "Base Unit"

    def variant_count(self, obj):
        return obj.variants.count()


# ------------------------------
# ATTACHMENT ADMIN
# ------------------------------
@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "type",
        "description",
        "content_type",
        "object_id",
        "source_url",
        "created_at",
    )
    list_filter = ("type", "content_type")
    search_fields = ("description", "source_url", "text_content")
    readonly_fields = ("created_at", "modified_at")

    fieldsets = (
        ("Basic Info", {
            "fields": ("id", "type", "description", "file", "text_content", "source_url")
        }),
        ("Linked Object", {
            "fields": ("content_type", "object_id")
        }),
        ("Timestamps", {
            "fields": ("created_at", "modified_at"),
        }),
    )

    def has_add_permission(self, request):
        # usually attachments are created via API or inline, not from admin
        return True

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return True
