"""Ciclul complet din README („Încearcă un ciclu complet”), pas cu pas, peste datele demo.

Evaluatorul îl parcurge de mână, cu cifrele și mesajele scrise acolo. Testul verifică
exact acele cifre și mesaje: dacă se schimbă ceva în aplicație, README-ul nu mai minte.
"""

import datetime

import pytest
from django.core import mail
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import BusinessEvent
from apps.catalog.models import Product, Supplier
from apps.demo.testing import seed_demo_for_tests
from apps.invoicing.models import Invoice
from apps.purchasing.models import PurchaseOrder
from apps.warehouse.models import GoodsReceipt
from tests.test_end_to_end import formset, post_ok

TODAY = timezone.localdate()


@pytest.fixture(scope="module")
def demo(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock(), transaction.atomic():
        yield seed_demo_for_tests()
        transaction.set_rollback(True)


pytestmark = pytest.mark.django_db


def person(username):
    return User.objects.get(username=username)


def receive(client, order, quantities):
    """Ion: „Recepționează” → cantitățile numărate → „Salvează ciorna” → „Confirmă recepția”."""
    rows = [{"quantity_received": quantity} for quantity in quantities]
    post_ok(
        client,
        reverse("warehouse:receipt_from_order", args=[order.pk]),
        {"receipt_date": TODAY.isoformat(), "delivery_note": "AVZ 1", **formset(rows)},
    )
    draft = order.receipts.get(status=GoodsReceipt.Status.DRAFT)
    post_ok(client, reverse("warehouse:receipt_confirm", args=[draft.pk]))
    order.refresh_from_db()


def test_the_cycle_described_in_the_readme(demo, client):
    supplier = Supplier.objects.get(name="Rulmenți Oltenia SRL")
    products = {p.code: p for p in Product.objects.filter(code__in=["RUL-6204", "CUR-A42"])}
    before = BusinessEvent.objects.order_by("-pk").values_list("pk", flat=True).first()

    # 1. Maria: comanda nouă, 100 rulmenți × 18,90 + 50 curele × 18,50, trimisă.
    client.force_login(person("maria.pop"))
    rows = [
        {"product": products["RUL-6204"].pk, "quantity": "100", "unit_price": "18.90"},
        {"product": products["CUR-A42"].pk, "quantity": "50", "unit_price": "18.50"},
    ]
    post_ok(
        client,
        reverse("purchasing:order_create"),
        {
            "supplier": supplier.pk,
            "currency": "RON",
            "owner": person("maria.pop").pk,
            "order_date": TODAY.isoformat(),
            "expected_date": (TODAY + datetime.timedelta(days=7)).isoformat(),
            **formset([{**row, "vat_rate": "21.00"} for row in rows]),
        },
    )
    order = PurchaseOrder.objects.latest("pk")
    post_ok(client, reverse("purchasing:order_send", args=[order.pk]))
    order.refresh_from_db()
    assert order.status == PurchaseOrder.Status.SENT

    # 2. Ion: prima tranșă, 100 rulmenți și 30 de curele.
    client.force_login(person("ion.marin"))
    receive(client, order, ["100", "30"])
    assert order.status == PurchaseOrder.Status.PARTIALLY_RECEIVED

    # 3. Elena: „Înregistrează factura” de pe comandă; liniile vin cu ce a sosit (100 și 30),
    #    ea le corectează după factura furnizorului (50 de curele) și validează: blocată.
    client.force_login(person("elena.dobre"))
    page = client.get(reverse("invoicing:invoice_create") + f"?comanda={order.pk}")
    prefilled = page.context["lines"]
    assert [form.initial["quantity"] for form in prefilled.forms] == ["100", "30"]
    response = client.post(
        reverse("invoicing:invoice_create"),
        {
            "supplier": supplier.pk,
            "supplier_invoice_number": "TEST-1",
            "currency": "RON",
            "invoice_date": TODAY.isoformat(),
            "due_date": (TODAY + datetime.timedelta(days=30)).isoformat(),
            "declared_net": "2815.00",
            "declared_vat": "591.15",
            "declared_total": "3406.15",
            "validate": "",
            **formset(
                [
                    {
                        "order_line": form.initial["order_line"].pk,
                        "quantity": quantity,
                        "unit_price": form.initial["unit_price"],
                        "vat_rate": "21.00",
                    }
                    for form, quantity in zip(prefilled.forms, ["100", "50"], strict=True)
                ]
            ),
        },
        follow=True,
    )
    assert response.redirect_chain, response.context["form"].errors  # salvată, nu respinsă
    invoice = Invoice.objects.latest("pk")
    assert invoice.status == Invoice.Status.BLOCKED
    assert [problem["code"] for problem in invoice.problems] == ["NOT_RECEIVED"]
    assert "facturat 50 buc, recepționat doar 30 buc: 20 buc nesosite" in response.content.decode()

    # 4. Andrei: „Trimite acum”; emailul Mariei are factura blocată, marcată NOU.
    client.force_login(person("andrei.ionescu"))
    mail.outbox.clear()
    post_ok(client, reverse("notifications:send_now"), {"recipient": ""})
    to_maria = next(m for m in mail.outbox if m.to == [person("maria.pop").email])
    assert f"[NOU] {invoice.number}" in to_maria.body

    # 5. Ion: restul de 20 de curele. 6. Factura devine singură „Potrivită”.
    client.force_login(person("ion.marin"))
    receive(client, order, ["20"])
    invoice.refresh_from_db()
    assert order.status == PurchaseOrder.Status.RECEIVED
    assert invoice.status == Invoice.Status.MATCHED
    client.force_login(person("elena.dobre"))
    html = client.get(invoice.get_absolute_url()).content.decode()
    assert "a devenit automat „Potrivită”" in html

    # 7. Elena: aprobă și plătește.
    post_ok(client, reverse("invoicing:invoice_approve", args=[invoice.pk]))
    post_ok(
        client,
        reverse("invoicing:invoice_pay", args=[invoice.pk]),
        {"paid_at": TODAY.isoformat(), "reference": "OP 1"},
    )
    invoice.refresh_from_db()
    assert invoice.status == Invoice.Status.PAID

    # 8. Andrei: istoricul spune toată povestea, cu cine a făcut fiecare pas.
    events = list(
        BusinessEvent.objects.filter(pk__gt=before)
        .exclude(event_type__startswith="auth.")
        .exclude(event_type="notifications.sent_now")
        .order_by("id")
        .values_list("event_type", "actor__username")
    )
    assert events == [
        ("order.sent", "maria.pop"),
        ("receipt.confirmed", "ion.marin"),
        ("invoice.validated", "elena.dobre"),
        ("receipt.confirmed", "ion.marin"),
        ("invoice.rechecked", "ion.marin"),
        ("invoice.approved", "elena.dobre"),
        ("invoice.paid", "elena.dobre"),
    ]
