import threading

_local = threading.local()


def get_current_request():
    return getattr(_local, "request", None)


def client_ip(request):
    if request is None:
        return None
    # Only the direct peer address is trusted; configure the proxy to set REMOTE_ADDR correctly.
    return request.META.get("REMOTE_ADDR") or None


class RequestContextMiddleware:
    """Keeps the current request available to the audit service."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _local.request = request
        try:
            return self.get_response(request)
        finally:
            _local.request = None
