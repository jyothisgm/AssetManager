import logging
import os
import sys
import traceback
import threading

# -----------------------------------------------------------------------------
# THREAD-LOCAL STORAGE (shared with middleware)
# -----------------------------------------------------------------------------
_user_local = threading.local()

def set_current_user(user):
    """Store current user in thread-local storage."""
    _user_local.user = user

def get_current_user():
    """Retrieve current user if available."""
    return getattr(_user_local, "user", None)


# -----------------------------------------------------------------------------
# LOG FILTER — adds current user info to every log record
# -----------------------------------------------------------------------------
class UserContextFilter(logging.Filter):
    def filter(self, record):
        user = get_current_user()
        record.user = (
            getattr(user, "email", None)
            or getattr(user, "username", None)
            or "Anonymous"
        )
        return True


# -----------------------------------------------------------------------------
# CLEAN EXCEPTION FORMATTER — adds concise context
# -----------------------------------------------------------------------------
class ExceptionFormatter(logging.Formatter):
    """
    Clean formatter that adds concise error info (file, line, and code)
    while removing traceback clutter. Includes user context.
    """

    def format(self, record):
        exc_text = ""
        exc_info_copy = record.exc_info

        if record.exc_info:
            exc_type, exc_value, tb = record.exc_info

            if tb:
                frame = traceback.extract_tb(tb)[-1]
                filename = os.path.basename(frame.filename)
                line_number = frame.lineno
                source_line = frame.line.strip() if frame.line else "(no source)"
            else:
                filename = record.filename
                line_number = record.lineno
                source_line = "(unknown source)"

            exc_text = (
                f"\n❌ {exc_type.__name__} in {filename}:{line_number}"
                f"\n   → {exc_value}"
                f"\n   🧩 Line: {source_line}"
            )

            # Suppress traceback for warnings
            if record.levelno == logging.WARNING:
                record.exc_info = None
                record.exc_text = None

        # Base formatting
        base = super().format(record)
        base = f"[User: {getattr(record, 'user', 'Anonymous')}] {base}"

        if exc_text:
            base += exc_text

        # Restore original exc_info
        record.exc_info = exc_info_copy

        return base


# -----------------------------------------------------------------------------
# GLOBAL LOGGER CONFIGURATION
# -----------------------------------------------------------------------------
logger = logging.getLogger("asset_manager")
logger.addFilter(UserContextFilter())


# -----------------------------------------------------------------------------
# GLOBAL EXCEPTION HANDLER
# -----------------------------------------------------------------------------
def log_uncaught_exceptions(exc_type, exc_value, tb):
    frame_info = traceback.extract_tb(tb)[-1] if tb else None
    filename = os.path.basename(frame_info.filename) if frame_info else "(unknown)"
    line_number = frame_info.lineno if frame_info else 0
    source_line = (
        frame_info.line.strip() if frame_info and frame_info.line else "(no source)"
    )

    logger.critical(
        f"💥 Uncaught {exc_type.__name__} in {filename}:{line_number}"
        f"\n   → {exc_value}"
        f"\n   🧩 Line: {source_line}",
        exc_info=(exc_type, exc_value, tb),
    )

sys.excepthook = log_uncaught_exceptions
