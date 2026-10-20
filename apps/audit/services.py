"""Înregistrarea evenimentelor de business în jurnalul de audit.

Folosire (ex. în capitolul 7, la forțarea unei facturi):

    record_event(
        BusinessEvent.Type.INVOICE_FORCE_APPROVED,
        f"Factura {invoice} a fost forțată la plată.",
        target=invoice,
        data={"justificare": reason},
    )
"""

from django.contrib.contenttypes.models import ContentType

from .context import get_audit_context
from .models import BusinessEvent


def record_event(event_type, message, *, target=None, data=None, actor=None):
    """Scrie un eveniment în jurnal și îl întoarce.

    `actor` e implicit utilizatorul cererii curente; se dă explicit doar când
    contextul nu îl cunoaște încă (ex. chiar în momentul autentificării).
    """
    if event_type not in BusinessEvent.Type.values:
        raise ValueError(f"Tip de eveniment necunoscut: {event_type!r}")

    context = get_audit_context()
    if actor is None:
        actor = context.get("actor")

    event = BusinessEvent(
        event_type=event_type,
        message=message,
        actor=actor,
        data=data or {},
        remote_addr=context.get("remote_addr"),
    )
    if target is not None:
        event.content_type = ContentType.objects.get_for_model(target)
        event.object_id = str(target.pk)
        event.object_repr = str(target)[:255]
    event.save()
    return event
