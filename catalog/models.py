from django.db import models
from django.utils import timezone
import ai

from common.models import Currency
from user.models import BaseUserManager, BaseUserQuerySet, BaseUserModel
from common.logging_config import logger


# ============================================================
# Institution
# ============================================================

class InstitutionQuerySet(BaseUserQuerySet):
    def create(self, **kwargs):
        """
        Shared creation logic that runs for .create(), .get_or_create(),
        and .update_or_create().
        Adds AI-based enrichment of institution metadata.
        """
        func_name = f"{self.__class__.__name__}.create"

        ai_checked = kwargs.pop("is_deleted", None)
        short_name = kwargs.get("short_name", "").strip()

        # Skip AI processing if already handled or empty
        if not ai_checked and short_name:
            logger.debug(f"[{func_name}] AI enrichment triggered for '{short_name}'")

            existing_institutions = list(self.model.objects.values_list("name", flat=True))
            try:
                ai_lookup = ai.utils.get_institution_data([short_name], existing_institutions)
            except Exception as e:
                logger.exception(f"[{func_name}] AI lookup failed for '{short_name}'")
                ai_lookup = {}

            ai_info = ai_lookup.get(short_name, {})

            if short_name.lower() == "cash":
                logger.info(f"[{func_name}] Skipping 'cash' institution creation")
                return None

            # Fill AI-enriched fields
            kwargs["name"] = ai_info.get("name", short_name[:50]).title()
            kwargs["short_name"] = ai_info.get("short_name", short_name[:50]).title()
            kwargs["type"] = ai_info.get("type", "other").lower()
            kwargs["country"] = ai_info.get("country", "Unknown")
            kwargs["website"] = ai_info.get("website")

            # Deduplicate by short_name
            existing = self.filter(short_name__iexact=kwargs["short_name"]).first()
            if existing:
                logger.info(f"[{func_name}] Institution '{short_name}' already exists → using existing record")
                return existing

            logger.info(f"[{func_name}] Creating new Institution: {kwargs}")

        return super().create(**kwargs)


class InstitutionManager(BaseUserManager.from_queryset(InstitutionQuerySet)):
    """Attach custom queryset logic to the manager."""
    pass


class Institution(BaseUserModel):
    """
    Represents a financial or commercial institution such as a bank,
    credit card company, investment platform, or insurance provider.
    """

    name = models.CharField(max_length=100)
    short_name = models.CharField(max_length=50, unique=True)
    type = models.CharField(
        max_length=30,
        choices=[
            ("bank", "Bank"),
            ("credit_card", "Credit Card Issuer"),
            ("broker", "Investment / Brokerage"),
            ("insurance", "Insurance"),
            ("fintech", "Fintech / Wallet"),
            ("other", "Other"),
        ],
        default="bank",
    )
    country = models.CharField(max_length=50, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    logo = models.ImageField(upload_to="institutions/logos/", blank=True, null=True)

    preferred = models.ForeignKey(
        "self", related_name="variants", on_delete=models.SET_NULL, null=True, blank=True
    )

    objects = InstitutionManager()

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        return self.short_name or self.name


# ============================================================
# Categories
# ============================================================

class CategoryGroup(BaseUserModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.name


class PurchaseCategory(BaseUserModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    group = models.ForeignKey(
        CategoryGroup,
        related_name="categories",
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
    )

    def canonical(self):
        return self

    def __str__(self):
        group_name = self.group.name if self.group else ""
        return f"{self.name} ({group_name})" if group_name else self.name


# ============================================================
# Brand / Product
# ============================================================

class Brand(BaseUserModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey(
        "self",
        related_name="variants",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        return self.name


class Product(BaseUserModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey(
        "self",
        related_name="variants",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    brand = models.ForeignKey(
        "catalog.Brand",
        related_name="items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    preferred_unit = models.ForeignKey(
        "common.Unit",
        related_name="default_for_items",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    category = models.ForeignKey(
        PurchaseCategory,
        related_name="products",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )

    def canonical(self):
        return self.preferred or self

    def get_preferred_unit(self):
        if self.preferred_unit:
            return self.preferred_unit
        if self.preferred and self.preferred.preferred_unit:
            return self.preferred.preferred_unit
        return None

    def __str__(self):
        label = self.name
        if self.preferred:
            label += f" → {self.preferred.name}"
            category = self.preferred.category
        else:
            category = self.category

        if category:
            label += f" ({category.name})"
        return label


# ============================================================
# Store
# ============================================================

class Store(BaseUserModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey(
        "self",
        related_name="variants",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    categories = models.ManyToManyField(
        PurchaseCategory, related_name="stores", blank=True
    )

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        label = self.preferred.name if self.preferred else self.name
        cats = list(self.categories.all()[:2])
        if cats:
            cat_labels = ", ".join(c.name for c in cats)
            return f"{label} ({cat_labels})"
        return label


# ============================================================
# Exchange Rate
# ============================================================

class ExchangeRateRecord(BaseUserModel):
    """
    Immutable record of an exchange rate used during a transfer or cross-currency transaction.
    Stored as metadata inside Transaction (no reverse relation).
    """

    base_currency = models.ForeignKey(
        Currency,
        related_name="+",
        on_delete=models.PROTECT,
        help_text="Currency being converted from",
    )
    quote_currency = models.ForeignKey(
        Currency,
        related_name="+",
        on_delete=models.PROTECT,
        help_text="Currency being converted to",
    )

    market_rate = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        help_text="Mid-market rate at the time (e.g. ECB or CoinGecko)",
        null=True,
        blank=True,
    )
    provider_rate = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        help_text="Actual rate used by the institution performing the conversion",
    )
    provider = models.ForeignKey(
        Institution,
        related_name="+",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Institution or service provider that executed the exchange (e.g. Revolut, Wise, Binance)",
    )
    fee_percent = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=0,
        help_text="Markup percentage between market and provider rate",
    )
    date = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        base = getattr(self.base_currency, "code", str(self.base_currency))
        quote = getattr(self.quote_currency, "code", str(self.quote_currency))
        provider_name = self.provider.name if self.provider else "Unknown"
        return f"1 {base} = {self.provider_rate} {quote} ({provider_name})"
