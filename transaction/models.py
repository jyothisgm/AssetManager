from decimal import Decimal, ROUND_HALF_UP
from django.db import models
from django.utils import timezone
from account.models import Account
from common.models import Unit
from catalog.models import Currency, ExchangeRateRecord, Store, Product, PurchaseCategory
import uuid
from user.models import Attachment, BaseUserModel
from django.db.models import Sum, Case, When, F, Q, DecimalField, FloatField
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
        ("transfer_credit", "Transfer IN"),
        ("transfer_debit", "Transfer OUT"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    transaction_type = models.CharField(max_length=16, choices=TRANSACTION_TYPES)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateTimeField(default=timezone.now)
    description = models.CharField(max_length=255, blank=True, null=True)
    totals_match = models.BooleanField(null=True, default=None)
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
            if self.id:
                # price is a line total already
                total = sum(Decimal(str(item.price)) for item in self.items.all())
                logger.debug(f"[{func_name}] Computed total from {self.items.count()} items: {total}")
                return total
            return '-'
        except Exception:
            logger.exception(f"[{func_name}] Error computing total_from_items for Transaction ID={self.id}")
            raise

    def update_total_match_status(self):
        totals = self.items.aggregate(
            total=Sum(
                F("price"),
                output_field=DecimalField(max_digits=20, decimal_places=2)
            )
        )
        items_total = totals.get("total") or Decimal("0.00")
        txn_amount = Decimal(str(self.amount or 0))
        has_items = self.items.exists()
        tolerance = Decimal("0.02")  # allow up to 2-cent rounding error

        # ✅ Adjust by exchange rate if applicable
        if has_items and self.exchange_rate_record and getattr(self.exchange_rate_record, "provider_rate", None):
            try:
                rate = Decimal(str(self.exchange_rate_record.provider_rate))
                if rate > 0:
                    txn_amount_old = txn_amount
                    txn_amount = (txn_amount / rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                    logger.info(
                        f"[Transaction.update_total_match_status] Transaction {self.id}: "
                        f"Adjusted items_total by provider_rate={txn_amount_old} / {rate} → {txn_amount}"
                    )
            except Exception as e:
                logger.warning(
                    f"[Transaction.update_total_match_status] Could not apply exchange rate for Transaction {self.id}: {e}",
                    exc_info=True,
                )

        if not has_items:
            new_status = None  # neutral: no items
            diff = None
        else:
            diff = abs(
                items_total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                - txn_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            )
            new_status = diff <= tolerance

            import math
            frac_txn, whole_txn = math.modf(txn_amount)
            if frac_txn == 0:
                _, whole_items = math.modf(items_total)
                new_status = whole_txn == whole_items or whole_txn == whole_items + 1

        if self.totals_match != new_status:
            self.totals_match = new_status
            self.save(update_fields=["totals_match"])
            logger.info(
                f"[Transaction.update_total_match_status] Transaction {self.id}: totals_match={new_status}, "
                f"has_items={has_items}, items_total={items_total}, amount={txn_amount}, diff={diff}"
            )


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
    price = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.product or 'Item'} ({self.quantity} {self.unit or ''}) - €{self.price}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        try:
            self.transaction.update_total_match_status()
            logger.debug(f"[TransactionItem.save] Updated total match for Transaction {self.transaction_id}")
        except Exception:
            logger.exception(f"[TransactionItem.save] Failed to update totals for Transaction {self.transaction_id}")

    def delete(self, *args, **kwargs):
        txn = self.transaction
        super().delete(*args, **kwargs)
        if txn:
            try:
                txn.update_total_match_status()
                logger.debug(f"[TransactionItem.delete] Updated total match for Transaction {txn.id}")
            except Exception:
                logger.exception(f"[TransactionItem.delete] Failed to update totals for Transaction {txn.id}")


from django.db.models.signals import post_save
from django.dispatch import receiver

@receiver(post_save, sender=Transaction)
def update_transaction_total_match_on_save(sender, instance, created, **kwargs):
    """
    Automatically recalculate totals_match whenever a Transaction is saved.
    """
    try:
        # Avoid recursion if update_total_match_status() itself triggered the save
        if not kwargs.get("update_fields") or "totals_match" not in kwargs.get("update_fields", []):
            instance.update_total_match_status()
            logger.debug(
                f"[post_save] Updated totals_match for Transaction ID={instance.id} "
                f"(created={created})"
            )
    except Exception as e:
        logger.exception(
            f"[post_save] Error updating totals_match for Transaction ID={instance.id}: {e}"
        )
