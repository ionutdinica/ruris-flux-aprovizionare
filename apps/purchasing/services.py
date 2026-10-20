"""Regulile de business ale comenzilor: tranzițiile de status.

Statusul unei comenzi se schimbă DOAR prin aceste funcții. Fiecare:
  1. blochează comanda în baza de date pe durata operației (select_for_update),
     ca două persoane care apasă simultan „Trimite” să nu producă o stare greșită;
  2. verifică dacă tranziția e permisă (docs/03-fluxuri-si-stari.md);
  3. înregistrează evenimentul în jurnalul de audit.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import BusinessEvent
from apps.audit.services import record_event

from .models import PurchaseOrder, PurchaseOrderLine

Status = PurchaseOrder.Status


class TransitionError(ValidationError):
    """Tranziția de status nu e permisă în situația curentă."""


def _lock(order):
    return PurchaseOrder.objects.select_for_update().get(pk=order.pk)


def _require_reason(reason):
    reason = (reason or "").strip()
    if not reason:
        raise TransitionError("Motivul este obligatoriu.")
    return reason


def received_quantities(order):
    """Cantitatea recepționată netă pe fiecare linie: {id linie: cantitate}."""
    lines = PurchaseOrderLine.objects.with_progress().filter(order=order)
    return dict(lines.values_list("id", "received_qty"))


@transaction.atomic
def send_order(order):
    """Ciornă → Trimisă. Comanda devine angajament față de furnizor."""
    order = _lock(order)
    if order.status != Status.DRAFT:
        raise TransitionError("Doar o comandă în ciornă poate fi trimisă.")
    lines = list(order.lines.select_related("product"))
    if not lines:
        raise TransitionError("Comanda nu are nicio linie.")
    if not order.supplier.is_active:
        raise TransitionError(f"Furnizorul {order.supplier} este inactiv.")
    inactive = [line.product.code for line in lines if not line.product.is_active]
    if inactive:
        raise TransitionError(f"Produse inactive pe comandă: {', '.join(inactive)}.")

    order.status = Status.SENT
    order.sent_at = timezone.now()
    order.save(update_fields=["status", "sent_at", "updated_at"])
    record_event(
        BusinessEvent.Type.ORDER_SENT,
        f"Comanda {order} a fost trimisă către {order.supplier}.",
        target=order,
    )
    return order


@transaction.atomic
def cancel_order(order, reason):
    """Ciornă / Trimisă → Anulată. Doar dacă nu s-a recepționat nimic (I-08)."""
    reason = _require_reason(reason)
    order = _lock(order)
    if order.status not in (Status.DRAFT, Status.SENT, Status.PARTIALLY_RECEIVED):
        raise TransitionError("Doar o comandă în ciornă sau trimisă poate fi anulată.")
    received = any(qty > 0 for qty in received_quantities(order).values())
    if order.status == Status.PARTIALLY_RECEIVED or received:
        # Mesajul spune și ce e de făcut, nu doar ce nu se poate.
        raise TransitionError(
            "S-a recepționat deja marfă pe această comandă; folosește „Închide cu rest nelivrat”."
        )

    order.status = Status.CANCELLED
    order.close_reason = reason
    order.save(update_fields=["status", "close_reason", "updated_at"])
    record_event(
        BusinessEvent.Type.ORDER_CANCELLED,
        f"Comanda {order} a fost anulată.",
        target=order,
        data={"motiv": reason},
    )
    return order


@transaction.atomic
def close_order(order, reason):
    """Parțial recepționată → Închisă: restul nu mai vine (I-08)."""
    reason = _require_reason(reason)
    order = _lock(order)
    if order.status != Status.PARTIALLY_RECEIVED:
        raise TransitionError("Doar o comandă parțial recepționată poate fi închisă cu rest.")

    order.status = Status.CLOSED
    order.close_reason = reason
    order.save(update_fields=["status", "close_reason", "updated_at"])
    record_event(
        BusinessEvent.Type.ORDER_CLOSED,
        f"Comanda {order} a fost închisă cu rest nelivrat.",
        target=order,
        data={"motiv": reason},
    )
    return order


@transaction.atomic
def refresh_status(order):
    """Recalculează statusul din cantitățile recepționate (tranzițiile automate).

    Apelată după fiecare eveniment care schimbă recepțiile: confirmare de
    recepție, rezolvare de discrepanță, retur, linie nouă (capitolul 5).
    """
    order = _lock(order)
    if order.status not in (Status.SENT, Status.PARTIALLY_RECEIVED, Status.RECEIVED):
        return order  # ciornele, comenzile închise și anulate nu se recalculează

    lines = list(order.lines.all())
    received = received_quantities(order)
    if lines and all(received[line.pk] >= line.quantity for line in lines):
        new_status = Status.RECEIVED
    elif any(received[line.pk] > 0 for line in lines):
        new_status = Status.PARTIALLY_RECEIVED
    else:
        new_status = Status.SENT

    if new_status != order.status:
        order.status = new_status
        order.save(update_fields=["status", "updated_at"])  # schimbarea intră în jurnal automat
    return order
