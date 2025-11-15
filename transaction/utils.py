from datetime import timedelta
from decimal import Decimal
from transaction.models import EmailTransactionMap, Transaction
from common.logging_config import logger


def find_possible_duplicate(user, account, date, amount, description, tolerance=Decimal("1.00")):
    """
    Check for potential duplicate transactions within ±3 days of the given date.
    Matches by account, similar description, and similar amount.
    Returns the first matching transaction if found, else None.
    """
    try:
        start = date - timedelta(days=3)
        end = date + timedelta(days=3)
        qs = Transaction.objects.filter(
            created_by=user,
            account=account,
            date__range=(start, end),
            amount__gte=amount - tolerance,
            amount__lte=amount + tolerance,
            description__icontains=description[:30],
        )
        duplicate = qs.first()
        if duplicate:
            logger.info(
                f"[DuplicateCheck] Found possible duplicate Txn={duplicate.id} "
                f"({duplicate.amount} {duplicate.description[:40]}...) within ±3 days."
            )
        return duplicate
    except Exception:
        logger.exception("[DuplicateCheck] Error while checking duplicates")
        return None


def link_email_to_transaction(transaction, gmail_account, email_data, job=None, confidence=1.0, needs_review=False):
    """
    Safe helper to link a Transaction to an email (many-to-many).
    Avoids duplicates and logs for traceability.
    """
    try:
        obj, created = EmailTransactionMap.objects.get_or_create(
            transaction=transaction,
            gmail_account=gmail_account,
            email_id=email_data.get("id"),
            defaults={
                "email_subject": email_data.get("subject"),
                "email_from": email_data.get("from"),
                "email_timestamp": email_data.get("timestamp"),
                "job": job,
                "confidence": confidence,
                "needs_review": needs_review,
            },
        )
        if created:
            logger.info(f"[EmailTransactionMap] Linked Tx {transaction.id} ↔ Email {email_data.get('id')}")
        else:
            logger.debug(f"[EmailTransactionMap] Existing link reused for Tx {transaction.id}")
        return obj
    except Exception:
        logger.exception(f"[EmailTransactionMap] Failed linking Tx {transaction.id} ↔ Email {email_data.get('id')}")
        return None
