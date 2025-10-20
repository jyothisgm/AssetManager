from django.db import models
from common.models import TimeStampedModel, Unit

# ---------- Category ----------
class CategoryGroup(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    def __str__(self): return self.name


class PurchaseCategory(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    preferred = models.ForeignKey("self", related_name="variants",
                                  on_delete=models.SET_NULL, null=True, blank=True)
    description = models.TextField(blank=True, null=True)
    groups = models.ManyToManyField(CategoryGroup, related_name="categories", blank=True)
    def canonical(self): return self.preferred or self
    def __str__(self):
        groups = ", ".join(g.name for g in self.groups.all()) if self.pk else ""
        label = self.name + (f" ({groups})" if groups else "")
        if self.preferred: label += f" → {self.preferred.name}"
        return label


# ---------- Brand / Item ----------
class Brand(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey("self", related_name="variants",
                                  on_delete=models.SET_NULL, null=True, blank=True)
    def canonical(self): return self.preferred or self
    def __str__(self): return self.name


class ItemName(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey("self", related_name="variants",
                                  on_delete=models.SET_NULL, null=True, blank=True)
    brand = models.ForeignKey("catalog.Brand", related_name="items",
                              on_delete=models.SET_NULL, null=True, blank=True)
    preferred_unit = models.ForeignKey("common.Unit", related_name="default_for_items",
                                       on_delete=models.SET_NULL, null=True, blank=True)

    def canonical(self): return self.preferred or self
    def get_preferred_unit(self):
        if self.preferred_unit: return self.preferred_unit
        if self.preferred and self.preferred.preferred_unit:
            return self.preferred.preferred_unit
        return None
    def __str__(self):
        return f"{self.name}" + (f" → {self.preferred.name}" if self.preferred else "")


# ---------- Store ----------
class Store(TimeStampedModel):
    name = models.CharField(max_length=255, unique=True)
    preferred = models.ForeignKey("self", related_name="variants",
                                    on_delete=models.SET_NULL, null=True, blank=True)
    category = models.ForeignKey("catalog.PurchaseCategory", related_name="stores",
                                    on_delete=models.SET_NULL, null=True, blank=True)

    def canonical(self): 
        return self.preferred or self

    def __str__(self):
        label = self.preferred.name if self.preferred else self.name
        if self.category:
            groups = ", ".join(g.name for g in self.category.groups.all())
            return f"{label} ({self.category.name}{' - ' + groups if groups else ''})"
        return label


# ---------- Institution ----------
class Institution(TimeStampedModel):
    """
    Represents a financial or commercial institution such as a bank,
    credit card company, investment platform, or insurance provider.
    """

    name = models.CharField(max_length=100, unique=True)
    short_name = models.CharField(max_length=50, blank=True, null=True)
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

    def canonical(self):
        return self.preferred or self

    def __str__(self):
        return self.short_name or self.name


# catalog/models.py
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


class ExchangeRateRecord(TimeStampedModel):
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
        help_text="Mid-market rate at the time (e.g. ECB or CoinGecko)"
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

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        base = self.base_currency.code if hasattr(self.base_currency, "code") else str(self.base_currency)
        quote = self.quote_currency.code if hasattr(self.quote_currency, "code") else str(self.quote_currency)
        provider_name = self.provider.name if self.provider else "Unknown"
        return f"1 {base} = {self.provider_rate} {quote} ({provider_name})"
