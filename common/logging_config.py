import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import traceback
from django.conf import settings  # ✅ Import Django settings


# ------------------------
# LOGGER SETUP
# ------------------------

class ExceptionFormatter(logging.Formatter):
    def format(self, record):
        base = super().format(record)

        # If there's exception info, add detailed traceback context
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

            base += (
                f"\n❌ {exc_type.__name__} in {filename}:{line_number}"
                f"\n   → {exc_value}"
                f"\n   🧩 Line: {source_line}"
            )
        return base


LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)

LOG_FILE = os.path.join(LOG_DIR, "app.log")

# ✅ Get log level from settings or default to DEBUG
LOG_LEVEL = getattr(settings, "LOG_LEVEL", "DEBUG").upper()

logger = logging.getLogger("asset_manager")
logger.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))

# File handler (rotates at 10MB, keeps 5 backups)
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=10 * 1024 * 1024, backupCount=5)
file_handler.setLevel(getattr(logging, LOG_LEVEL, logging.DEBUG))

# Console handler
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.INFO)

formatter = ExceptionFormatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s"
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Prevent duplicate handlers (important when using Django autoreload)
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# Catch uncaught exceptions globally
def log_uncaught_exceptions(exc_type, exc_value, tb):
    frame_info = traceback.extract_tb(tb)[-1] if tb else None
    filename = os.path.basename(frame_info.filename) if frame_info else "(unknown file)"
    line_number = frame_info.lineno if frame_info else 0
    source_line = frame_info.line.strip() if frame_info and frame_info.line else "(no source)"

    logger.critical(
        f"💥 Uncaught {exc_type.__name__} in {filename}:{line_number}"
        f"\n   → {exc_value}"
        f"\n   🧩 Line: {source_line}",
        exc_info=(exc_type, exc_value, tb),
    )

sys.excepthook = log_uncaught_exceptions
