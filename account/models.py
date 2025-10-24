# account/models.py
from django.db import models
from catalog.models import Institution, Currency
from django.db.models import Sum, Case, When, F, DecimalField

from common.models import TimeStampedModel
from user.models import BaseUserModel


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
        ("insurance", "Insurance"),
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


class Account(BaseUserModel):
    name = models.CharField(max_length=100)
    account_type = models.ForeignKey(AccountType, on_delete=models.PROTECT, related_name="account")
    institution = models.ForeignKey(
        Institution,
        related_name="account",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    currency = models.ForeignKey(
        Currency,
        related_name="account",
        on_delete=models.PROTECT,
        null=True,
        help_text="Currency of this account’s balance."
    )
    # balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        cur = self.currency.code if self.currency else "—"
        return f"{self.name} ({self.account_type.name}, {cur})"
    
    @property
    def computed_balance(self):
        """
        Calculates current balance from related transactions.
        Credits increase balance; debits decrease it.
        """
        from transaction.models import Transaction  # avoid circular import

        result = (
            Transaction.objects.filter(account=self)
            .aggregate(
                balance=Sum(
                    Case(
                        When(transaction_type__in=["credit", "transfer_credit"], then=F("amount")),
                        When(transaction_type__in=["debit", "transfer_debit"], then=-F("amount")),
                        default=0,
                        output_field=DecimalField(max_digits=14, decimal_places=2),
                    )
                )
            )
            .get("balance")
            or 0
        )
        return round(result, 2)

