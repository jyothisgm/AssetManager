import asyncio
import threading
from typing import Awaitable, Callable
from common.logging_config import logger

ACTIVE_JOB_THREADS: dict[int, threading.Thread] = {}


def start_job_thread(runner, job_id: int, name: str) -> None:
    """Start a background thread for a given job."""
    thread_name = f"{name}-{job_id}"
    thread = threading.Thread(target=runner, daemon=True, name=thread_name)
    ACTIVE_JOB_THREADS[job_id] = thread
    thread.start()
    logger.info(f"[ThreadManager] 🧵 Started {thread_name}")


def cleanup_dead_threads() -> None:
    """Remove inactive or finished threads from registry."""
    for job_id, thread in list(ACTIVE_JOB_THREADS.items()):
        if not thread.is_alive():
            ACTIVE_JOB_THREADS.pop(job_id, None)
            logger.debug(f"[ThreadManager] 🧹 Cleaned up dead thread for job_id={job_id}")


def get_existing_thread(job_id: int) -> threading.Thread | None:
    """Get the currently active thread for a job, if any."""
    thread = ACTIVE_JOB_THREADS.get(job_id)
    if thread:
        logger.debug(f"[ThreadManager] 🔍 Found active thread: {thread.name}")
    return thread


def cleanup_job_thread(job_id: int) -> None:
    """Remove a job thread from registry when it finishes."""
    if job_id in ACTIVE_JOB_THREADS:
        thread = ACTIVE_JOB_THREADS.pop(job_id)
        logger.debug(f"[ThreadManager] 🧹 Cleaned up job thread {thread.name}")



def run_async_in_thread(async_fn: Callable[[], Awaitable[None]], job_id: int, name: str) -> None:
    """
    Generic helper to run an async function in a background thread.
    Handles asyncio loop setup, error logging, and cleanup.
    """
    def runner():
        try:
            asyncio.run(async_fn())
        except Exception as e:
            print(f"[ThreadManager] ❌ Thread {name}-{job_id} crashed: {e}")
        finally:
            cleanup_job_thread(job_id)

    thread_name = f"{name}-{job_id}"
    thread = threading.Thread(target=runner, daemon=True, name=thread_name)
    ACTIVE_JOB_THREADS[job_id] = thread
    thread.start()
    logger.info(f"[ThreadManager] 🧵 Started {thread_name}")