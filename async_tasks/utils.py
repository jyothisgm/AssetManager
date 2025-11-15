import re
import threading

from asgiref.sync import sync_to_async
from typing import List
from main.settings import BASE_DIR
from common.logging_config import logger


EMAIL_JOB_LOG_DIR = BASE_DIR / "email_jobs"
EMAIL_JOB_LOG_DIR.mkdir(parents=True, exist_ok=True)


async def _update_job_status(job, **fields):
    """Helper to safely update fields in EmailSyncJob."""
    for k, v in fields.items():
        setattr(job, k, v)
    await sync_to_async(job.save)()


def write_email_job_log(job_id: int, text: str):
    """Append text to the log file for a specific EmailSyncJob."""
    file_path = EMAIL_JOB_LOG_DIR / f"job_{job_id}.log"
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


async def _log_batch_results(job, batch_no, analysed_total, total_unique, possible_tx, emails):
    """Log batch results and write to file."""
    lines = [f"\n🧾 [Batch {batch_no}] ---- Possible Transactions Detected ----"]
    if not possible_tx:
        lines.append("None found in this batch.")
    else:
        for t in possible_tx:
            email_id = t.get("email_id", "")
            email_obj = next((e for e in emails if e["id"] == email_id), None)
            timestamp = email_obj["timestamp"] if email_obj else "unknown"
            lines.append(
                f"💳 [msg_id: {email_id} | {timestamp}] "
                f"{t.get('subject', '')} | From: {t.get('from', '')} | Reason: {t.get('reason', '—')}"
            )

    lines.append(
        f"[EmailSyncJob] Batch {batch_no}: analysed {analysed_total}/{total_unique}, "
        f"potential_tx={len(possible_tx)}"
    )

    batch_text = "\n".join(lines)
    logger.info(batch_text)
    write_email_job_log(job.id, batch_text)


# Helper to read email IDs from log file
async def _read_email_ids_from_log(job_id: int) -> List[str]:
    pattern = re.compile(r"\[msg_id:\s*(\S+)\s*\|")
    log_path = EMAIL_JOB_LOG_DIR / f"job_{job_id}.log"

    if not log_path.exists():
        logger.error(f"[EmailSyncJob] No log file for job_id={job_id}")
        return []

    ids = []
    with open(log_path, "r", encoding="utf-8") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                ids.append(match.group(1))
    # Inverse order (newest→oldest)
    return ids[::-1]