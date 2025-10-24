import sys
import logging

logger = logging.getLogger(__name__)

def raise_with_line_info(context: str, error: Exception):
    """
    Logs an error with line number, then re-raises it.
    Useful for debugging LLM or file parsing exceptions.
    """
    tb = sys.exc_info()[2]
    line = tb.tb_lineno if tb else "unknown"
    logger.error(f"⚠️ {context}: {error} (line {line})", exc_info=True)
    raise error
