from django.db import models
from django.utils import timezone
from account.models import Account
from common.models import TimeStampedModel, Unit
from catalog.models import Currency, ExchangeRateRecord, Store, Product, Brand, PurchaseCategory
import uuid


class Transaction(TimeStampedModel):
    TRANSACTION_TYPES = [
        ("debit", "Debit"),
        ("credit", "Credit"),
        ("transfer_credit", "Transfer_Credit"),
        ("transfer_debit", "Transfer_Debit"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction_type = models.CharField(max_length=16, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateTimeField(default=timezone.now)
    description = models.CharField(max_length=255, blank=True, null=True)
    processed = models.BooleanField(default=False)
    currency = models.ForeignKey(Currency, on_delete=models.PROTECT, related_name="transactions", null=True, blank=True)
    
    # For transfers
    linked_transaction = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="reverse_transfer"
    )

    account = models.ForeignKey(
        Account,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )

    category = models.ForeignKey(
        PurchaseCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )

    store = models.ForeignKey(
        Store,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
    )

    attachment = models.FileField(
        upload_to="transactions/attachments/",
        blank=True,
        null=True,
        help_text="Upload a receipt, invoice, or any related file"
    )

    notes = models.TextField(blank=True, null=True)
    
    exchange_rate_record = models.ForeignKey(
        ExchangeRateRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Exchange rate details for this transfer (if applicable)"
    )
    
    fee = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fee_for_transactions",
        help_text="Link to fee transaction associated with this transaction"
    )


    # ✅ Generic reverse link (Django auto-creates)
    # You can now access via `transaction.attachments.all()`

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.amount} ({self.date.date()})"

    @property
    def total_from_items(self):
        return sum(item.price for item in self.items.all())

    def reconcile_amount(self):
        total = self.total_from_items
        if total and total != self.amount:
            self.amount = total
            self.save(update_fields=["amount"])



class TransactionItem(TimeStampedModel):
    transaction = models.ForeignKey(
        Transaction,
        related_name="items",
        on_delete=models.CASCADE,
    )

    product = models.ForeignKey(
        Product, related_name="transaction_items", on_delete=models.SET_NULL, null=True, blank=True
    )

    quantity = models.FloatField(default=1)
    unit = models.ForeignKey(Unit, on_delete=models.SET_NULL, null=True, blank=True)
    price = models.FloatField(default=0)

    def __str__(self):
        return f"{self.product or 'Item'} ({self.quantity} {self.unit or ''}) - €{self.price}"
