import asyncio
import concurrent.futures
import json
import re
from unicodedata import category

from asgiref.sync import sync_to_async
from base64 import urlsafe_b64decode
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from typing import List, Dict, Any
from datetime import datetime, timedelta
from chromadb import Client
from chromadb.config import Settings

from account.models import Account, AccountType, Card
from async_tasks.threading import get_existing_thread, run_async_in_thread
from async_tasks.utils import EMAIL_JOB_LOG_DIR, _log_batch_results, _read_email_ids_from_log, _update_job_status
from catalog.models import Institution, Product, PurchaseCategory, Store
from common.logging_config import logger
from ai.utils import (
    analyze_email_batch_with_llm,
    detect_currency_with_llm,
    fetch_total_emails,
    get_embedding,
    get_llm_for_user,
    parse_transactions_with_llm,
    suggest_account_details_with_llm,
)
from catalog.helper import _detect_source_from_sender
from common.models import Currency
from googleapiclient.errors import HttpError
from user.models import EmailSyncJob
from user.utils import get_gmail_service
from transaction.models import EmailTransactionMap
from transaction.helpers import create_transaction_from_llm_tx
from transaction.utils import link_email_to_transaction


BATCH_SIZE = 1000


def _get_or_create_institution_from_source(source_label: str):
    """
    Resolve an Institution based on a source/store label.
    Ensures we reuse an existing institution before attempting to create one.
    """
    normalized = (source_label or "").strip()
    if not normalized:
        normalized = "Unknown Institution"
    normalized = normalized.title()
    short_name = normalized[:50]

    existing = Institution.objects.filter(short_name__iexact=short_name).first()
    if existing:
        return existing

    existing = Institution.objects.filter(name__iexact=normalized).first()
    if existing:
        return existing

    return Institution.objects.create(name=normalized, short_name=short_name, type="other")


def _get_or_create_card(account, card_number: str, card_type: str = "debit", card_name: str = None):
    """
    Get or create a Card linked to an Account.
    Returns the Card instance.
    """
    if not account or not card_number:
        return None
    
    # Normalize card number to last 4-6 digits
    card_number = str(card_number).strip()
    if len(card_number) > 6:
        card_number = card_number[-6:]
    elif len(card_number) < 4:
        return None
    
    # Try to find existing card
    card = Card.objects.filter(account=account, card_number=card_number).first()
    if card:
        return card
    
    # Create new card
    try:
        card = Card.objects.create(
            created_by=account.created_by,
            account=account,
            card_number=card_number,
            card_type=card_type,
            name=card_name or "",
            is_active=True,
        )
        logger.info(f"[Card] Created new card {card.display_name} for account {account.name}")
        return card
    except Exception as e:
        logger.warning(f"[Card] Error creating card {card_number} for account {account.name}: {e}")
        return None

# ------------------------------------------------------
# PHASE 1 — Fetch phase (quick)
# ------------------------------------------------------
async def _run_fetch_phase(job, service):
    total_unique = await asyncio.to_thread(fetch_total_emails, service)
    await _update_job_status(job, status="fetching", total_emails=total_unique, last_tx_timestamp=timezone.now())
    logger.info(f"[EmailSyncJob] 📬 Total Gmail messages for {job.gmail_account.email_address}: {total_unique}")
    return total_unique


# ------------------------------------------------------
# PHASE 2 — Analyse phase (resumable batch)
# ------------------------------------------------------
async def _run_analyse_phase(job, service, llm):
    user = job.created_by
    total_unique = job.total_emails or await _run_fetch_phase(job, service)
    await _update_job_status(job, status="analysing")
    potential_ids = await _analyze_all_batches(job, user, service, llm, total_unique)
    await _update_job_status(job, status="parsing")
    logger.info(f"[EmailSyncJob] 🔍 Phase 2 complete — {len(potential_ids)} potential tx emails found.")
    return potential_ids

async def _analyze_all_batches(job, user, service, llm, total_unique):
    """Iterate through Gmail in batches and analyze via LLM with resumability."""
    analysed_total = job.analysed_count or 0
    batch_no = (analysed_total // BATCH_SIZE) + 1 if analysed_total else 1
    potential_email_ids = set(json.loads(job.partial_results or "[]"))
    next_page_token = job.next_page_token or None

    logger.info(f"[EmailSyncJob] Resuming from batch {batch_no}, analysed={analysed_total}, potential_tx={len(potential_email_ids)}")

    while True:
        try:
            res = await asyncio.to_thread(_fetch_batch_emails, service, next_page_token)
            emails, next_page_token = res["emails"], res["next_token"]
            if not emails:
                break

            possible_tx = await asyncio.to_thread(analyze_email_batch_with_llm, llm, emails)
            await _log_batch_results(job, batch_no, analysed_total, total_unique, possible_tx, emails)

            ids = [t["email_id"] for t in possible_tx if "email_id" in t]
            potential_email_ids.update(ids)
            analysed_total += len(emails)

            # Persist intermediate progress
            await _update_job_status(
                job,
                analysed_count=analysed_total,
                potential_tx_count=len(potential_email_ids),
                next_page_token=next_page_token,
                partial_results=json.dumps(list(potential_email_ids)),
            )

            batch_no += 1
            if not next_page_token:
                break

        except Exception as e:
            logger.exception(f"[EmailSyncJob] Error in batch {batch_no}, will resume later: {e}")
            await _update_job_status(
                job,
                status="paused",
                next_page_token=next_page_token,
                partial_results=json.dumps(list(potential_email_ids)),
            )
            raise  # Re-raise to stop outer flow gracefully

    # Cleanup after full completion
    await _update_job_status(
        job,
        next_page_token=None,
        partial_results=json.dumps(list(potential_email_ids)),
    )
    return list(potential_email_ids)

# ------------------------------------------------------
# PHASE 3 — Parse phase (resume only from log file)
# ------------------------------------------------------
# --- Initialize persistent Chroma once ---

CHROMA_DIR = "chroma_db"
chroma_client = Client(Settings(persist_directory=CHROMA_DIR))
chroma_collection = chroma_client.get_or_create_collection(name="email_embeddings")


async def _run_parse_phase(job, service, llm):
    """
    Parse transactions strictly from the log file (oldest→newest),
    resuming automatically from the last email already linked in EmailTransactionMap.
    Also generates and stores embeddings for possible transactions in Chroma.
    """
    user = job.created_by
    await _update_job_status(job, status="parsing")

    # 1️⃣ Get all email IDs (oldest→newest) from the log
    email_ids = await _read_email_ids_from_log(job.id)
    if not email_ids:
        logger.warning(f"[EmailSyncJob] No email IDs found in log for job_id={job.id}")
        await _update_job_status(job, status="done")
        return

    # 2️⃣ Find already parsed emails for this job
    existing_ids = await sync_to_async(
        lambda: set(
            EmailTransactionMap.objects.filter(job=job)
            .values_list("email_id", flat=True)
        )
    )()
    remaining_ids = [eid for eid in email_ids if eid not in existing_ids]
    logger.info(
        f"[EmailSyncJob] {len(remaining_ids)} unparsed emails remain "
        f"(already parsed: {len(existing_ids)})"
    )

    if not remaining_ids:
        await _update_job_status(job, status="done")
        return

    # 3️⃣ Process remaining emails in batches (oldest first)
    batch_size = 50
    parsed_total = 0

    for start in range(0, len(remaining_ids), batch_size):
        batch_ids = remaining_ids[start:start + batch_size]

        # fetch the actual Gmail email metadata/bodies
        emails = await asyncio.to_thread(_fetch_filtered_emails, service, set(batch_ids))

        # parse transactions in each email (your existing logic)
        await _parse_transactions_in_depth(user.id, emails, llm, job)

        # 🧠 Generate embeddings for each parsed email and store in Chroma
        for email in emails:
            try:
                subject = email.get("subject", "")
                snippet = email.get("snippet", "")
                text = f"{subject}\n\n{snippet}".strip()
                if not text:
                    continue

                # compute embedding safely in a thread
                embedding = await asyncio.to_thread(get_embedding, text)
                if not embedding:
                    continue

                store_match = await sync_to_async(_detect_source_from_sender)(email.get("from", ""))
                source = email.get("source") or (store_match.name if store_match else None)

                metadata = {
                    "source": source,
                    "subject": subject,
                    "snippet": snippet,
                    "email_id": email["id"],
                    "job_id": job.id,
                }

                # ✅ Chroma add must also be run in a thread to avoid async conflict
                await asyncio.to_thread(
                    lambda: chroma_collection.add(
                        ids=[email["id"]],
                        embeddings=[embedding],
                        metadatas=[metadata],
                    )
                )

            except Exception as e:
                logger.error(f"[EmailSyncJob] Failed to store embedding for email={email.get('id')}: {e}")

        parsed_total += len(batch_ids)

        await _update_job_status(
            job,
            parsed_count=(job.parsed_count or 0) + parsed_total,
        )
        
        logger.info(
            f"[EmailSyncJob] ✅ Parsed batch {start//batch_size + 1} "
            f"({len(batch_ids)} emails). Total parsed so far: {parsed_total}"
        )

    pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
    if pending:
        logger.debug(f"[EmailSyncJob] Waiting for {len(pending)} tasks before shutdown")
        await asyncio.gather(*pending, return_exceptions=True)

    try:
        await asyncio.to_thread(lambda: chroma_collection.persist())
    except AttributeError:
        logger.debug("[EmailSyncJob] Chroma client does not support persist(); skipping.")
    logger.info(f"[EmailSyncJob] 🎯 Completed parse phase for job={job.id}")


def _fetch_batch_emails(service, page_token=None) -> Dict[str, Any]:
    """Fetch a batch of emails with metadata only."""
    res = service.users().messages().list(
        userId="me", maxResults=BATCH_SIZE, pageToken=page_token
    ).execute()

    messages_meta = res.get("messages", [])
    next_token = res.get("nextPageToken")
    emails = []

    for m in messages_meta:
        msg = service.users().messages().get(
            userId="me",
            id=m["id"],
            format="metadata",
            metadataHeaders=["Subject", "From"],
        ).execute()

        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        ts_ms = int(msg.get("internalDate", 0))
        ts_str = timezone.datetime.fromtimestamp(ts_ms / 1000).strftime("%Y-%m-%d %H:%M:%S")

        emails.append(
            {
                "id": msg.get("id"),
                "subject": headers.get("subject", ""),
                "from": headers.get("from", ""),
                "snippet": msg.get("snippet", ""),
                "timestamp": ts_str,
            }
        )

    return {"emails": emails, "next_token": next_token}


def _fetch_filtered_emails(service, ids: set) -> List[Dict[str, Any]]:
    """Fetch full metadata + body + attachments for selected email IDs."""
    results = []
    for eid in ids:
        try:
            msg = service.users().messages().get(
                userId="me", id=eid, format="full"
            ).execute()
        except HttpError as e:
            # Handle 404 (email deleted) or other HTTP errors gracefully
            if e.resp.status == 404:
                logger.warning(
                    "[EmailSyncJob] Email %s not found (may have been deleted), skipping",
                    eid,
                )
            else:
                logger.warning(
                    "[EmailSyncJob] HTTP error %s when fetching email %s: %s, skipping",
                    e.resp.status,
                    eid,
                    str(e),
                )
            continue
        except Exception as e:
            # Handle any other unexpected errors
            logger.warning(
                "[EmailSyncJob] Unexpected error fetching email %s: %s, skipping",
                eid,
                str(e),
            )
            continue

        headers = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
        subject = headers.get("subject", "")
        sender = headers.get("from", "")
        body_text = ""
        timestamp = None
        
        if "internalDate" in msg:
            try:
                internal_ts_raw = msg.get("internalDate")
                timestamp = datetime.fromtimestamp(
                    int(internal_ts_raw) / 1000,
                    tz=timezone.get_current_timezone(),
                )
            except Exception as e:
                timestamp = None
                logger.warning("[EmailSyncJob] Failed to parse internalDate for email=%s: %s", eid, e)

        # fallback to Date header
        if not timestamp and "date" in headers:
            try:
                timestamp = datetime.strptime(headers["date"], "%a, %d %b %Y %H:%M:%S %z")
            except Exception:
                timestamp = None

        # Extract plain/text or HTML body
        def extract_parts(parts):
            text = ""
            for p in parts:
                if p.get("mimeType") == "text/plain" and p.get("body", {}).get("data"):
                    text += urlsafe_b64decode(p["body"]["data"]).decode("utf-8", errors="ignore")
                elif p.get("mimeType") == "text/html" and not text and p.get("body", {}).get("data"):
                    text += urlsafe_b64decode(p["body"]["data"]).decode("utf-8", errors="ignore")
                elif "parts" in p:
                    text += extract_parts(p["parts"])
            return text

        if "parts" in msg.get("payload", {}):
            body_text = extract_parts(msg["payload"]["parts"])
        else:
            data = msg.get("payload", {}).get("body", {}).get("data")
            if data:
                body_text = urlsafe_b64decode(data).decode("utf-8", errors="ignore")

        # Extract attachments (metadata only for now)
        attachments = []
        for p in msg.get("payload", {}).get("parts", []):
            if p.get("filename") and "attachmentId" in p.get("body", {}):
                attachments.append({
                    "filename": p["filename"],
                    "attachment_id": p["body"]["attachmentId"],
                })
        if timestamp and timezone.is_naive(timestamp):
            timestamp = timezone.make_aware(timestamp, timezone.get_current_timezone())
        results.append({
            "id": eid,
            "from": sender,
            "subject": subject,
            "body": body_text,
            "attachments": attachments,
            "timestamp": timestamp,
        })
    return results


async def _parse_transactions_in_depth(user_id: int, emails, llm, job=None):
    """
    Parses transactions from Gmail emails (body + attachments),
    resuming automatically if the job was stopped mid-way.
    """
    User = get_user_model()
    user = await sync_to_async(User.objects.get)(pk=user_id)

    logger.info(f"[EmailSyncJob] Parsing {len(emails)} emails for user={user_id} (resumable)")

    existing_ids = await sync_to_async(
        lambda: set(
            EmailTransactionMap.objects.filter(job=job).values_list("email_id", flat=True)
        )
    )()

    to_process = [e for e in emails if e["id"] not in existing_ids]
    logger.info(f"[EmailSyncJob] {len(to_process)} emails pending for parsing")

    parsed_count = 0
    for idx, email in enumerate(to_process, start=1):
        try:
            existing_data = await asyncio.to_thread(lambda: {
                "accounts": list(Account.objects.filter(created_by=user).values_list("name", flat=True)),
                "stores": list(Store.objects.all().values_list("name", flat=True)),
                "categories": list(PurchaseCategory.objects.all().values_list("name", flat=True)),
                "products": list(Product.objects.all().values_list("name", flat=True)),
                "institutions": list(Institution.objects.all().values_list("name", flat=True)),
                "account_types":list(AccountType.objects.all().values_list("name", flat=True)),
                "currencies": list(Currency.objects.all().values_list("code", flat=True)),
            })
            txs = parse_transactions_with_llm(
                llm,
                email,
                existing_accounts=existing_data["accounts"],
                existing_stores=existing_data["stores"],
                existing_categories=existing_data["categories"],
                existing_products=existing_data["products"],
                existing_institutions=existing_data["institutions"],
                existing_account_types=existing_data["account_types"],
                existing_currencies=existing_data["currencies"],
            )

            if not txs:
                continue

            # 🔹 Detect currency for this email using dedicated LLM call
            currency_detection = await asyncio.to_thread(
                detect_currency_with_llm,
                llm,
                email,
                existing_data["currencies"],
            )
            detected_currency = currency_detection.get("currency")
            currency_confidence = currency_detection.get("confidence", "low")
            
            if detected_currency:
                logger.info(
                    "[EmailSyncJob] Currency detected: %s (confidence=%s) for email=%s",
                    detected_currency,
                    currency_confidence,
                    email.get("id"),
                )

            email_ts = email.get("timestamp")
            if isinstance(email_ts, str):
                parsed_ts = parse_datetime(email_ts)
                if not parsed_ts:
                    try:
                        parsed_ts = datetime.fromisoformat(email_ts.replace("Z", "+00:00"))
                    except Exception:
                        parsed_ts = None
                email_ts = parsed_ts
            if email_ts and timezone.is_naive(email_ts):
                email_ts = timezone.make_aware(email_ts, timezone.get_current_timezone())

            for tx in txs:
                if email_ts:
                    tx["email_timestamp"] = email_ts.isoformat()
                    tx["_email_timestamp_dt"] = email_ts
                llm_date_raw = tx.get("date")
                llm_date = None
                if llm_date_raw:
                    cleaned = llm_date_raw.strip()
                    parsed_llm = parse_datetime(cleaned)
                    if not parsed_llm:
                        try:
                            parsed_llm = datetime.fromisoformat(cleaned.replace("Z", "+00:00"))
                        except Exception:
                            parsed_llm = None
                    llm_date = parsed_llm
                    if llm_date and timezone.is_naive(llm_date):
                        llm_date = timezone.make_aware(llm_date, timezone.get_current_timezone())

                if email_ts:
                    if not llm_date:
                        tx["date"] = email_ts.isoformat()
                    else:
                        if abs(email_ts - llm_date) > timedelta(days=31):
                            tx["date"] = email_ts.isoformat()
                            tx.setdefault("needs_review", True)
                        else:
                            tx["date"] = llm_date.isoformat()
                elif llm_date:
                    tx["date"] = llm_date.isoformat()

                # 🔹 Override currency with detected currency if available and confident
                if detected_currency and currency_confidence in ("high", "medium"):
                    tx["currency"] = detected_currency
                    logger.debug(
                        "[EmailSyncJob] Using detected currency %s (confidence=%s) for tx=%s",
                        detected_currency,
                        currency_confidence,
                        tx.get("description", "")[:50],
                    )
                elif detected_currency and currency_confidence == "low":
                    # Use detected currency as fallback if LLM didn't provide one
                    if not tx.get("currency"):
                        tx["currency"] = detected_currency
                        logger.debug(
                            "[EmailSyncJob] Using low-confidence detected currency %s as fallback for tx=%s",
                            detected_currency,
                            tx.get("description", "")[:50],
                        )

                tx_type = (tx.get("transaction_type") or "").lower()
                if tx_type not in ["debit", "credit", "transfer_debit", "transfer_credit"]:
                    tx["transaction_type"] = (
                        "debit" if "purchase" in tx.get("description", "").lower() else "credit"
                    )
                
                # Extract card number if present (for debit/credit card transactions)
                card_number = tx.get("card_number")
                if card_number:
                    card_number = str(card_number).strip()
                    # Extract last 4-6 digits if full number is provided
                    if len(card_number) > 6:
                        card_number = card_number[-6:]
                    elif len(card_number) < 4:
                        card_number = None
                
                account_name = (tx.get("account") or "").strip() or None
                account = None
                
                # First, try to match by Card.card_number (if present)
                card = None
                if card_number:
                    card = await sync_to_async(
                        lambda: Card.objects.filter(
                            created_by=user,
                            card_number=card_number
                        ).select_related("account").first()
                    )()
                    if card and card.account:
                        account = card.account
                        logger.info(f"[EmailSyncJob] Matched account via Card {card.display_name}: {account.name}")
                
                # If not found via Card, try to match Account by account_number
                if not account and card_number:
                    account = await sync_to_async(
                        lambda: Account.objects.filter(
                            created_by=user, 
                            account_number=card_number
                        ).first()
                    )()
                    if account:
                        logger.info(f"[EmailSyncJob] Matched account by account_number {card_number}: {account.name}")
                
                # If not found by card_number, try to match by name
                if not account and account_name:
                    account = await sync_to_async(
                        lambda: Account.objects.filter(created_by=user, name__iexact=account_name).first()
                    )()
                    # If account found by name but has no account_number, update it with card_number
                    if account and card_number and not account.account_number:
                        account.account_number = card_number
                        await sync_to_async(account.save)()
                        logger.info(f"[EmailSyncJob] Updated account {account.name} with account_number {card_number}")

                if not account:
                    # Use LLM to suggest account metadata
                    account_suggestion = {}
                    if llm:
                        account_suggestion = await asyncio.to_thread(
                            suggest_account_details_with_llm,
                            llm,
                            tx,
                            existing_data["account_types"],
                            existing_data["currencies"],
                            existing_data["institutions"],
                            email_timestamp=email_ts.isoformat() if email_ts else None,
                        )

                    suggested_account_type = (account_suggestion.get("account_type") or "").strip()
                    suggested_currency_code = (account_suggestion.get("currency") or "").strip()
                    suggested_institution = (account_suggestion.get("institution") or "").strip()
                    suggested_account_name = (account_suggestion.get("account_name") or "").strip()
                    suggested_account_number = account_suggestion.get("account_number")
                    
                    # Use normalized account name from suggestion if available, otherwise use original
                    new_name = suggested_account_name or account_name or "Unknown Account"
                    # Use account_number from suggestion if available, otherwise use card_number from transaction
                    final_account_number = suggested_account_number or card_number
                    if final_account_number:
                        final_account_number = str(final_account_number).strip()
                        # Extract last 4-6 digits if full number is provided
                        if len(final_account_number) > 6:
                            final_account_number = final_account_number[-6:]
                        elif len(final_account_number) < 4:
                            final_account_number = None
                    currency_code = suggested_currency_code or (tx.get("currency") or "")

                    # 🔹 Fetch account_type (LLM suggestion first, fallback to Personal)
                    def resolve_account_type():
                        if suggested_account_type:
                            match = AccountType.objects.filter(name__iexact=suggested_account_type).first()
                            if match:
                                return match
                        return (
                            AccountType.objects.filter(name__iexact="Personal").first()
                            or AccountType.objects.first()
                        )

                    account_type_obj = await sync_to_async(resolve_account_type)()

                    # 🔹 Fetch currency (LLM suggestion or fallback)
                    def resolve_currency():
                        code = currency_code.strip().upper()
                        if code:
                            curr = Currency.objects.filter(code__iexact=code).first()
                            if curr:
                                return curr
                        return (
                            Currency.objects.filter(code__in=["INR", "USD"]).first()
                            or Currency.objects.first()
                        )

                    currency_obj = await sync_to_async(resolve_currency)()

                    # 🔹 Choose institution (LLM suggestion overrides detected source)
                    store_match = await sync_to_async(_detect_source_from_sender)(email.get("from", ""))
                    source_name = (store_match.name if store_match else None) or "Unknown Institution"
                    institution_name = suggested_institution or source_name
                    institution = await sync_to_async(_get_or_create_institution_from_source)(institution_name)

                    if account_suggestion.get("needs_review"):
                        tx["needs_review"] = True

                    # 🔹 Create new Account with AI-guided defaults
                    # Include account_number (card_number) if available
                    account = await sync_to_async(
                        lambda: Account.objects.create(
                            created_by=user,
                            name=new_name,
                            account_number=final_account_number if final_account_number else None,
                            account_type=account_type_obj,
                            currency=currency_obj,
                            institution=institution,
                        )
                    )()

                    logger.info(
                        f"[TxCreate] Created new account '{new_name}' "
                        f"({currency_obj.code if currency_obj else 'N/A'}) "
                        f"{'with account_number ' + final_account_number if final_account_number else ''} "
                        f"for user={user.id}"
                    )

                # 🔹 Create or find Card if card_number is present and we don't already have one
                if card_number and account and not card:
                    # Determine card type based on transaction type
                    card_type = "credit" if tx_type in ["credit", "transfer_credit"] else "debit"
                    card = await sync_to_async(_get_or_create_card)(
                        account, 
                        card_number, 
                        card_type=card_type,
                        card_name=None,  # Can be enhanced later with LLM suggestions
                    )
                    if card:
                        logger.info(f"[EmailSyncJob] Created/linked card {card.display_name} to account {account.name}")

                txn, status = await asyncio.to_thread(create_transaction_from_llm_tx, user, tx, account, llm, card=card)
                if txn:
                    await asyncio.to_thread(
                        link_email_to_transaction,
                        txn,
                        job.gmail_account if job else None,
                        email,
                        job,
                        confidence=tx.get("confidence", 1.0),
                        needs_review=tx.get("needs_review", False),
                    )

            parsed_count += 1
            if parsed_count % 5 == 0:
                await _update_job_status(job, parsed_count=parsed_count)

            logger.info(f"[EmailSyncJob] ✅ Parsed {idx}/{len(to_process)} — {email['subject'][:60]}")

        except Exception as e:
            logger.exception(f"[EmailSyncJob] ⚠️ Error parsing email {email.get('id')}: {e}")
            await _update_job_status(job, status="paused")
            break

    logger.info(f"[EmailSyncJob] 🎯 Completed parsing stage for job={job.id}, parsed={parsed_count}")


async def extract_all_accounts_from_emails(
    user_id: int, 
    service, 
    llm, 
    job_id: int = None, 
    limit: int = None,
    status_updater=None,
    gmail_account_id: int = None,
):
    """
    Extract all unique accounts from emails by analyzing email content.
    Only processes emails saved in the email_jobs log file.
    Creates accounts in DB as they're found.
    Updates progress via status_updater callback.
    Returns a list of account dictionaries with suggested metadata.
    """
    User = get_user_model()
    user = await sync_to_async(User.objects.get)(pk=user_id)
    
    logger.info(f"[AccountExtraction] Starting account extraction for user={user_id}, job_id={job_id}")
    
    # Get job_id if not provided - use the latest job for the user
    if not job_id:
        latest_job = await sync_to_async(
            lambda: EmailSyncJob.objects.filter(created_by=user).order_by("-created_at").first()
        )()
        if latest_job:
            job_id = latest_job.id
            logger.info(f"[AccountExtraction] Using latest job_id={job_id}")
        else:
            logger.warning(f"[AccountExtraction] No email sync job found for user={user_id}")
            return []
    
    # Read email IDs from log file
    email_ids = await _read_email_ids_from_log(job_id)
    if not email_ids:
        logger.warning(f"[AccountExtraction] No email IDs found in log file for job_id={job_id}")
        return []
    
    logger.info(f"[AccountExtraction] Found {len(email_ids)} email IDs in log file")
    
    # Apply limit if specified
    if limit:
        email_ids = email_ids[:limit]
        logger.info(f"[AccountExtraction] Limited to {len(email_ids)} emails")
    
    # Get existing data for grounding
    existing_data = await asyncio.to_thread(lambda: {
        "account_types": list(AccountType.objects.all().values_list("name", flat=True)),
        "currencies": list(Currency.objects.all().values_list("code", flat=True)),
        "institutions": list(Institution.objects.all().values_list("name", flat=True)),
        "existing_accounts": list(Account.objects.filter(created_by=user).values_list("name", flat=True)),
    })
    
    # Process emails from log file
    all_accounts = set()
    account_details = {}  # account_name -> account info
    accounts_created = 0
    
    # Process emails in batches to avoid overwhelming the API
    batch_size = 50
    total_emails = len(email_ids)
    processed = 0
    
    def update_status():
        """Update status via callback if provided"""
        if status_updater:
            remaining = total_emails - processed
            progress = int((processed / total_emails * 100)) if total_emails > 0 else 0
            status_updater({
                "status": "running",
                "progress": progress,
                "total_emails": total_emails,
                "processed_emails": processed,
                "remaining_emails": remaining,
                "accounts_found": len(account_details),
                "accounts_created": accounts_created,
            })
    
    for i in range(0, total_emails, batch_size):
        batch_ids = set(email_ids[i:i + batch_size])
        try:
            # Fetch full emails for this batch
            full_emails = await asyncio.to_thread(_fetch_filtered_emails, service, batch_ids)
            
            for email in full_emails:
                try:
                    processed += 1
                    
                    # Parse transactions to extract account info
                    txs = parse_transactions_with_llm(
                        llm,
                        email,
                        existing_accounts=existing_data["existing_accounts"],
                        existing_stores=[],
                        existing_categories=[],
                        existing_products=[],
                        existing_institutions=existing_data["institutions"],
                        existing_account_types=existing_data["account_types"],
                        existing_currencies=existing_data["currencies"],
                    )
                    
                    # Extract account names from transactions
                    for tx in txs:
                        account_name = (tx.get("account") or "").strip()
                        if account_name:
                            all_accounts.add(account_name)
                            
                            # Get LLM suggestions for account details
                            if account_name not in account_details:
                                suggestion = await asyncio.to_thread(
                                    suggest_account_details_with_llm,
                                    llm,
                                    tx,
                                    existing_data["account_types"],
                                    existing_data["currencies"],
                                    existing_data["institutions"],
                                    email_timestamp=email.get("timestamp").isoformat() if email.get("timestamp") else None,
                                )
                                
                                # Detect currency from email
                                currency_detection = await asyncio.to_thread(
                                    detect_currency_with_llm,
                                    llm,
                                    email,
                                    existing_data["currencies"],
                                )
                                
                                # Detect institution from sender
                                store_match = await sync_to_async(_detect_source_from_sender)(email.get("from", ""))
                                
                                # Use normalized account name from LLM if available, otherwise use original
                                normalized_name = suggestion.get("account_name") or account_name
                                account_number = suggestion.get("account_number")
                                
                                account_info = {
                                    "name": normalized_name,
                                    "account_number": account_number,
                                    "account_type": suggestion.get("account_type"),
                                    "currency": currency_detection.get("currency") or suggestion.get("currency"),
                                    "institution": suggestion.get("institution") or (store_match.name if store_match else None),
                                    "email_sender": email.get("from", ""),
                                    "confidence": currency_detection.get("confidence", "low"),
                                    "needs_review": suggestion.get("needs_review", False),
                                }
                                # Use normalized name as key
                                account_details[normalized_name] = account_info
                                
                                # Create account in DB immediately
                                try:
                                    created = await sync_to_async(_create_account_from_info)(user, account_info, existing_data)
                                    if created:
                                        accounts_created += 1
                                        # Update existing_accounts list for next iterations
                                        existing_data["existing_accounts"].append(normalized_name)
                                except Exception as e:
                                    logger.warning(f"[AccountExtraction] Failed to create account {account_name}: {e}")
                    
                    # Update status after each email
                    update_status()
                
                except Exception as e:
                    logger.warning(f"[AccountExtraction] Error processing email {email.get('id', 'unknown')}: {e}")
                    processed += 1  # Still count as processed
                    update_status()
                    continue
            
            # Log progress
            if processed % 100 == 0:
                logger.info(f"[AccountExtraction] Processed {processed}/{total_emails} emails, found {len(account_details)} unique accounts, created {accounts_created}")
                
        except Exception as e:
            logger.exception(f"[AccountExtraction] Error in batch {i//batch_size + 1}: {e}")
            continue
    
    # Convert to list and sort
    accounts_list = list(account_details.values())
    accounts_list.sort(key=lambda x: x["name"])
    
    logger.info(f"[AccountExtraction] Completed: processed {processed}/{total_emails} emails, found {len(accounts_list)} unique accounts, created {accounts_created}")
    
    return accounts_list


def _create_account_from_info(user, account_info: Dict[str, Any], existing_data: Dict[str, Any]) -> bool:
    """
    Create an Account in the database from account_info.
    Matches accounts by account_number first, then by name.
    Returns True if account was created, False if it already existed.
    """
    account_name = account_info.get("name", "").strip()
    if not account_name:
        return False
    
    account_number = account_info.get("account_number")
    if account_number:
        account_number = str(account_number).strip()
        if not account_number:
            account_number = None
    
    # First, check if account exists by account_number (if provided)
    if account_number:
        existing_account = Account.objects.filter(
            created_by=user, 
            account_number=account_number
        ).first()
        if existing_account:
            logger.info(f"[AccountExtraction] Account with number {account_number} already exists: {existing_account.name}")
            return False
    
    # Then check if account exists by name (case-insensitive)
    existing_account = Account.objects.filter(
        created_by=user, 
        name__iexact=account_name
    ).first()
    if existing_account:
        # If account exists but doesn't have account_number, update it
        if account_number and not existing_account.account_number:
            existing_account.account_number = account_number
            existing_account.save()
            logger.info(f"[AccountExtraction] Updated account {account_name} with account_number {account_number}")
        return False
    
    # Get or find account_type
    account_type_name = account_info.get("account_type")
    account_type = None
    if account_type_name:
        account_type = AccountType.objects.filter(name__iexact=account_type_name).first()
    
    # If no account_type found, use a default (e.g., "Bank" or first available)
    if not account_type:
        account_type = AccountType.objects.filter(name__iexact="Bank").first()
        if not account_type:
            account_type = AccountType.objects.first()
    
    if not account_type:
        logger.warning(f"[AccountExtraction] No AccountType available, skipping account {account_name}")
        return False
    
    # Get currency
    currency_code = account_info.get("currency")
    currency = None
    if currency_code:
        currency = Currency.objects.filter(code__iexact=currency_code).first()
    
    # Get institution
    institution_name = account_info.get("institution")
    institution = None
    if institution_name:
        institution = Institution.objects.filter(name__iexact=institution_name).first()
    
    # Create account
    try:
        Account.objects.create(
            created_by=user,
            name=account_name,
            account_number=account_number,
            account_type=account_type,
            currency=currency,
            institution=institution,
            is_active=True,
        )
        logger.info(f"[AccountExtraction] Created account: {account_name}" + (f" (number: {account_number})" if account_number else ""))
        return True
    except Exception as e:
        logger.warning(f"[AccountExtraction] Error creating account {account_name}: {e}")
        return False


async def run_email_sync_phases(job):
    """Decide which phase to resume from."""
    status = job.status or "queued"
    logger.info(f"[EmailSyncJob] Resuming phase from status={status}")
    # Ensure Gmail + LLM ready
    user, gmail_account = job.created_by, job.gmail_account
    service = get_gmail_service(gmail_account.creds)
    llm = await get_llm_for_user(user.id)

    try:
        if job.status in ["queued", "fetching"]:
            await _run_fetch_phase(job, service)

        if job.status in ["analysing"]:
            await _run_analyse_phase(job, service, llm)

        if job.status in ["parsing"]:
            await _run_parse_phase(job, service, llm)

        if job.status in ["done"]:
            logger.info(f"[EmailSyncJob] ✅ Job {job.id} completed all phases.")
    except Exception as e:
        # Fail-safe: capture phase where it stopped
        logger.exception(f"[EmailSyncJob] ❌ Error during {status} phase for job_id={job.id}: {e}")
        await _update_job_status(job, status="paused")
        raise


def start_email_sync_job(job_id: int):
    """Start or resume an email sync job asynchronously inside a background thread."""
    async def run():
        job = await sync_to_async(EmailSyncJob.objects.select_related("created_by", "gmail_account").get)(pk=job_id)
        try:
            await run_email_sync_phases(job)
        except Exception as e:
            await _update_job_status(job, status="failed")
            logger.exception(f"[EmailSyncJob] ❌ Job {job_id} failed: {e}")
    run_async_in_thread(run, job_id, "EmailSyncJob")


def resume_or_start_email_sync_job(user, gmail_account):
    existing = EmailSyncJob.objects.filter(created_by=user, gmail_account=gmail_account).order_by("-created_at").first()
    if existing:
        # Check if thread is alive
        running_thread = get_existing_thread(existing.id)
        if running_thread and running_thread.is_alive():
            logger.info(f"[EmailSyncJob] Job {existing.id} is already running in thread {running_thread.name}")
            return existing, "already_running"

        # If job says running in DB but no live thread, resume it
        logger.warning(f"[EmailSyncJob] Job {existing.id} marked as {existing.status} but thread missing — restarting.")
        start_email_sync_job(existing.id)
        return existing, "restarted"

    # No active job found — start a new one
    new_job = EmailSyncJob.objects.create(created_by=user, gmail_account=gmail_account, status="queued")
    start_email_sync_job(new_job.id)
    return new_job, "started_new"


def extract_accounts_from_all_emails(user, gmail_account, job_id: int = None, limit: int = None, status_updater=None):
    """
    Synchronous wrapper to extract all accounts from emails.
    Only processes emails saved in the email_jobs log file.
    Creates accounts in DB as they're found.
    Updates progress via status_updater callback.
    Returns a list of account dictionaries with suggested metadata.
    
    Usage:
        def update_status(status):
            print(f"Progress: {status['progress']}%")
        
        accounts = extract_accounts_from_all_emails(user, gmail_account, job_id=1, limit=1000, status_updater=update_status)
        for account in accounts:
            print(f"{account['name']} - {account['currency']} - {account['institution']}")
    """
    async def run():
        service = get_gmail_service(gmail_account.creds)
        llm = await get_llm_for_user(user.id)
        return await extract_all_accounts_from_emails(
            user.id, 
            service, 
            llm, 
            job_id=job_id, 
            limit=limit,
            status_updater=status_updater,
            gmail_account_id=gmail_account.id,
        )
    
    # Run synchronously and return results
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're already in an async context, create a new event loop in a thread
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(asyncio.run, run())
                return future.result()
        else:
            return loop.run_until_complete(run())
    except RuntimeError:
        # No event loop, create a new one
        return asyncio.run(run())
