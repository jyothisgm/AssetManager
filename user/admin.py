from django.contrib import admin
from django.db.models import Q
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.urls import reverse
from .models import Attachment, User, Role
from common.logging_config import logger
from django.contrib import messages
from django.utils.translation import gettext_lazy as _
from django.contrib.admin.sites import site
from django.utils.safestring import mark_safe
from django.utils.html import format_html
from django.template.response import TemplateResponse
from django_admin_listfilter_dropdown.filters import RelatedOnlyDropdownFilter
from django.contrib.admin import SimpleListFilter
from django.contrib.contenttypes.models import ContentType



admin.site.site_header = "Asset Manager Admin"
admin.site.site_title = "Asset Manager Portal"
admin.site.index_title = "Welcome to the Asset Manager Dashboard"

class UsedTypeFilter(SimpleListFilter):
    title = "type"
    parameter_name = "type"

    def lookups(self, request, model_admin):
        # Return only distinct types in DB
        if not request.user.is_superuser:
            values = model_admin.model.objects.filter(created_by=request.user).values_list("type", flat=True).distinct()
        else:
            values = model_admin.model.objects.values_list("type", flat=True).distinct()
        return [(v, v) for v in values if v]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(type=self.value())
        return queryset


class UsedContentTypeFilter(SimpleListFilter):
    title = "content type"
    parameter_name = "content_type"

    def lookups(self, request, model_admin):
        if not request.user.is_superuser:
            used_ids = (
                model_admin.model.objects.values_list("content_type", flat=True)
                .filter(created_by=request.user)
                .exclude(content_type__isnull=True)
                .distinct()
            )
        else:
            used_ids = (
                model_admin.model.objects.values_list("content_type", flat=True)
                .exclude(content_type__isnull=True)
                .distinct()
            )
        types = ContentType.objects.filter(id__in=used_ids)
        return [(t.id, t.name.title()) for t in types]

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(content_type=self.value())
        return queryset


class RestrictedViewAdmin(admin.ModelAdmin):
    exclude = ("is_deleted", )

    def get_readonly_fields(self, request, obj=None):
        """
        Combine subclass readonly_fields with enforced ones.
        """
        base_fields = ("id", "created_by")
        subclass_fields = getattr(self, "readonly_fields", ())
        # ensure uniqueness while preserving tuple form
        merged = tuple(sorted(set(subclass_fields + base_fields)))
        return merged

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

    @admin.display(description="", ordering=False)
    def action_checkbox(self, obj):
        """
        Override Django's built-in action_checkbox column.
        Render checkbox only if the user is allowed to act on this object.
        """
        request = getattr(self, "_request_cache", None)
        if not request:
            return ""
        if request.user.is_superuser or getattr(obj, "created_by_id", None) == request.user.id:
            return format_html(
                '<input type="checkbox" name="_selected_action" value="{}" class="action-select">',
                obj.pk,
            )
        return ""

    def changelist_view(self, request, extra_context=None):
        """Cache request for use inside custom_action_checkbox."""
        self._request_cache = request
        return super().changelist_view(request, extra_context)

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

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            RelatedModel = db_field.remote_field.model
            related_admin = self._get_related_admin(RelatedModel)

            # Restrict only if the related admin is a RestrictedAdmin subclass
            if isinstance(related_admin, RestrictedAdmin):
                if hasattr(RelatedModel, "created_by"):
                    kwargs["queryset"] = RelatedModel.objects.filter(
                        created_by=request.user, is_deleted=False
                    )

        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def _get_related_admin(self, model):
        """Utility to get the admin class registered for a model."""
        return admin.site._registry.get(model)

    def formfield_for_manytomany(self, db_field, request, **kwargs):
        if not request.user.is_superuser:
            RelatedModel = db_field.remote_field.model
            related_admin = self._get_related_admin(RelatedModel)

            if isinstance(related_admin, RestrictedAdmin):
                if hasattr(RelatedModel, "created_by"):
                    kwargs["queryset"] = RelatedModel.objects.filter(
                        created_by=request.user, is_deleted=False
                    )

        return super().formfield_for_manytomany(db_field, request, **kwargs)


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
    filter_horizontal = ("permissions",)


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
    list_filter = (UsedTypeFilter, UsedContentTypeFilter, ("created_by", RelatedOnlyDropdownFilter))
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

_original_index = site.index

def custom_index(request, extra_context=None):
    if request.user.is_authenticated and not getattr(request.user, "gemini_key", None):
        message_html = mark_safe(
            f'Your Gemini API key is not set. '
            f'<a href="/admin/user/user/{request.user.id}/change/">Set it here</a>.'
        )
        messages.warning(request, message_html)
    return _original_index(request, extra_context)

site.index = custom_index
