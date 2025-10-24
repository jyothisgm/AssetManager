from django.db import models

class SoftDeleteQuerySet(models.QuerySet):
    def create(self, **kwargs):
        """
        If an object with same unique constraints exists and is soft-deleted,
        un-delete it instead of creating a duplicate.
        """
        model = self.model
        unique_fields = [
            f.name for f in model._meta.fields if f.unique and f.name != "id"
        ]
        filters = {f: kwargs[f] for f in unique_fields if f in kwargs}

        if filters:
            existing = model.all_objects.filter(**filters).first()
            if existing and existing.is_deleted:
                existing.is_deleted = False
                for key, value in kwargs.items():
                    setattr(existing, key, value)
                existing.save()
                print("♻️ Restored soft-deleted object:", existing)
                return existing
        return super().create(**kwargs)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)


# ---------- Base ----------
class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)
    is_deleted = models.BooleanField(default=False)

    class Meta:
        abstract = True

    objects = SoftDeleteManager()
    all_objects = models.Manager()  # to access even deleted
    
    def delete(self, *args, **kwargs):
        """Soft delete — just mark as deleted"""
        self.is_deleted = True
        self.save(update_fields=["is_deleted"])

    def hard_delete(self, *args, **kwargs):
        """Actual delete if ever needed"""
        super().delete(*args, **kwargs)


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
        label = f"{self.name}"
        if self.preferred:
            label += f" → {self.preferred.symbol}"
        return label + base


class Currency(TimeStampedModel):
    """
    ISO-based and crypto-compatible currency model for accounts, transactions, and analytics.
    """
    CURRENCY_TYPES = [
        ("fiat", "Fiat Currency"),
        ("crypto", "Cryptocurrency"),
    ]

    code = models.CharField(max_length=10, unique=True, help_text="Currency code (ISO 4217 or symbol like BTC)")
    name = models.CharField(max_length=64)
    symbol = models.CharField(max_length=8, blank=True, null=True)
    type = models.CharField(max_length=10, choices=CURRENCY_TYPES, default="fiat")
    country = models.CharField(max_length=64, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    rate_to_base = models.DecimalField(
        max_digits=18, decimal_places=8, default=1, help_text="Conversion rate to system base currency."
    )
    is_base_currency = models.BooleanField(default=False, help_text="Only one should be base.")

    class Meta:
        ordering = ["type", "code"]

    def __str__(self):
        t = "₿" if self.type == "crypto" else ""
        return f"{self.code} {t}".strip()

    def canonical(self):
        return self
