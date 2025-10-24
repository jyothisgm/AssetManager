import threading

_user = threading.local()

def get_current_user():
    """Return the current user stored in thread-local storage."""
    return getattr(_user, "value", None)

class CurrentUserMiddleware:
    """Middleware that saves the logged-in user in thread-local storage."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _user.value = getattr(request, "user", None)
        response = self.get_response(request)
        _user.value = None
        return response
