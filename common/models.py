from django.db import models

from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
from django.core.files.storage import FileSystemStorage

import uuid


# ---------- Base ----------
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    class Meta:
        abstract = True


# ---------- Units ----------
class Unit(TimeStampedModel):
    CATEGORY_CHOICES = [
        ("weight", "Weight"),
        ("length", "Length"),
        ("volume", "Volume"),
        ("pieces", "Pieces"),
    ]
    name = models.CharField(max_length=50, unique=True)
    symbol = models.CharField(max_length=10, blank=True, null=True)
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    preferred = models.ForeignKey("self", related_name="variants",
                                  on_delete=models.SET_NULL, null=True, blank=True)
    base_unit = models.ForeignKey("self", related_name="derived_units",
                                  on_delete=models.SET_NULL, null=True, blank=True)
    conversion_to_base = models.FloatField(null=True, blank=True)

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        base = f" (1 {self.symbol or self.name} = {self.conversion_to_base or 1} " \
               f"{self.base_unit.symbol if self.base_unit else self.symbol})"
        label = f"{self.name} ({self.symbol or ''})"
        if self.preferred:
            label += f" → {self.preferred.name}"
        return label + base


file_storage = FileSystemStorage(location="media/attachments", base_url="/media/attachments/")
class Attachment(TimeStampedModel):
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

