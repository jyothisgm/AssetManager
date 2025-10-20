# accounts/models.py
from django.db import models
from common.models import TimeStampedModel
from catalog.models import Institution, Currency


class AccountType(TimeStampedModel):
    """
    Defines the category of an account (e.g. Bank, Cash, Credit Card, Loan).
    Allows dynamic addition and grouping (Asset, Liability, etc.)
    """
    TYPE_GROUPS = [
        ("asset", "Asset"),
        ("liability", "Liability"),
        ("equity", "Equity"),
        ("income", "Income"),
        ("expense", "Expense"),
    ]

    name = models.CharField(max_length=50, unique=True)
    code = models.CharField(
        max_length=20, unique=True, help_text="Short code or key for reference (e.g. BANK, CASH)"
    )
    group = models.CharField(
        max_length=20, choices=TYPE_GROUPS, default="asset", help_text="Broad financial category"
    )
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} ({self.group})"


class Account(TimeStampedModel):
    name = models.CharField(max_length=100)
    account_type = models.ForeignKey(AccountType, on_delete=models.PROTECT, related_name="accounts")
    institution = models.ForeignKey(
        Institution,
        related_name="accounts",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    currency = models.ForeignKey(
        Currency,
        related_name="accounts",
        on_delete=models.PROTECT,
        null=True,
        help_text="Currency of this account’s balance."
    )
    balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        cur = self.currency.code if self.currency else "—"
        return f"{self.name} ({self.account_type.name}, {cur})"


