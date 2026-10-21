"""Datele demo: fiecare situație din cerință există, iar istoria e coerentă.

Generarea durează câteva secunde, așa că se face o singură dată pentru tot fișierul,
într-o tranzacție anulată la final (datele nu ajung în celelalte teste).
"""

import datetime

import pytest
from auditlog.models import LogEntry
from django.db import transaction
from django.utils import timezone

from apps.audit.models import BusinessEvent
from apps.budgets.services import statuses as budget_statuses
from apps.dashboard.charts import late_orders_trend, on_time_by_supplier
from apps.demo.seed import HISTORY_DAYS
from apps.demo.testing import seed_demo_for_tests
from apps.invoicing.models import Invoice
from apps.notifications.alerts import collect
from apps.notifications.models import DailyDigestRun, NotificationLog
from apps.purchasing.models import PurchaseOrder
from apps.warehouse.models import Discrepancy, GoodsReceipt, StockMovement

TODAY = timezone.localdate()
S = Invoice.Status


@pytest.fixture(scope="module")
def demo(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock(), transaction.atomic():
        yield seed_demo_for_tests()
        transaction.set_rollback(True)


pytestmark = pytest.mark.django_db


def problem_codes(invoice):
    return {problem["code"] for problem in invoice.problems}


def story(seeder, label):
    return seeder.scenarios[label]


# --- Fiecare situație din cerință -------------------------------------------------------------


def test_two_deliveries_then_paid(demo):
    seeder, _ = demo
    order = story(seeder, "Livrare în două tranșe, facturată și plătită").order

    assert order.receipts.count() == 2
    assert order.lines.get(product__code="RUL-6204")  # recepționată în două părți
    [invoice] = Invoice.objects.filter(lines__order_line__order=order).distinct()
    assert invoice.status == S.PAID


def test_partial_delivery_with_full_invoice_is_blocked_and_late(demo):
    seeder, _ = demo
    s = story(seeder, "Livrare parțială, factură pe tot (blocată: marfă nesosită)")

    invoice = Invoice.objects.get(pk=s.invoices[-1].pk)
    assert invoice.status == S.BLOCKED and problem_codes(invoice) == {"NOT_RECEIVED"}
    assert any(a.code == "ORDER_LATE" and a.key.endswith(str(s.order.pk)) for a in collect())


def test_wrong_price_is_blocked(demo):
    seeder, _ = demo
    invoice = story(seeder, "Factură cu preț diferit de comandă (blocată)").invoices[-1]

    assert problem_codes(Invoice.objects.get(pk=invoice.pk)) == {"PRICE_MISMATCH"}


def test_unordered_and_over_delivered_goods_wait_in_quarantine(demo):
    open_ = Discrepancy.objects.filter(status=Discrepancy.Status.OPEN)

    assert {d.type for d in open_} == {Discrepancy.Type.UNORDERED, Discrepancy.Type.OVER_DELIVERY}
    resolved = Discrepancy.objects.filter(status=Discrepancy.Status.RESOLVED)
    assert {d.resolution for d in resolved} == {"ATTACHED", "RETURNED"}


def test_eur_invoice_from_a_saturday_uses_fridays_rate(demo):
    seeder, _ = demo
    invoice = Invoice.objects.get(
        pk=story(seeder, "Factură în EUR emisă sâmbăta (curs de vineri)").invoices[-1].pk
    )

    assert invoice.currency == "EUR" and invoice.invoice_date.weekday() == 5
    assert invoice.exchange_rate_date == invoice.invoice_date - datetime.timedelta(days=1)
    assert invoice.status == S.APPROVED and invoice.total_ron > invoice.declared_total


def test_forced_and_rejected_invoices(demo):
    forced = Invoice.objects.exclude(override_reason="")
    rejected = Invoice.objects.filter(status=S.REJECTED)

    assert forced.count() == 1 and forced.get().status == S.APPROVED
    assert rejected.count() == 1 and "stornarea" in rejected.get().rejection_reason
    assert BusinessEvent.objects.filter(event_type="invoice.force_approved").exists()


def test_every_alert_type_appears_somewhere(demo):
    """Panoul și emailul au ce să arate: toate tipurile de probleme din docs/05 §4."""
    codes = {alert.code for alert in collect()}

    assert codes >= {
        "ORDER_LATE",
        "DELIVERY_EXPECTED_TODAY",
        "DISCREPANCY_OPEN",
        "INVOICE_BLOCKED",
        "INVOICE_MATCHED_WAITING",
        "INVOICE_DUE_SOON",
        "INVOICE_OVERDUE",
    }


def test_budgets_one_almost_used_one_exceeded_with_a_reason(demo):
    by_supplier = {s.budget.supplier.name: s for s in budget_statuses(TODAY.year)}

    assert len(by_supplier) == 8
    assert by_supplier["Plastic Injecție Dolj SRL"].level == "warning"
    assert by_supplier["Componente Electrice Banat SRL"].level == "over"
    assert by_supplier["Rulmenți Oltenia SRL"].percent < 70  # loc pentru ciclul din README
    others = [s.level for name, s in by_supplier.items() if "Plastic" not in name]
    assert others.count("over") == 1 and "warning" not in others
    [over] = PurchaseOrder.objects.exclude(budget_override_reason="")
    assert over.supplier.name == "Componente Electrice Banat SRL"
    assert BusinessEvent.objects.get(event_type="order.sent_over_budget").target == over
    assert {"BUDGET_ALMOST_USED", "BUDGET_EXCEEDED"} <= {alert.code for alert in collect()}


# --- O istorie coerentă -----------------------------------------------------------------------


def test_volume_and_shape(demo):
    assert 40 <= PurchaseOrder.objects.count() <= 70
    assert Invoice.objects.filter(status=S.PAID).count() >= 15
    assert StockMovement.objects.filter(type="CONSUMPTION").exists()
    suppliers = on_time_by_supplier(TODAY)
    assert len(suppliers.labels) >= 6 and min(suppliers.datasets[0]["data"]) < 80
    assert max(late_orders_trend(TODAY).datasets[0]["data"]) >= 1


def test_document_numbers_follow_time(demo):
    """Numerele cresc odată cu data: agenda rulează în ordine cronologică."""
    receipts = list(
        GoodsReceipt.objects.exclude(number="")
        .order_by("number")
        .values_list("receipt_date", flat=True)
    )
    invoices = list(Invoice.objects.order_by("number").values_list("created_at", flat=True))

    assert receipts == sorted(receipts)
    assert invoices == sorted(invoices)


def test_audit_trail_is_in_the_past_and_signed(demo):
    """Jurnalul arată acțiunile la data lor, făcute de oameni (nu „sistem” sau „azi”)."""
    order = PurchaseOrder.objects.order_by("order_date").first()
    created = LogEntry.objects.get_for_object(order).order_by("timestamp").first()

    assert created.timestamp.date() <= TODAY - datetime.timedelta(days=HISTORY_DAYS - 7)
    assert created.actor.username in {"maria.pop", "radu.vasile"}
    assert not LogEntry.objects.filter(timestamp__date__gte=TODAY).exists()


def test_recent_daily_digests_were_sent(demo):
    seeder, _ = demo
    # Ultimele 3 zile lucrătoare, plus azi dacă generarea a avut loc după ora rezumatului.
    assert DailyDigestRun.objects.count() == 3 + seeder.digest_today
    assert NotificationLog.objects.filter(status=NotificationLog.Status.SENT).exists()


def test_summary_lists_the_situations(demo):
    _, log = demo

    assert any("situații din cerință" in line for line in log)
    assert any("facturi:" in line for line in log)
