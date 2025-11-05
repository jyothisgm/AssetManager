from django.contrib.auth.models import AbstractUser, BaseUserManager, Permission
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
import uuid

import os
from common.models import SoftDeleteManager, SoftDeleteQuerySet, TimeStampedModel
from common.storage import get_dynamic_storage
from common.logging_config import logger, get_current_user


class UserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        func_name = f"{self.__class__.__name__}.create_user"
        try:
            if not email:
                logger.error(f"[{func_name}] Missing email during user creation")
                raise ValueError("Email must be provided")

            email = self.normalize_email(email)
            user = self.model(email=email, **extra_fields)
            user.set_password(password)
            user.save(using=self._db)

            logger.info(f"[{func_name}] User created successfully: {email}")
            return user
        except Exception as e:
            logger.exception(f"[{func_name}] Error creating user {email}")
            raise e

    def create_superuser(self, email, password=None, **extra_fields):
        func_name = f"{self.__class__.__name__}.create_superuser"
        try:
            extra_fields.setdefault("is_staff", True)
            extra_fields.setdefault("is_superuser", True)
            logger.info(f"[{func_name}] Creating superuser: {email}")
            return self.create_user(email, password, **extra_fields)
        except Exception as e:
            logger.exception(f"[{func_name}] Failed to create superuser {email}")
            raise e


class Role(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True, null=True)
    permissions = models.ManyToManyField(Permission, blank=True)

    def __str__(self):
        return self.name


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    roles = models.ManyToManyField(Role, blank=True)
    gemini_key = models.CharField(max_length=256, blank=True, null=True)
    is_verified = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    def __str__(self):
        return self.email

    def get_all_permissions(self, obj=None):
        func_name = f"{self.__class__.__name__}.get_all_permissions"
        try:
            perms = set(super().get_all_permissions(obj))
            if self.roles.exists():
                role_perms = self.roles.values_list(
                    "permissions__content_type__app_label",
                    "permissions__codename"
                )
                perms |= {f"{app}.{code}" for app, code in role_perms}
            return perms
        except Exception as e:
            logger.exception(f"[{func_name}] Error retrieving permissions for {self.email}")
            raise e

    def has_perm(self, perm, obj=None):
        func_name = f"{self.__class__.__name__}.has_perm"
        try:
            if self.is_superuser:
                return True
            codename = perm.split(".")[-1]
            if self.roles.filter(permissions__codename=codename).exists():
                return True
            return super().has_perm(perm, obj)
        except Exception as e:
            logger.exception(f"[{func_name}] Error checking permission {perm} for {self.email}")
            raise e

    def has_module_perms(self, app_label):
        func_name = f"{self.__class__.__name__}.has_module_perms"
        try:
            if self.is_superuser:
                return True
            if self.roles.filter(permissions__content_type__app_label=app_label).exists():
                logger.debug(f"[{func_name}] Role-based module permission granted for {app_label}")
                return True
            return super().has_module_perms(app_label)
        except Exception as e:
            logger.exception(f"[{func_name}] Error checking module perms for {app_label} / {self.email}")
            raise e

    def delete(self, *args, **kwargs):
        func_name = f"{self.__class__.__name__}.delete"
        try:
            logger.info(f"[{func_name}] Soft deleting user {self.email}")
            self.is_deleted = True
            self.is_active = False
            self.save(update_fields=["is_deleted", "is_active"])
        except Exception as e:
            logger.exception(f"[{func_name}] Error soft deleting user {self.email}")
            raise e


class BaseUserQuerySet(SoftDeleteQuerySet):
    def create(self, **kwargs):
        func_name = f"{self.__class__.__name__}.create"
        try:
            user = get_current_user()
            if not kwargs.get("created_by", None) and user and user.is_authenticated:
                kwargs["created_by"] = user
                logger.debug(f"[{func_name}] Setting created_by={user.email}")
            return super().create(**kwargs)
        except Exception as e:
            logger.exception(f"[{func_name}] Error during object creation")
            raise e


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
        editable=False,
    )

    class Meta:
        abstract = True

    objects = BaseUserManager()

    def delete(self, *args, **kwargs):
        func_name = f"{self.__class__.__name__}.delete"
        try:
            logger.info(f"[{func_name}] Soft deleting object ID={self.id}")
            self.is_deleted = True
            self.created_by = None
            self.save(update_fields=["is_deleted", "created_by"])
        except Exception as e:
            logger.exception(f"[{func_name}] Error soft deleting object ID={self.id}")
            raise e

    def save(self, *args, **kwargs):
        func_name = f"{self.__class__.__name__}.save"
        try:
            if not self.pk and not self.created_by:
                user = get_current_user()
                if user and user.is_authenticated:
                    self.created_by = user
                    logger.debug(f"[{func_name}] Auto-set created_by={user.email}")
            super().save(*args, **kwargs)
            logger.debug(f"[{func_name}] Object saved successfully ID={self.id}")
        except Exception as e:
            logger.exception(f"[{func_name}] Error saving object ID={getattr(self, 'id', None)}")
            raise e


def dynamic_attachment_path(instance, filename):
    from transaction.models import transaction_attachment_path
    from ai.models import ai_log_attachment_path
    """
    Calls a model-specific path function based on the parent model.
    """
    parent = getattr(instance, "content_object", None)
    if not parent:
        # default fallback
        return f"attachments/unknown/{filename}"

    model_name = parent.__class__.__name__.lower()

    # registry of model → function mapping
    path_map = {
        "transaction": transaction_attachment_path,
        "airequestlog": ai_log_attachment_path,
        # add more here, e.g.
        # "account": account_attachment_path,
    }

    path_func = path_map.get(model_name)

    if path_func:
        return path_func(instance, filename)
    else:
        # fallback generic path
        return os.path.join("attachments", model_name, filename)


def get_attachment_type(filename: str = "", mime_type: str = None) -> str:
    """
    Detects an appropriate Attachment.type value ("image", "pdf", "csv", "json", "text", "email", or "other")
    from MIME type or filename extension.

    :param filename: The uploaded file name
    :param mime_type: The MIME type string, if available
    :return: One of the allowed type strings
    """
    file_type = "other"

    # Normalize inputs
    mime = (mime_type or "").lower()
    ext = (filename or "").lower().split(".")[-1] if "." in (filename or "") else ""

    # Priority 1: use MIME type
    if "image" in mime:
        return "image"
    if "pdf" in mime:
        return "pdf"
    if "csv" in mime:
        return "csv"
    if "json" in mime:
        return "json"
    if "text" in mime or "plain" in mime:
        return "text"
    if "html" in mime or "xml" in mime:
        return "text"
    if "email" in mime or "message" in mime:
        return "email"

    # Priority 2: use extension
    if ext in ("png", "jpg", "jpeg", "gif", "bmp", "tiff", "webp"):
        return "image"
    if ext == "pdf":
        return "pdf"
    if ext == "csv":
        return "csv"
    if ext == "json":
        return "json"
    if ext in ("txt", "md", "log"):
        return "text"
    if ext in ("eml", "msg"):
        return "email"

    return file_type


# --- main Attachment model ---
class Attachment(BaseUserModel):
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
        upload_to=dynamic_attachment_path,
        storage=get_dynamic_storage(),
        null=True,
        blank=True,
        help_text="Uploaded file (optional).",
    )

    text_content = models.TextField(blank=True, null=True)
    source_url = models.URLField(blank=True, null=True)
    description = models.CharField(max_length=255, blank=True, null=True)

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.UUIDField()
    content_object = GenericForeignKey("content_type", "object_id")

    def __str__(self):
        parts = [self.type.capitalize()]

        # Include file name if available
        if self.file and hasattr(self.file, "name") and self.file.name:
            parts.append(os.path.basename(self.file.name))

        # Include linked object name if available
        if self.content_object:
            parts.append(str(self.content_object))

        # Include description if available
        if self.description:
            parts.append(self.description)

        # Join all parts with " – "
        return " – ".join(parts) or f"{self.type.capitalize()} ({self.id})"
