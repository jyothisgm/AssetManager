from django.contrib import admin
from django.db.models import Q

from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Attachment, User, Role

admin.site.site_header = "Asset Manager Admin"
admin.site.site_title = "Asset Manager Portal"
admin.site.index_title = "Welcome to the Asset Manager Dashboard"


class RestrictedViewAdmin(admin.ModelAdmin):
    exclude = ("is_deleted", )

    def save_model(self, request, obj, form, change):
        if not obj.created_by:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)

    def has_change_permission(self, request, obj=None):
        if obj and not request.user.is_superuser:
            return obj.created_by == request.user
        return True

    def has_delete_permission(self, request, obj=None):
        if obj and not request.user.is_superuser:
            return obj.created_by == request.user
        return True

class RestrictedAdmin(RestrictedViewAdmin):
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Only show objects created by the user or all if superuser
        if request.user.is_superuser:
            return qs
        return qs.filter(created_by=request.user, is_deleted=False)


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Roles & Permissions", {"fields": ("roles", "is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"fields": ("email", "password1", "password2")}),)
    list_display = ("email", "is_staff", "is_superuser")
    search_fields = ("email",)
    ordering = ("email",)
    
    def get_readonly_fields(self, request, obj=None):
        if not request.user.is_superuser:
            return ['username', 'is_staff', 'is_superuser', 'user_permissions', 'groups', 'roles', 'email', 'is_active']
        return super().get_readonly_fields(request, obj)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Only show objects created by the user or all if superuser
        if request.user.is_superuser:
            return qs
        return qs.filter(email=request.user.email, is_deleted=False)
    
    def get_fieldsets(self, request, obj=None):
        if not request.user.is_superuser:
            fieldsets = (
                (None, {"fields": ("email", "password")}),
                ("Personal info", {"fields": ("first_name", "last_name")}),
                ("Roles & Permissions", {"fields": ("roles", )}),
            )
            return fieldsets
        return super().get_fieldsets(request, obj)

@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    filter_horizontal = ("permissions",)  # ✅ very important for M2M UI


# ------------------------------
# ATTACHMENT ADMIN
# ------------------------------
@admin.register(Attachment)
class AttachmentAdmin(RestrictedAdmin):
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
