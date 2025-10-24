from django.contrib import admin
from django.db.models import Q
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import Attachment, User, Role
from common.logging_config import logger

admin.site.site_header = "Asset Manager Admin"
admin.site.site_title = "Asset Manager Portal"
admin.site.index_title = "Welcome to the Asset Manager Dashboard"


class RestrictedViewAdmin(admin.ModelAdmin):
    exclude = ("is_deleted", )

    def save_model(self, request, obj, form, change):
        func_name = f"{self.__class__.__name__}.save_model"
        try:
            if not obj.created_by:
                obj.created_by = request.user
                logger.debug(f"[{func_name}] Auto-set created_by={request.user.email} for {obj}")
            super().save_model(request, obj, form, change)
            logger.info(f"[{func_name}] Object saved successfully by {request.user.email}: {obj}")
        except Exception as e:
            logger.exception(f"[{func_name}] Error saving object by {request.user.email}")
            raise e

    def has_change_permission(self, request, obj=None):
        func_name = f"{self.__class__.__name__}.has_change_permission"
        try:
            if obj and not request.user.is_superuser:
                allowed = obj.created_by == request.user
                logger.debug(f"[{func_name}] {request.user.email} {'allowed' if allowed else 'denied'} to change {obj}")
                return allowed
            return True
        except Exception as e:
            logger.exception(f"[{func_name}] Error checking change permission")
            raise e

    def has_delete_permission(self, request, obj=None):
        func_name = f"{self.__class__.__name__}.has_delete_permission"
        try:
            if obj and not request.user.is_superuser:
                allowed = obj.created_by == request.user
                logger.debug(f"[{func_name}] {request.user.email} {'allowed' if allowed else 'denied'} to delete {obj}")
                return allowed
            return True
        except Exception as e:
            logger.exception(f"[{func_name}] Error checking delete permission")
            raise e


class RestrictedAdmin(RestrictedViewAdmin):
    def get_queryset(self, request):
        func_name = f"{self.__class__.__name__}.get_queryset"
        try:
            qs = super().get_queryset(request)
            if request.user.is_superuser:
                logger.debug(f"[{func_name}] Superuser {request.user.email} — returning full queryset")
                return qs
            filtered = qs.filter(created_by=request.user, is_deleted=False)
            logger.debug(f"[{func_name}] Returning {filtered.count()} records for {request.user.email}")
            return filtered
        except Exception as e:
            logger.exception(f"[{func_name}] Error fetching queryset for {request.user.email}")
            raise e


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Keys", {"fields": ("gemini_key",)}),
        ("Roles & Permissions", {"fields": ("roles", "is_active", "is_staff", "is_superuser")}),
    )
    add_fieldsets = ((None, {"fields": ("email", "password1", "password2")}),)
    list_display = ("email", "is_staff", "is_superuser")
    search_fields = ("email",)
    ordering = ("email",)

    def get_readonly_fields(self, request, obj=None):
        func_name = f"{self.__class__.__name__}.get_readonly_fields"
        try:
            if not request.user.is_superuser:
                logger.debug(f"[{func_name}] Restricting readonly fields for non-superuser {request.user.email}")
                return ['username', 'is_staff', 'is_superuser', 'user_permissions', 'groups', 'roles', 'email', 'is_active']
            return super().get_readonly_fields(request, obj)
        except Exception as e:
            logger.exception(f"[{func_name}] Error getting readonly fields")
            raise e

    def get_queryset(self, request):
        func_name = f"{self.__class__.__name__}.get_queryset"
        try:
            qs = super().get_queryset(request)
            if request.user.is_superuser:
                logger.debug(f"[{func_name}] Superuser {request.user.email} viewing all users")
                return qs
            filtered = qs.filter(email=request.user.email, is_deleted=False)
            logger.debug(f"[{func_name}] Restricted queryset to current user {request.user.email}")
            return filtered
        except Exception as e:
            logger.exception(f"[{func_name}] Error fetching queryset for {request.user.email}")
            raise e

    def get_fieldsets(self, request, obj=None):
        func_name = f"{self.__class__.__name__}.get_fieldsets"
        try:
            if not request.user.is_superuser:
                logger.debug(f"[{func_name}] Returning limited fieldsets for {request.user.email}")
                fieldsets = (
                    (None, {"fields": ("email", "password")}),
                    ("Personal info", {"fields": ("first_name", "last_name")}),
                    ("Keys", {"fields": ("gemini_key",)}),
                    ("Roles & Permissions", {"fields": ("roles",)}),
                )
                return fieldsets
            return super().get_fieldsets(request, obj)
        except Exception as e:
            logger.exception(f"[{func_name}] Error getting fieldsets")
            raise e


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("name", "description")
    filter_horizontal = ("permissions",)  # ✅ better UI for permissions


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
