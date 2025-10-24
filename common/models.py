from django.db import models
from common.logging_config import logger, raise_with_line_info


class SoftDeleteQuerySet(models.QuerySet):
    def create(self, **kwargs):
        """
        If an object with same unique constraints exists and is soft-deleted,
        un-delete it instead of creating a duplicate.
        """
        func_name = f"{self.__class__.__name__}.create"
        try:
            model = self.model
            unique_fields = [
                f.name for f in model._meta.fields if f.unique and f.name != "id"
            ]
            filters = {f: kwargs[f] for f in unique_fields if f in kwargs}

            logger.debug(f"[{func_name}] kwargs={kwargs}, unique_fields={unique_fields}, filters={filters}")

            if filters:
                existing = model.all_objects.filter(**filters).first()
                if existing and existing.is_deleted:
                    logger.info(f"[{func_name}] Restoring soft-deleted object: {existing}")
                    existing.is_deleted = False
                    for key, value in kwargs.items():
                        setattr(existing, key, value)
                    existing.save()
                    logger.debug(f"[{func_name}] Object restored and saved successfully: {existing}")
                    return existing

            logger.debug(f"[{func_name}] Creating new instance for model {model.__name__}")
            instance = super().create(**kwargs)
            logger.info(f"[{func_name}] Created new instance: {instance}")
            return instance

        except Exception as e:
            logger.exception(f"[{func_name}] Error during create operation")
            raise_with_line_info(func_name, e)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):
    def get_queryset(self):
        func_name = f"{self.__class__.__name__}.get_queryset"
        try:
            qs = super().get_queryset().filter(is_deleted=False)
            logger.debug(f"[{func_name}] Returning queryset filtered for non-deleted items")
            return qs
        except Exception as e:
            logger.exception(f"[{func_name}] Failed to build queryset")
            raise_with_line_info(func_name, e)


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
        func_name = f"{self.__class__.__name__}.delete"
        try:
            logger.info(f"[{func_name}] Soft deleting object ID={self.id}")
            self.is_deleted = True
            self.save(update_fields=["is_deleted"])
            logger.debug(f"[{func_name}] Marked as deleted successfully")
        except Exception as e:
            logger.exception(f"[{func_name}] Error during soft delete")
            raise_with_line_info(func_name, e)

    def hard_delete(self, *args, **kwargs):
        """Actual delete if ever needed"""
        func_name = f"{self.__class__.__name__}.hard_delete"
        try:
            logger.warning(f"[{func_name}] Performing hard delete on ID={self.id}")
            super().delete(*args, **kwargs)
            logger.debug(f"[{func_name}] Hard delete completed")
        except Exception as e:
            logger.exception(f"[{func_name}] Error during hard delete")
            raise_with_line_info(func_name, e)


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
    preferred = models.ForeignKey(
        "self", related_name="variants",
        on_delete=models.SET_NULL, null=True, blank=True
    )
    base_unit = models.ForeignKey(
        "self", related_name="derived_units",
        on_delete=models.SET_NULL, null=True, blank=True
    )
    conversion_to_base = models.FloatField(null=True, blank=True)

    def canonical(self):
        func_name = f"{self.__class__.__name__}.canonical"
        try:
            result = self.preferred or self
            logger.debug(f"[{func_name}] canonical={result}")
            return result
        except Exception as e:
            logger.exception(f"[{func_name}] Error computing canonical unit")
            raise_with_line_info(func_name, e)

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
        func_name = f"{self.__class__.__name__}.canonical"
        try:
            logger.debug(f"[{func_name}] Returning canonical currency: {self}")
            return self
        except Exception as e:
            logger.exception(f"[{func_name}] Error in canonical method")
            raise_with_line_info(func_name, e)
