# common/logging_config.py
import logging
import os
import sys
import traceback

class ExceptionFormatter(logging.Formatter):
    """
    Clean formatter that adds concise error info (file, line, and code)
    while removing all traceback output — even for Django and libraries.
    """

    def format(self, record):
        # base = super().format(record)
        exc_text = ''
        exc_info_copy = record.exc_info

        if record.exc_info:
            exc_type, exc_value, tb = record.exc_info

            # Get the last frame (where the error occurred)
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

            # 🚫 Suppress traceback text entirely
            if record.levelno == logging.WARNING:
                record.exc_info = None
                record.exc_text = None

        # Base formatting (after removing traceback)
        base = super().format(record)
        base += exc_text

        record.exc_info = exc_info_copy

        return base


class ExceptionFormatter2(logging.Formatter):
    """
    Adds concise error context (file, line, code) for logger.exception()
    but keeps full traceback for logger.error(..., exc_info=True) or Django internals.
    """

    def format(self, record):
        base = super().format(record)

        if record.exc_info:
            exc_type, exc_value, tb = record.exc_info

            # Extract the last frame (where exception occurred)
            if tb:
                frame = traceback.extract_tb(tb)[-1]
                filename = os.path.basename(frame.filename)
                line_number = frame.lineno
                source_line = frame.line.strip() if frame.line else "(no source)"
            else:
                filename = record.filename
                line_number = record.lineno
                source_line = "(unknown source)"

            # Detect if this came from logger.exception() (most likely your own code)
            called_from_logger_exception = record.funcName == "exception"

            if called_from_logger_exception:
                # ✅ Your handled errors — no traceback, just concise info
                base += (
                    f"\n❌ {exc_type.__name__} in {filename}:{line_number}"
                    f"\n   → {exc_value}"
                    f"\n   🧩 Line: {source_line}"
                )
                record.exc_info = None  # Suppress traceback
            else:
                # ✅ Django/system errors — include traceback
                tb_lines = "".join(traceback.format_exception(exc_type, exc_value, tb))
                base += (
                    f"\n💥 {exc_type.__name__} in {filename}:{line_number}"
                    f"\n   → {exc_value}"
                    f"\n   🧩 Line: {source_line}"
                    f"\n📜 Traceback:\n{tb_lines}"
                )

        return base


# Global uncaught exception hook
logger = logging.getLogger("asset_manager")

def log_uncaught_exceptions(exc_type, exc_value, tb):
    frame_info = traceback.extract_tb(tb)[-1] if tb else None
    filename = os.path.basename(frame_info.filename) if frame_info else "(unknown)"
    line_number = frame_info.lineno if frame_info else 0
    source_line = frame_info.line.strip() if frame_info and frame_info.line else "(no source)"

    logger.critical(
        f"💥 Uncaught {exc_type.__name__} in {filename}:{line_number}"
        f"\n   → {exc_value}"
        f"\n   🧩 Line: {source_line}",
        exc_info=(exc_type, exc_value, tb),
    )

sys.excepthook = log_uncaught_exceptions
