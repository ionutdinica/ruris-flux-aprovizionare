"""Regulile de business ale facturilor: validare, reverificare automată, aprobare, plată.

Statusul unei facturi se schimbă DOAR prin aceste funcții (docs/03-fluxuri-si-stari.md).
Potrivirea propriu-zisă e în matching.py; aici se decide ce urmează după ea.

Concurență: înainte de orice potrivire se blochează în baza de date liniile de comandă
implicate, mereu în aceeași ordine (după id). Două facturi pe aceeași marfă, validate
în aceeași secundă, se verifică astfel una după alta, iar a doua o „vede” pe prima.
"""

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.audit.models import BusinessEvent
from apps.audit.services import record_event
from apps.currency.services import InvalidRateDate, RatePending, get_rate
from apps.purchasing.models import PurchaseOrderLine

from .matching import find_problems
from .models import Invoice, InvoiceLine

Status = Invoice.Status


class InvoiceError(ValidationError):
    """Operația nu e permisă în situația curentă a facturii."""


# --- Blocări și potrivire -------------------------------------------------------------------


def _lock_order_lines(order_line_ids):
    """Blochează liniile de comandă (ordonat după id, ca să evităm blocajele reciproce)."""
    return list(
        PurchaseOrderLine.objects.select_for_update()
        .filter(pk__in=sorted(set(order_line_ids)))
        .order_by("pk")
        .values_list("pk", flat=True)
    )


def _order_line_ids(invoice):
    return list(InvoiceLine.objects.filter(invoice=invoice).values_list("order_line_id", flat=True))


def _lock(invoice):
    """Blochează liniile de comandă ale facturii, apoi factura. Mereu în această ordine."""
    _lock_order_lines(_order_line_ids(invoice))
    return Invoice.objects.select_for_update().get(pk=invoice.pk)


def _require_status(invoice, allowed, message):
    if invoice.status not in allowed:
        raise InvoiceError(message)


def _require_text(value, message):
    value = (value or "").strip()
    if not value:
        raise InvoiceError(message)
    return value


def _apply_match(invoice):
    """Rulează potrivirea și pune statusul rezultat: Potrivită sau Blocată."""
    problems = find_problems(invoice)
    invoice.match_result = [problem.as_dict() for problem in problems]
    invoice.matched_at = timezone.now()
    invoice.status = Status.BLOCKED if problems else Status.MATCHED
    invoice.save(update_fields=["match_result", "matched_at", "status", "updated_at"])
    return problems


def _set_rate(invoice, quote):
    """Cursul BNR se fixează pe factură și nu se mai schimbă (I-24)."""
    invoice.exchange_rate = quote.rate / quote.multiplier
    invoice.exchange_rate_date = quote.date
    invoice.total_ron = quote.to_ron(invoice.declared_total)
    invoice.save(update_fields=["exchange_rate", "exchange_rate_date", "total_ron", "updated_at"])


def _codes(invoice):
    return [problem["code"] for problem in invoice.problems]


# --- Validare ------------------------------------------------------------------------------


@transaction.atomic
def validate_invoice(invoice):
    """Înregistrată → Potrivită / Blocată / Curs în așteptare."""
    invoice = _lock(invoice)
    _require_status(invoice, [Status.REGISTERED], "Doar o factură înregistrată poate fi validată.")
    if not invoice.lines.exists():
        raise InvoiceError("Factura nu are nicio linie.")
    if invoice.invoice_date > timezone.localdate():
        # Verificat aici, pentru orice monedă: la RON nu se cere niciun curs (I-27).
        raise InvoiceError(f"Data facturii {invoice.invoice_date:%d.%m.%Y} este în viitor.")

    try:
        quote = get_rate(invoice.currency, invoice.invoice_date)
    except InvalidRateDate as exc:
        raise InvoiceError(str(exc)) from exc
    except RatePending:
        # Fără curs nu putem calcula totalul în lei: factura așteaptă și se reia singură
        # după actualizarea cursurilor (resume_rate_pending, la semnalul rates_synced).
        invoice.status = Status.RATE_PENDING
        invoice.save(update_fields=["status", "updated_at"])
        record_event(
            BusinessEvent.Type.INVOICE_VALIDATED,
            f"Factura {invoice} așteaptă cursul BNR din {invoice.invoice_date:%d.%m.%Y}.",
            target=invoice,
        )
        return invoice

    _set_rate(invoice, quote)
    _apply_match(invoice)
    record_event(
        BusinessEvent.Type.INVOICE_VALIDATED,
        f"Factura {invoice} a fost validată: {invoice.get_status_display().lower()}.",
        target=invoice,
        data={"motive": _codes(invoice)},
    )
    _recheck_related(invoice)
    return invoice


# --- Reverificare automată -----------------------------------------------------------------


def recheck_invoices(order_line_ids, *, exclude=None, cause=""):
    """Reverifică facturile Potrivite / Blocate care conțin aceste linii de comandă.

    Se rulează în ordinea înregistrării (id crescător): rezultatul unei facturi depinde
    doar de facturile anterioare ei (matching.invoiced_elsewhere), care sunt deja
    actualizate în această trecere. O singură trecere ajunge, iar rezultatul e
    determinist. Întoarce facturile al căror status s-a schimbat.
    """
    if not order_line_ids:
        return []
    with transaction.atomic():
        _lock_order_lines(order_line_ids)
        # Subinterogare, nu join + DISTINCT: PostgreSQL nu permite FOR UPDATE cu DISTINCT.
        touching = InvoiceLine.objects.filter(order_line_id__in=order_line_ids).values("invoice")
        invoices = Invoice.objects.select_for_update().filter(
            status__in=Invoice.RECHECKABLE_STATUSES, pk__in=touching
        )
        if exclude is not None:
            invoices = invoices.exclude(pk=exclude.pk)
        changed = []
        for invoice in invoices.order_by("pk"):
            before = invoice.status
            _apply_match(invoice)
            if invoice.status != before:
                changed.append(invoice)
                record_event(
                    BusinessEvent.Type.INVOICE_RECHECKED,
                    f"Factura {invoice} a devenit automat „{invoice.get_status_display()}”{cause}.",
                    target=invoice,
                    data={"motive": _codes(invoice)},
                )
        return changed


def _recheck_related(invoice):
    """După o schimbare a acestei facturi, reverifică celelalte facturi pe aceeași marfă."""
    return recheck_invoices(_order_line_ids(invoice), exclude=invoice, cause=f" după {invoice}")


def recheck_order(order):
    """Recepțiile sau comanda s-au schimbat: reverifică facturile legate de comandă."""
    line_ids = list(order.lines.values_list("pk", flat=True))
    return recheck_invoices(line_ids, cause=f" după o modificare pe comanda {order}")


def resume_rate_pending():
    """Facturile în „Curs în așteptare” primesc cursul, dacă între timp e cunoscut."""
    resumed = []
    pending = Invoice.objects.filter(status=Status.RATE_PENDING).order_by("pk")
    for invoice in pending.values_list("pk", flat=True):
        with transaction.atomic():
            invoice = _lock(Invoice(pk=invoice))
            if invoice.status != Status.RATE_PENDING:
                continue
            try:
                quote = get_rate(invoice.currency, invoice.invoice_date)
            except RatePending:
                continue  # încă nu; data viitoare
            _set_rate(invoice, quote)
            _apply_match(invoice)
            record_event(
                BusinessEvent.Type.INVOICE_RECHECKED,
                f"Factura {invoice} a primit cursul BNR din {quote.date:%d.%m.%Y} și a devenit "
                f"„{invoice.get_status_display()}”.",
                target=invoice,
                data={"motive": _codes(invoice)},
            )
            _recheck_related(invoice)
            resumed.append(invoice)
    return resumed


# --- Decizii ale Contabilității --------------------------------------------------------------


@transaction.atomic
def reopen_invoice(invoice):
    """Blocată / Curs în așteptare → Înregistrată: pentru corectarea datelor introduse."""
    invoice = _lock(invoice)
    _require_status(
        invoice,
        [Status.BLOCKED, Status.RATE_PENDING],
        "Doar o factură blocată sau în așteptare poate fi redeschisă pentru corectare.",
    )
    invoice.status = Status.REGISTERED
    invoice.match_result = []
    invoice.matched_at = None
    # Cursul se stabilește din nou la revalidare: data facturii se poate corecta.
    invoice.exchange_rate = invoice.exchange_rate_date = invoice.total_ron = None
    invoice.save()
    record_event(
        BusinessEvent.Type.INVOICE_REOPENED,
        f"Factura {invoice} a fost redeschisă pentru corectare.",
        target=invoice,
    )
    return invoice


@transaction.atomic
def approve_invoice(invoice, user):
    """Potrivită → Aprobată la plată. Potrivirea se mai rulează o dată, chiar acum."""
    invoice = _lock(invoice)
    _require_status(invoice, [Status.MATCHED], "Doar o factură potrivită poate fi aprobată.")
    problems = find_problems(invoice)
    if problems:
        raise InvoiceError(
            f"Factura nu mai corespunde: {problems[0].message} Reverific-o înainte de aprobare."
        )
    _approve(invoice, user)
    record_event(
        BusinessEvent.Type.INVOICE_APPROVED,
        f"Factura {invoice} a fost aprobată la plată.",
        target=invoice,
    )
    _recheck_related(invoice)
    return invoice


@transaction.atomic
def force_approve_invoice(invoice, user, reason):
    """Blocată → Aprobată la plată, cu justificare obligatorie (I-23)."""
    reason = _require_text(reason, "Justificarea este obligatorie pentru a forța o factură.")
    invoice = _lock(invoice)
    _require_status(invoice, [Status.BLOCKED], "Doar o factură blocată poate fi forțată.")
    invoice.override_reason = reason
    _approve(invoice, user)
    record_event(
        BusinessEvent.Type.INVOICE_FORCE_APPROVED,
        f"Factura {invoice} a fost forțată la plată, deși era blocată.",
        target=invoice,
        # Se păstrează și motivele de blocare din acel moment: ce anume s-a ignorat.
        data={"justificare": reason, "motive": [p["message"] for p in invoice.problems]},
    )
    _recheck_related(invoice)
    return invoice


def _approve(invoice, user):
    invoice.status = Status.APPROVED
    invoice.approved_by = user
    invoice.approved_at = timezone.now()
    invoice.save()


@transaction.atomic
def mark_paid(invoice, paid_at, reference=""):
    """Aprobată la plată → Plătită."""
    invoice = _lock(invoice)
    _require_status(invoice, [Status.APPROVED], "Doar o factură aprobată poate fi marcată plătită.")
    if paid_at > timezone.localdate():
        raise InvoiceError("Data plății nu poate fi în viitor.")
    if paid_at < invoice.invoice_date:
        raise InvoiceError("Data plății nu poate fi înaintea datei facturii.")
    invoice.status = Status.PAID
    invoice.paid_at = paid_at
    invoice.payment_reference = (reference or "").strip()
    invoice.save()
    record_event(
        BusinessEvent.Type.INVOICE_PAID,
        f"Factura {invoice} a fost plătită pe {paid_at:%d.%m.%Y}.",
        target=invoice,
        data={"referinta": invoice.payment_reference} if invoice.payment_reference else None,
    )
    return invoice


@transaction.atomic
def reject_invoice(invoice, reason):
    """Înregistrată / În așteptare / Blocată → Respinsă (contestată la furnizor)."""
    reason = _require_text(reason, "Motivul respingerii este obligatoriu.")
    invoice = _lock(invoice)
    _require_status(
        invoice,
        [Status.REGISTERED, Status.RATE_PENDING, Status.BLOCKED],
        "O factură potrivită, aprobată sau plătită nu mai poate fi respinsă.",
    )
    invoice.status = Status.REJECTED
    invoice.rejection_reason = reason
    invoice.save()
    record_event(
        BusinessEvent.Type.INVOICE_REJECTED,
        f"Factura {invoice} a fost respinsă.",
        target=invoice,
        data={"motiv": reason},
    )
    return invoice
