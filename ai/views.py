from django.http import JsonResponse
from django.views import View

from common.logging_config import logger
from user.models import GmailAccount, EmailSyncJob
from async_tasks.email_jobs import resume_or_start_email_sync_job


class ScanAllEmailsView(View):
    """
    Start or resume one background sync task per active Gmail account.
    If a job already exists and is not finished, it continues/resumes it.
    """

    def get(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({"error": "Unauthorized"}, status=401)
        logger.info(f"[ScanAllEmails] Checking Gmail sync status for user_id={user.id}")
        mail_accounts = GmailAccount.objects.filter(created_by=user, active=True)
        if not mail_accounts.exists():
            return JsonResponse(
                {"status": "no_accounts", "message": "No active Gmail accounts connected."},
                status=400,
            )
        jobs_payload = []
        for mail_account in mail_accounts:
            job, action = resume_or_start_email_sync_job(user, mail_account)
            jobs_payload.append({
                "job_id": job.id,
                "gmail_account_id": mail_account.id,
                "gmail_address": mail_account.email_address,
                "status": job.status,
                "action": action,
            })
        return JsonResponse({"status": "ok", "user_id": user.id, "jobs": jobs_payload})

class EmailSyncStatusView(View):
    """
    Show all sync jobs for the current user, grouped per Gmail account.
    Also shows remaining analyse / parse counts.
    """
    def get(self, request, *args, **kwargs):
        user = request.user
        if not user.is_authenticated:
            return JsonResponse({"error": "Unauthorized"}, status=401)

        jobs = EmailSyncJob.objects.filter(created_by=user).select_related("gmail_account").order_by("-created_at")
        if not jobs.exists():
            return JsonResponse({"error": "No sync jobs found"}, status=404)

        data = []
        for job in jobs:
            remaining_to_analyse_percentage = round(max(job.total_emails - job.analysed_count, 0) / max(job.total_emails, 1) * 100, 2)
            remaining_to_parse_percentage = round(max(job.potential_tx_count - job.parsed_count, 0) / max(job.potential_tx_count, 1) * 100, 2)
            data.append(
                {
                    "job_id": job.id,
                    "gmail_account_id": job.gmail_account.id,
                    "gmail_address": job.gmail_account.email_address,
                    "status": job.status,
                    "total_emails": job.total_emails,
                    "analysed": job.analysed_count,
                    "potential_transactions": job.potential_tx_count,
                    "parsed": job.parsed_count,
                    "successful_transactions": job.successful_tx_count,
                    "remaining_to_analyse_percentage": remaining_to_analyse_percentage,
                    "remaining_to_parse_percentage": remaining_to_parse_percentage,
                    "last_email_timestamp": job.last_email_timestamp,
                    "last_transaction_timestamp": job.last_tx_timestamp,
                    "created_at": job.created_at,
                    "modified_at": job.modified_at,
                }
            )
        return JsonResponse({"status": "ok", "jobs": data})
