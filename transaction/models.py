from django.db import models
from django.utils import timezone
from account.models import Account
from common.models import Unit
from catalog.models import Currency, ExchangeRateRecord, Store, Product, PurchaseCategory
import uuid
from user.models import Attachment, BaseUserModel
from common.logging_config import logger
from django.conf import settings

import os
from datetime import datetime


def transaction_attachment_path(instance, filename):
    """
    Generates and ensures structured path for uploaded attachments.

    Example result:
        attachments/42_tony_example_com/transactions/purchase_receipt/20251015_142600_Jumbo.jpeg
    """
    # --- User info ---
    user_email = getattr(instance.created_by, "email", "unknown_user")
    user_pk = getattr(instance.created_by, "pk", None)
    safe_user = f"{user_pk}_" if user_pk else ""
    safe_user += user_email.replace("@", "_at_").replace(".", "_")

    # --- File info ---
    extension = filename.split(".")[-1]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # --- Document / Store info ---
    doc_type = getattr(instance, "type", "other")
    store_name = getattr(getattr(instance, "content_object", None), "store", None)
    preferred_store = getattr(store_name, "name", "unknown")

    # --- Custom filename ---
    custom_name = f"{timestamp}_{preferred_store}.{extension}"

    # --- Build relative + absolute paths ---
    relative_dir = os.path.join(safe_user, "transactions", doc_type)
    relative_path = os.path.join(relative_dir, custom_name)
    full_dir = os.path.join(settings.MEDIA_ROOT, "attachments", relative_dir)

    # --- Ensure directory exists ---
    os.makedirs(full_dir, exist_ok=True)

    return relative_path


class Transaction(BaseUserModel):
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
    currency = models.ForeignKey(
        Currency, on_delete=models.PROTECT, related_name="transactions", null=True, blank=True
    )

    linked_transaction = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="reverse_transfer"
    )

    account = models.ForeignKey(
        Account, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions"
    )

    category = models.ForeignKey(
        PurchaseCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions"
    )

    store = models.ForeignKey(
        Store, on_delete=models.SET_NULL, null=True, blank=True, related_name="transactions"
    )

    attachment = models.ForeignKey(
            Attachment,
            on_delete=models.SET_NULL,
            null=True,
            blank=True,
            related_name="transactions",
            help_text="Attachment linked to this transaction (e.g., receipt, invoice, bill).",
        )

    notes = models.TextField(blank=True, null=True)

    exchange_rate_record = models.ForeignKey(
        ExchangeRateRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Exchange rate details for this transfer (if applicable)",
    )

    fee = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fee_for_transactions",
        help_text="Link to fee transaction associated with this transaction",
    )

    def __str__(self):
        return f"{self.get_transaction_type_display()} {self.amount} ({self.date.date()})"

    @property
    def total_from_items(self):
        func_name = f"{self.__class__.__name__}.total_from_items"
        try:
            total = sum(item.price for item in self.items.all())
            logger.debug(f"[{func_name}] Computed total from {self.items.count()} items: {total}")
            return total
        except Exception as e:
            logger.exception(f"[{func_name}] Error computing total_from_items for Transaction ID={self.id}")
            raise e

    def reconcile_amount(self):
        func_name = f"{self.__class__.__name__}.reconcile_amount"
        try:
            total = self.total_from_items
            if total and total != self.amount:
                logger.info(f"[{func_name}] Reconciling transaction ID={self.id}: {self.amount} → {total}")
                self.amount = total
                self.save(update_fields=["amount"])
                logger.debug(f"[{func_name}] Updated transaction ID={self.id} with reconciled amount={self.amount}")
            else:
                logger.debug(f"[{func_name}] No reconciliation needed for Transaction ID={self.id}")
        except Exception as e:
            logger.exception(f"[{func_name}] Error during reconciliation for Transaction ID={self.id}")
            raise e


class TransactionItem(BaseUserModel):
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
    date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.product or 'Item'} ({self.quantity} {self.unit or ''}) - €{self.price}"

    def save(self, *args, **kwargs):
        func_name = f"{self.__class__.__name__}.save"
        try:
            logger.debug(
                f"[{func_name}] Saving TransactionItem (product={self.product}, price={self.price}, qty={self.quantity})"
            )
            super().save(*args, **kwargs)
            logger.debug(f"[{func_name}] TransactionItem saved successfully (ID={self.id})")
        except Exception as e:
            logger.exception(f"[{func_name}] Error saving TransactionItem (product={self.product})")
            raise e

    def delete(self, *args, **kwargs):
        func_name = f"{self.__class__.__name__}.delete"
        try:
            logger.info(f"[{func_name}] Deleting TransactionItem ID={self.id}")
            super().delete(*args, **kwargs)
            logger.debug(f"[{func_name}] TransactionItem ID={self.id} deleted successfully")
        except Exception as e:
            logger.exception(f"[{func_name}] Error deleting TransactionItem ID={self.id}")
            raise e
