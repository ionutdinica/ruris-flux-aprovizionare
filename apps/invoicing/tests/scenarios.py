"""Facturi de test, construite ca în aplicație: antet + linii legate de comandă."""

import itertools
from datetime import timedelta
from decimal import Decimal

from django.utils import timezone

from apps.invoicing import services
from apps.invoicing.models import Invoice, InvoiceLine

_numbers = itertools.count(1)


def register(
    order,
    *quantities,
    prices=None,
    lines=None,
    supplier=None,
    currency=None,
    invoice_date=None,
    declared=None,
):
    """Factură ÎNREGISTRATĂ pe liniile comenzii `order` (în ordine), cu cantitățile date.

    `lines` = [(linie de comandă, cantitate)] pentru facturi pe mai multe comenzi.
    Totalurile declarate sunt implicit exact cele calculate; `declared` = (net, tva, total).
    """
    invoice_date = invoice_date or timezone.localdate()
    invoice = Invoice.objects.create(
        supplier=supplier or order.supplier,
        supplier_invoice_number=f"F-{next(_numbers)}",
        invoice_date=invoice_date,
        due_date=invoice_date + timedelta(days=30),
        currency=currency or order.currency,
        declared_net=0,
        declared_vat=0,
        declared_total=0,
    )
    pairs = lines or list(zip(order.lines.order_by("id"), quantities, strict=False))
    for index, (order_line, quantity) in enumerate(pairs):
        InvoiceLine.objects.create(
            invoice=invoice,
            order_line=order_line,
            quantity=Decimal(quantity),
            unit_price=Decimal(prices[index]) if prices else order_line.unit_price,
            vat_rate=order_line.vat_rate,
        )
    if declared:
        invoice.declared_net, invoice.declared_vat, invoice.declared_total = map(Decimal, declared)
    else:
        invoice.declared_net = invoice.computed_net
        invoice.declared_vat = invoice.computed_vat
        invoice.declared_total = invoice.computed_total
    invoice.save()
    return invoice


def validated(order, *quantities, **kwargs):
    """Factură înregistrată și validată (rezultatul potrivirii e în status)."""
    return services.validate_invoice(register(order, *quantities, **kwargs))


def refreshed(invoice):
    return Invoice.objects.get(pk=invoice.pk)


def codes(invoice):
    return [problem["code"] for problem in refreshed(invoice).problems]


def messages(invoice):
    return " | ".join(problem["message"] for problem in refreshed(invoice).problems)
