"""Cine face acțiunea curentă și de pe ce IP – pentru evenimentele de audit.

Contextul există doar pe durata unei cereri web (AuditContextMiddleware) sau a
unui bloc `with audit_context(...)`, și e golit garantat la final. În afara
lor (ex. un job programat) contextul e gol: evenimentul nu are autor uman.

De ce nu folosim direct contextul din django-auditlog: acesta nu e golit la
sfârșitul cererii, iar un job rulat ulterior pe același fir de execuție ar
moșteni utilizatorul ultimei cereri – un „cine” fals în jurnal.
"""

from contextlib import contextmanager
from contextvars import ContextVar

_current = ContextVar("audit_context", default=None)


def get_audit_context():
    """{"actor": User | None, "remote_addr": str | None} sau {} în afara unei cereri."""
    return _current.get() or {}


@contextmanager
def audit_context(actor=None, remote_addr=None):
    token = _current.set({"actor": actor, "remote_addr": remote_addr})
    try:
        yield
    finally:
        _current.reset(token)  # revine la starea dinainte, orice s-ar întâmpla


def client_ip(request):
    """IP-ul clientului. În spatele unui proxy (online), primul IP din X-Forwarded-For."""
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


class AuditContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user if request.user.is_authenticated else None
        with audit_context(actor=user, remote_addr=client_ip(request)):
            return self.get_response(request)
