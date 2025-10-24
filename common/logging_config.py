import logging
from logging.handlers import RotatingFileHandler
import os
import sys
import traceback
from django.conf import settings  # ✅ Import Django settings


# ------------------------
# LOGGER SETUP
# ------------------------

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

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s"
)
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

# Prevent duplicate handlers (important when using Django autoreload)
if not logger.handlers:
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)


# ------------------------
# ERROR WRAPPERS
# ------------------------

def raise_with_line_info(prefix: str, error: Exception):
    """Raises a new exception with line info preserved."""
    tb = sys.exc_info()[2]
    frame = traceback.extract_tb(tb)[-1] if tb else None
    filename = os.path.basename(frame.filename) if frame else "?"
    line_no = frame.lineno if frame else "?"
    raise Exception(f"{prefix}: {error} [{filename}:{line_no}]") from error


def log_exceptions(func):
    """Decorator for catching and logging exceptions with traceback."""
    def wrapper(*args, **kwargs):
        try:
            logger.debug(f"Entering {func.__qualname__}")
            return func(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Error in {func.__qualname__}")
            raise_with_line_info(func.__qualname__, e)
    return wrapper
