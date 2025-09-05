# camisas/middleware.py
import threading
_local = threading.local()

def get_current_request():
    return getattr(_local, "request", None)

def get_current_user():
    req = get_current_request()
    return getattr(req, "user", None) if req else None

class CurrentRequestMiddleware:
    """Disponibiliza o request atual para outras camadas (ex.: signals de auditoria)."""
    def __init__(self, get_response):
        self.get_response = get_response
    def __call__(self, request):
        _local.request = request
        try:
            return self.get_response(request)
        finally:
            _local.request = None
