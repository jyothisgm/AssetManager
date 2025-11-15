from django.http import JsonResponse
from django.views import View
from django.contrib.auth import get_user_model
from account.models import Account
from user.models import GmailAccount, EmailSyncJob
from async_tasks.email_jobs import extract_accounts_from_all_emails
from async_tasks.threading import get_existing_thread, ACTIVE_JOB_THREADS
from async_tasks.utils import _read_email_ids_from_log
from common.logging_config import logger
import json
import asyncio
import threading

User = get_user_model()

# In-memory tracking of extraction results and jobs per Gmail account
EXTRACTION_RESULTS = {}  # gmail_account_id -> results
EXTRACTION_STATUS = {}  # gmail_account_id -> status
EXTRACTION_JOBS = {}  # gmail_account_id -> job_id


class AccountExtractionView(View):
    """
    View to:
    - GET: List all accounts + extraction status, and start/restart extraction if needed
    Only one extraction job per Gmail account.
    """

    def get(self, request, *args, **kwargs):
        """Return list of all accounts and extraction status. Start extraction if not running."""
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        # Get Gmail account (use first active one, or allow specifying in query params)
        gmail_account_id = request.GET.get("gmail_account_id")
        if gmail_account_id:
            gmail_account = GmailAccount.objects.filter(
                id=gmail_account_id, created_by=user, active=True
            ).first()
        else:
            gmail_account = GmailAccount.objects.filter(created_by=user, active=True).first()
        
        if not gmail_account:
            return JsonResponse(
                {"error": "No active Gmail account found"},
                status=400,
            )

        # Get all accounts for the user
        accounts = Account.objects.filter(created_by=user, is_deleted=False).select_related(
            "account_type", "currency", "institution"
        )
        
        accounts_data = []
        for account in accounts:
            accounts_data.append({
                "id": str(account.id),
                "name": account.name,
                "account_number": account.account_number if hasattr(account, "account_number") else None,
                "account_type": account.account_type.name if account.account_type else None,
                "currency": account.currency.code if account.currency else None,
                "institution": account.institution.name if account.institution else None,
                "is_active": account.is_active,
                "balance": float(account.computed_balance) if hasattr(account, "computed_balance") else 0.0,
                "created_at": account.created_at.isoformat() if account.created_at else None,
            })

        # Check extraction status for this Gmail account
        extraction_key = f"gmail_account_{gmail_account.id}"
        status = EXTRACTION_STATUS.get(extraction_key, {
            "status": "idle",
            "progress": 0,
            "total_emails": 0,
            "processed_emails": 0,
            "remaining_emails": 0,
            "accounts_found": 0,
            "accounts_created": 0,
        })
        
        # Check if thread is running for this Gmail account
        thread_id = f"AccountExtraction-{gmail_account.id}"
        thread = None
        for tid, t in ACTIVE_JOB_THREADS.items():
            if hasattr(t, "name") and t.name == thread_id:
                thread = t
                break
        
        # Determine current status
        is_running = thread and thread.is_alive() if thread else False
        current_status = status.get("status", "idle")
        
        if is_running:
            current_status = "running"
        elif current_status == "running" and not is_running:
            current_status = "completed"

        # Start or restart extraction if needed
        should_start = False
        action_taken = None
        
        if current_status in ("idle", "paused", "failed"):
            should_start = True
            action_taken = "started" if current_status == "idle" else "restarted"
        elif current_status == "running":
            action_taken = "already_running"
        elif current_status == "completed":
            action_taken = "completed"

        if should_start:
            # Get job_id and limit from query params
            job_id = request.GET.get("job_id")
            limit = request.GET.get("limit")
            if limit:
                try:
                    limit = int(limit)
                except:
                    limit = None

            # If job_id not provided, get the latest job for this Gmail account
            if not job_id:
                latest_job = EmailSyncJob.objects.filter(
                    created_by=user, gmail_account=gmail_account
                ).order_by("-created_at").first()
                if latest_job:
                    job_id = latest_job.id
                    logger.info(f"[AccountExtraction] Using latest job_id={job_id} for gmail_account={gmail_account.id}")
                else:
                    return JsonResponse({
                        "status": "error",
                        "error": "No email sync job found. Please run email sync first.",
                        "accounts": accounts_data,
                        "extraction": {
                            "status": "error",
                            "message": "No email sync job found",
                        },
                    }, status=400)

            # Get total emails from log file for progress tracking
            try:
                email_ids = asyncio.run(_read_email_ids_from_log(job_id))
                total_emails = len(email_ids)
                if limit:
                    total_emails = min(total_emails, limit)
            except Exception as e:
                logger.warning(f"[AccountExtraction] Could not read log file for job_id={job_id}: {e}")
                total_emails = 0

            # Update status
            EXTRACTION_STATUS[extraction_key] = {
                "status": "running",
                "progress": 0,
                "total_emails": total_emails,
                "processed_emails": 0,
                "remaining_emails": total_emails,
                "accounts_found": 0,
                "accounts_created": 0,
            }
            EXTRACTION_JOBS[extraction_key] = job_id

            # Status updater function to update progress in real-time
            def status_updater(update_data):
                """Update extraction status in real-time"""
                EXTRACTION_STATUS[extraction_key].update(update_data)

            # Start extraction in background
            def extraction_wrapper():
                nonlocal total_emails, job_id
                try:
                    logger.info(f"[AccountExtraction] Starting extraction for gmail_account={gmail_account.id}, job_id={job_id}")
                    results = extract_accounts_from_all_emails(
                        user, 
                        gmail_account, 
                        job_id=job_id, 
                        limit=limit,
                        status_updater=status_updater,
                    )
                    
                    # Store results
                    EXTRACTION_RESULTS[extraction_key] = results
                    final_status = EXTRACTION_STATUS.get(extraction_key, {})
                    EXTRACTION_STATUS[extraction_key] = {
                        "status": "completed",
                        "progress": 100,
                        "total_emails": total_emails,
                        "processed_emails": total_emails,
                        "remaining_emails": 0,
                        "accounts_found": len(results),
                        "accounts_created": final_status.get("accounts_created", 0),
                    }
                    logger.info(f"[AccountExtraction] Completed extraction for gmail_account={gmail_account.id}, found {len(results)} accounts")
                except Exception as e:
                    logger.exception(f"[AccountExtraction] Error during extraction for gmail_account={gmail_account.id}: {e}")
                    EXTRACTION_STATUS[extraction_key] = {
                        "status": "failed",
                        "progress": 0,
                        "error": str(e),
                    }

            thread = threading.Thread(target=extraction_wrapper, daemon=True, name=thread_id)
            thread.start()
            
            # Store thread reference
            ACTIVE_JOB_THREADS[f"extraction_{gmail_account.id}"] = thread
            current_status = "running"
            is_running = True

        # Get extraction results if available
        results = EXTRACTION_RESULTS.get(extraction_key, [])
        
        # Refresh status to get latest updates
        status = EXTRACTION_STATUS.get(extraction_key, {
            "status": "idle",
            "progress": 0,
            "total_emails": 0,
            "processed_emails": 0,
            "remaining_emails": 0,
            "accounts_found": 0,
            "accounts_created": 0,
        })
        
        # Update current_status based on refreshed status and thread state
        if is_running:
            current_status = "running"
        elif status.get("status") == "completed":
            current_status = "completed"
        elif status.get("status") == "failed":
            current_status = "failed"
        else:
            current_status = status.get("status", "idle")

        return JsonResponse({
            "status": "ok",
            "action": action_taken,
            "accounts": accounts_data,
            "extraction": {
                "status": current_status,
                "progress": status.get("progress", 0),
                "total_emails": status.get("total_emails", 0),
                "processed_emails": status.get("processed_emails", 0),
                "remaining_emails": status.get("remaining_emails", 0),
                "accounts_found": status.get("accounts_found", 0),
                "accounts_created": status.get("accounts_created", 0),
                "is_running": is_running,
                "gmail_account_id": gmail_account.id,
                "gmail_address": gmail_account.email_address,
            },
            "extraction_results": results,
        })
