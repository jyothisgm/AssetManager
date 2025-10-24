from django.contrib.auth.models import AbstractUser, BaseUserManager, Permission
from django.db import models
from django.utils.translation import gettext_lazy as _

from django.db import models
from django.conf import settings
from django.utils import timezone

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.files.storage import FileSystemStorage

import uuid

import ai
from common.models import SoftDeleteManager, SoftDeleteQuerySet, TimeStampedModel
from main.middleware import get_current_user


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError("Email must be provided")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        return self.create_user(email, password, **extra_fields)


class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    permissions = models.ManyToManyField(Permission, blank=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    username = None  # remove username
    email = models.EmailField(unique=True)
    roles = models.ManyToManyField(Role, blank=True)
    gemini_key = models.CharField(max_length=256)
    is_verified = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email

    def get_all_permissions(self, obj=None):
        """
        Combine Django's built-in permissions + all Role-based permissions.
        """
        perms = set(super().get_all_permissions(obj))
        if self.roles.exists():
            role_perms = (
                self.roles.values_list(
                    "permissions__content_type__app_label",
                    "permissions__codename"
                )
            )
            perms |= {f"{app}.{code}" for app, code in role_perms}
        return perms

    def has_perm(self, perm, obj=None):
        """
        Check permission across both native permissions and role-based ones.
        """
        if self.is_superuser:
            return True
        if self.roles.filter(permissions__codename=perm.split(".")[-1]).exists():
            return True
        return super().has_perm(perm, obj)

    def has_module_perms(self, app_label):
        """
        Django Admin calls this to decide whether to show an app.
        """
        if self.is_superuser:
            return True
        if self.roles.filter(permissions__content_type__app_label=app_label).exists():
            return True
        return super().has_module_perms(app_label)

    def delete(self, *args, **kwargs):
        """Soft delete — just mark as deleted"""
        self.is_deleted = True
        self.is_active = False
        self.save(update_fields=["is_deleted", "is_active"])



class BaseUserQuerySet(SoftDeleteQuerySet):
    def create(self, **kwargs):
        """
        Shared creation logic that runs for .create(), .get_or_create(),
        and .update_or_create().
        """
        user = get_current_user()
        if user and user.is_authenticated:
            kwargs['created_by'] = user
        return super().create(**kwargs)

class BaseUserManager(SoftDeleteManager.from_queryset(BaseUserQuerySet)):
    """Attach the custom queryset logic to the manager."""
    pass


class BaseUserModel(TimeStampedModel):
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="%(class)s_created",
        null=True,
        blank=True,
        editable=False,  # ✅ not editable in any form
    )

    class Meta:
        abstract = True  # Don’t create a table for this

    objects = BaseUserManager()
    
    def delete(self, *args, **kwargs):
        """Soft delete — just mark as deleted"""
        self.is_deleted = True
        self.created_by = None
        self.save(update_fields=["is_deleted", "created_by"])
    
    def save(self, *args, **kwargs):
        """
        Auto-set created_by from the current logged-in user if available.
        """
        if not self.pk and not self.created_by:
            user = get_current_user()
            if user and user.is_authenticated:
                self.created_by = user
        super().save(*args, **kwargs)


file_storage = FileSystemStorage(location="media/attachments", base_url="/media/attachments/")
class Attachment(BaseUserModel):
    """
    A generalized attachment that can belong to any object (transaction, income, bill, etc.)
    Supports image, PDF, email, text, CSV, JSON, or any other type of uploaded file or text.
    """
    ATTACHMENT_TYPES = [
        ("image", "Image"),
        ("pdf", "PDF"),
        ("email", "Email"),
        ("text", "Text"),
        ("csv", "CSV"),
        ("json", "JSON"),
        ("other", "Other"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=20, choices=ATTACHMENT_TYPES, default="other")

    file = models.FileField(
        upload_to="attachments/",
        storage=file_storage,
        null=True,
        blank=True,
        help_text="Uploaded file (optional).",
    )
    text_content = models.TextField(blank=True, null=True, help_text="Raw text or parsed content.")
    source_url = models.URLField(blank=True, null=True, help_text="Optional source URL (e.g., web receipt or email link).")
    description = models.CharField(max_length=255, blank=True, null=True)

    # 🔗 Generic relation to link with any model
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey("content_type", "object_id")

    def __str__(self):
        return self.description or f"{self.type.capitalize()} ({self.id})"

