# account/models.py
from django.db import models
from django.db.models import Sum, Case, When, F, DecimalField, Q
from catalog.models import Institution, Currency
from common.models import TimeStampedModel
from user.models import BaseUserModel
from common.logging_config import logger


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
    account_number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Account number, card number, or other identifier (last 4-6 digits for privacy).",
    )
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
        help_text="Currency of this account's balance.",
    )
    is_active = models.BooleanField(default=True)
    
    class Meta:
        # Ensure unique account number per user (if provided)
        constraints = [
            models.UniqueConstraint(
                fields=["created_by", "account_number"],
                condition=models.Q(account_number__isnull=False) & ~models.Q(account_number=""),
                name="unique_account_number_per_user",
            ),
        ]

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

        logger.debug(f"[account.models] Computing balance for account '{self.name}' ({self.id})")

        try:
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
            rounded_balance = round(result, 2)
            logger.debug(
                f"[account.models] Computed balance for '{self.name}' = {rounded_balance} {self.currency.code if self.currency else ''}"
            )
            return rounded_balance

        except Exception as e:
            logger.exception(f"[account.models] Failed to compute balance for '{self.name}'")
            return 0


class Card(BaseUserModel):
    """
    Represents a debit or credit card linked to an Account.
    One account can have multiple cards.
    """
    CARD_TYPES = [
        ("debit", "Debit Card"),
        ("credit", "Credit Card"),
    ]

    account = models.ForeignKey(
        Account,
        on_delete=models.CASCADE,
        related_name="cards",
        help_text="The account this card is linked to.",
    )
    card_number = models.CharField(
        max_length=6,
        help_text="Last 4-6 digits of the card number for identification.",
    )
    card_type = models.CharField(
        max_length=10,
        choices=CARD_TYPES,
        default="debit",
        help_text="Type of card (debit or credit).",
    )
    name = models.CharField(
        max_length=100,
        blank=True,
        help_text="Optional name for the card (e.g., 'Primary Debit Card', 'Travel Card').",
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Whether this card is currently active.",
    )

    class Meta:
        # Ensure unique card number per account
        constraints = [
            models.UniqueConstraint(
                fields=["account", "card_number"],
                name="unique_card_number_per_account",
            ),
        ]
        ordering = ["-is_active", "card_type", "card_number"]

    def __str__(self):
        card_name = self.name or f"{self.get_card_type_display()}"
        account_name = self.account.name if self.account else "Unknown"
        return f"{account_name} - {card_name} (****{self.card_number})"

    @property
    def display_name(self):
        """Returns a display-friendly name for the card."""
        if self.name:
            return f"{self.name} (****{self.card_number})"
        return f"{self.get_card_type_display()} (****{self.card_number})"
