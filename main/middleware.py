from common.logging_config import logger, set_current_user

class CurrentUserMiddleware:
    """
    Middleware that saves the logged-in user in a single shared
    thread-local storage (used also by the logger).
    """

    def __init__(self, get_response):
        self.get_response = get_response
        logger.debug("[CurrentUserMiddleware.__init__] Middleware initialized")

    def __call__(self, request):
        func_name = "CurrentUserMiddleware.__call__"
        user = getattr(request, "user", None)
        try:
            # Store user for this thread (shared with logger)
            set_current_user(user)
            logger.debug(f"[{func_name}] Stored user in thread-local: {user}")
            response = self.get_response(request)
            logger.debug(f"[{func_name}] Response generated successfully")
            return response
        except Exception as e:
            logger.exception(f"[{func_name}] Error while processing request")
            raise e
        finally:
            # Always clear to prevent leakage across requests
            set_current_user(None)
            logger.debug(f"[{func_name}] Cleared thread-local user reference")
