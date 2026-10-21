"""Testul cap-coadă: povestea din cerință, parcursă prin pagini, ca de oameni reali.

    Maria (Achiziții) comandă → Ion (Depozit) recepționează o parte → Elena (Contabilitate)
    înregistrează factura pe tot: blocată → a doua zi, rezumatul o anunță pe Maria →
    Ion recepționează restul → factura se deblochează SINGURĂ → Elena o aprobă și o plătește.

Celelalte teste verifică piesele separat (regulile, direct); acesta verifică faptul că
piesele se leagă: formulare, permisiuni, semnale, potrivire, notificări, audit.
"""

import datetime

import pytest
from django.core import mail
from django.urls import reverse
from django.utils import timezone

from apps.audit.models import BusinessEvent
from apps.catalog.tests.factories import ProductFactory, SupplierFactory
from apps.core.dates import is_business_day
from apps.invoicing.models import Invoice
from apps.notifications.services import send_daily_digests
from apps.purchasing.models import PurchaseOrder
from apps.warehouse.models import GoodsReceipt

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()


def post_ok(client, url, data=None):
    """Un formular trimis cu succes: redirecționare (formularele invalide răspund 200)."""
    response = client.post(url, data or {})
    assert response.status_code == 302, response.content.decode()[:500]
    return response


def formset(rows, prefix="lines"):
    data = {
        f"{prefix}-TOTAL_FORMS": len(rows),
        f"{prefix}-INITIAL_FORMS": 0,
        f"{prefix}-MIN_NUM_FORMS": 0,
        f"{prefix}-MAX_NUM_FORMS": 1000,
    }
    for index, fields in enumerate(rows):
        data.update({f"{prefix}-{index}-{key}": value for key, value in fields.items()})
    return data


def next_business_morning():
    day = TODAY + datetime.timedelta(days=1)
    while not is_business_day(day):
        day += datetime.timedelta(days=1)
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(8, 5)))


def receive(client, order, quantities):
    """Ion numără marfa pe comandă (cantitățile în ordinea liniilor încă așteptate)."""
    url = reverse("warehouse:receipt_from_order", args=[order.pk])
    rows = [{"quantity_received": quantity} for quantity in quantities]
    post_ok(
        client, url, {"receipt_date": TODAY.isoformat(), "delivery_note": "AVZ", **formset(rows)}
    )
    receipt = GoodsReceipt.objects.filter(status=GoodsReceipt.Status.DRAFT).get()
    post_ok(client, reverse("warehouse:receipt_confirm", args=[receipt.pk]))


def test_from_order_to_payment(client, procurement_user, warehouse_user, accounting_user):
    maria, ion, elena = procurement_user, warehouse_user, accounting_user
    supplier = SupplierFactory(name="Rulmenți Oltenia SRL")
    bearing, belt = ProductFactory(code="RUL-6204"), ProductFactory(code="CUR-A42")

    # 1. Maria creează comanda (10 rulmenți × 100 + 4 curele × 50 lei) și o trimite.
    client.force_login(maria)
    post_ok(
        client,
        reverse("purchasing:order_create"),
        {
            "supplier": supplier.pk,
            "currency": "RON",
            "owner": maria.pk,
            "order_date": TODAY.isoformat(),
            "expected_date": (TODAY + datetime.timedelta(days=7)).isoformat(),
            "notes": "",
            **formset(
                [
                    {
                        "product": bearing.pk,
                        "quantity": "10",
                        "unit_price": "100",
                        "vat_rate": "21.00",
                    },
                    {"product": belt.pk, "quantity": "4", "unit_price": "50", "vat_rate": "21.00"},
                ]
            ),
        },
    )
    order = PurchaseOrder.objects.get()
    post_ok(client, reverse("purchasing:order_send", args=[order.pk]))

    # 2. Ion recepționează doar rulmenții (curelele nu au venit).
    client.force_login(ion)
    receive(client, order, ["10", ""])
    order.refresh_from_db()
    assert order.status == PurchaseOrder.Status.PARTIALLY_RECEIVED

    # 3. Elena înregistrează factura pe tot și o validează: blocată, curelele nu au sosit.
    client.force_login(elena)
    lines = list(order.lines.order_by("id"))
    response = client.post(
        reverse("invoicing:invoice_create"),
        {
            "supplier": supplier.pk,
            "supplier_invoice_number": "RO-1001",
            "currency": "RON",
            "invoice_date": TODAY.isoformat(),
            "due_date": (TODAY + datetime.timedelta(days=30)).isoformat(),
            "declared_net": "1200.00",
            "declared_vat": "252.00",
            "declared_total": "1452.00",
            "notes": "",
            "validate": "",
            **formset(
                [
                    {
                        "order_line": lines[0].pk,
                        "quantity": "10",
                        "unit_price": "100",
                        "vat_rate": "21.00",
                    },
                    {
                        "order_line": lines[1].pk,
                        "quantity": "4",
                        "unit_price": "50",
                        "vat_rate": "21.00",
                    },
                ]
            ),
        },
        follow=True,
    )
    invoice = Invoice.objects.get()
    assert invoice.status == Invoice.Status.BLOCKED
    assert "4 buc nesosite" in response.content.decode()

    # 4. A doua zi dimineața, rezumatul pe email o anunță pe Maria (responsabila comenzii).
    send_daily_digests(now=next_business_morning())
    to_maria = next(message for message in mail.outbox if message.to == [maria.email])
    assert invoice.number in to_maria.body and "[NOU]" in to_maria.body

    # 5. Ion recepționează curelele: factura se deblochează SINGURĂ, fără ca Elena să facă nimic.
    client.force_login(ion)
    receive(client, order, ["4"])
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.MATCHED

    # 6. Elena aprobă și plătește.
    client.force_login(elena)
    post_ok(client, reverse("invoicing:invoice_approve", args=[invoice.pk]))
    post_ok(
        client,
        reverse("invoicing:invoice_pay", args=[invoice.pk]),
        {"paid_at": TODAY.isoformat(), "reference": "OP 77"},
    )
    invoice.refresh_from_db()
    order.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID
    assert order.status == PurchaseOrder.Status.RECEIVED

    # 7. Jurnalul spune toată povestea: ce, cine, în ordine.
    story = list(
        BusinessEvent.objects.exclude(event_type__startswith="auth.")
        .order_by("id")
        .values_list("event_type", "actor__username")
    )
    assert story == [
        ("order.sent", maria.username),
        ("receipt.confirmed", ion.username),
        ("invoice.validated", elena.username),
        ("receipt.confirmed", ion.username),
        ("invoice.rechecked", ion.username),  # deblocarea a fost declanșată de recepția lui Ion
        ("invoice.approved", elena.username),
        ("invoice.paid", elena.username),
    ]

    # 8. Nimic nu mai așteaptă: panoul Elenei e curat, Maria vede comanda recepționată.
    html = client.get(reverse("dashboard:home")).content.decode()
    assert "Nimic de rezolvat acum" in html
