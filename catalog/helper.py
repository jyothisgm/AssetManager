# ai/utils.py or transaction/utils.py
import re
from django.db import transaction
from catalog.models import Store


def _detect_source_from_sender(sender: str | None) -> Store | None:
    """
    Detect or create a Store based on the sender's email address.
    Uses existing Store records to find matches (exact or variant),
    otherwise creates a new Store with itself as its preferred store.
    """
    if not sender:
        return None

    sender = sender.lower().strip()

    # Extract domain and key name
    match = re.search(r"@([\w\.-]+)", sender)
    domain = match.group(1) if match else sender
    key = domain.split(".")[0]

    # Normalize possible store name
    candidate_name = key.replace("-", " ").replace("_", " ").strip().title()

    # Transaction-safe lookup or creation
    with transaction.atomic():
        # 1️⃣ Try to match preferred or variant store by name (case-insensitive)
        store = (
            Store.objects.filter(name__iexact=candidate_name).first()
            or Store.objects.filter(preferred__name__iexact=candidate_name).first()
        )

        # 2️⃣ If not found, create a new store
        if not store:
            store = Store.objects.create(name=candidate_name)
            # newly created store prefers itself
            store.preferred = store
            store.save(update_fields=["preferred"])

    return store
