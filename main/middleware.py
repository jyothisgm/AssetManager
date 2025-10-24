import threading
from common.logging_config import logger

_user = threading.local()

def get_current_user():
    """Return the current user stored in thread-local storage."""
    func_name = "get_current_user"
    try:
        user = getattr(_user, "value", None)
        logger.debug(f"[{func_name}] Retrieved current user: {user}")
        return user
    except Exception as e:
        logger.exception(f"[{func_name}] Failed to get current user")
        raise e


class CurrentUserMiddleware:
    """Middleware that saves the logged-in user in thread-local storage."""

    def __init__(self, get_response):
        func_name = "CurrentUserMiddleware.__init__"
        try:
            self.get_response = get_response
            logger.debug(f"[{func_name}] Middleware initialized")
        except Exception as e:
            logger.exception(f"[{func_name}] Initialization failed")
            raise e

    def __call__(self, request):
        func_name = "CurrentUserMiddleware.__call__"
        try:
            user = getattr(request, "user", None)
            _user.value = user
            logger.debug(f"[{func_name}] Stored user in thread-local: {user}")

            response = self.get_response(request)
            logger.debug(f"[{func_name}] Response generated successfully")

            return response
        except Exception as e:
            logger.exception(f"[{func_name}] Error while processing request")
            raise e
        finally:
            # Always clear thread-local storage to prevent leakage across requests
            _user.value = None
            logger.debug(f"[{func_name}] Cleared thread-local user reference")
