import sys
import traceback

def raise_with_line_info(prefix: str, error: Exception):
    """
    Raises a new exception with the original message and line number included.
    Keeps the traceback chain for context.
    """
    tb = sys.exc_info()[2]
    line_no = traceback.extract_tb(tb)[-1].lineno if tb else "?"
    raise Exception(f"{prefix}: {error} (line {line_no})") from error
