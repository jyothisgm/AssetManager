from django.db import models
import ai
from common.models import Currency
from django.utils import timezone

from user.models import BaseUserManager, BaseUserQuerySet, BaseUserModel


class InstitutionQuerySet(BaseUserQuerySet):
    def create(self, **kwargs):
        """
        Shared creation logic that runs for .create(), .get_or_create(),
        and .update_or_create().
        """
        # Extract flags and normalize name
        ai_checked = kwargs.pop("is_deleted", None)
        short_name = kwargs.get("short_name", "").strip()

        # Skip AI processing if already marked or empty
        if not ai_checked and short_name:
            print("⚠️ Reached AI Check: ", kwargs)

            existing_institutions = self.model.objects.values_list("name", flat=True)
            try:
                ai_lookup = ai.utils.get_institution_data([short_name], existing_institutions)
            except Exception as e:
                print("❌ AI lookup failed:", e)
                ai_lookup = {}

            ai_info = ai_lookup.get(short_name, {})

            # Skip creating cash institution
            if short_name.lower() == "cash":
                print("⚠️ Skipping 'cash' institution")
                return None

            # Fill AI-enriched info
            kwargs["name"] = ai_info.get("name", short_name[:50]).title()
            kwargs["short_name"] = ai_info.get("short_name", short_name[:50]).title()
            kwargs["type"] = ai_info.get("type", "other").lower()
            kwargs["country"] = ai_info.get("country", "Unknown")
            kwargs["website"] = ai_info.get("website")
            print(kwargs)
            instance = self.filter(short_name__iexact=kwargs["short_name"]).first()
            if instance:
                return instance
        return super().create(**kwargs)


class InstitutionManager(BaseUserManager.from_queryset(InstitutionQuerySet)):
    """Attach the custom queryset logic to the manager."""
    pass


# ---------- Institution ----------
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


# ---------- Category ----------
class CategoryGroup(BaseUserModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    def __str__(self): return self.name


class PurchaseCategory(BaseUserModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    group = models.ForeignKey(CategoryGroup, related_name="categories", blank=True, null=True, on_delete=models.SET_NULL)

    def canonical(self): 
        return self

    def __str__(self):
        group = self.group if self.pk else ""
        label = self.name + f" -> ({group})" 
        return label


# ---------- Brand / Item ----------
class Brand(BaseUserModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey("self", related_name="variants",
                                    on_delete=models.SET_NULL, null=True, blank=True)
    def canonical(self): return self.preferred or self
    def __str__(self): return self.name


class Product(BaseUserModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey("self", related_name="variants",
                                    on_delete=models.SET_NULL, null=True, blank=True)
    brand = models.ForeignKey("catalog.Brand", related_name="items",
                                on_delete=models.SET_NULL, null=True, blank=True)
    preferred_unit = models.ForeignKey("common.Unit", related_name="default_for_items",
                                        on_delete=models.SET_NULL, null=True, blank=True)
    category = models.ForeignKey(PurchaseCategory, related_name="products", on_delete=models.SET_NULL,
                                    null=True, blank=True)

    def canonical(self):
        return self.preferred or self

    def get_preferred_unit(self):
        if self.preferred_unit: return self.preferred_unit
        if self.preferred and self.preferred.preferred_unit:
            return self.preferred.preferred_unit
        return None

    def __str__(self):
        label = self.name
        category = None
        if self.preferred:
            label += f" → {self.preferred.name}"
            category = self.preferred.category
        else:
            category = self.category

        if category:
            label += f" ({category.name})"

        return label


# ---------- Store ----------
class Store(BaseUserModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey(
        "self", related_name="variants",
        on_delete=models.SET_NULL, null=True, blank=True
    )
    categories = models.ManyToManyField(PurchaseCategory, related_name="stores", blank=True)

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        label = self.preferred.name if self.preferred else self.name

        # Show up to 2 categories in parentheses (to keep it readable)
        cats = self.categories.all()[:2]
        if cats:
            cat_labels = ", ".join(c.name for c in cats)
            return f"{label} ({cat_labels})"
        return label


class ExchangeRateRecord(BaseUserModel):
    """
    Immutable record of an exchange rate used during a transfer or cross-currency transaction.
    Stored as metadata inside Transaction (no reverse relation).
    """

    base_currency = models.ForeignKey(
        Currency,
        related_name="+",
        on_delete=models.PROTECT,
        help_text="Currency being converted from"
    )
    quote_currency = models.ForeignKey(
        Currency,
        related_name="+",
        on_delete=models.PROTECT,
        help_text="Currency being converted to"
    )

    market_rate = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        help_text="Mid-market rate at the time (e.g. ECB or CoinGecko)",
        null=True, blank=True
    )
    provider_rate = models.DecimalField(
        max_digits=20,
        decimal_places=8,
        help_text="Actual rate used by the institution performing the conversion"
    )

    provider = models.ForeignKey(
        Institution,
        related_name="+",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Institution or service provider that executed the exchange (e.g. Revolut, Wise, Binance)"
    )

    fee_percent = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=0,
        help_text="Markup percentage between market and provider rate"
    )
    
    date = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        base = self.base_currency.code if hasattr(self.base_currency, "code") else str(self.base_currency)
        quote = self.quote_currency.code if hasattr(self.quote_currency, "code") else str(self.quote_currency)
        provider_name = self.provider.name if self.provider else "Unknown"
        return f"1 {base} = {self.provider_rate} {quote} ({provider_name})"
