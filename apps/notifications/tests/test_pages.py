"""Pagina „Notificări trimise” și butonul „Trimite acum”."""

import datetime

import pytest
from django.core import mail
from django.urls import reverse

from apps.audit.models import BusinessEvent
from apps.notifications.models import DailyDigestRun, NotificationLog
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.warehouse.tests.scenarios import sent_order

pytestmark = pytest.mark.django_db

LOG = reverse("notifications:log")
SEND_NOW = reverse("notifications:send_now")


def notification(user, status=NotificationLog.Status.SENT, **extra):
    return NotificationLog.objects.create(
        recipient=user,
        email=user.email,
        subject=f"Aprovizionare: un lucru de rezolvat ({user.username})",
        body_text="Bună ziua!\nhttps://aprovizionare.test/comenzi/1/",
        status=status,
        **extra,
    )


@pytest.fixture
def late_order(procurement_user, warehouse_user):
    order = sent_order("10")
    PurchaseOrder.objects.filter(pk=order.pk).update(owner=procurement_user)
    PurchaseOrderLine.objects.filter(order=order).update(
        expected_date=datetime.date.today() - datetime.timedelta(days=2)
    )
    return order


# --- Cine ce vede -----------------------------------------------------------------------------


def test_everyone_sees_only_their_own(client, procurement_user, warehouse_user):
    mine = notification(procurement_user)
    notification(warehouse_user)
    client.force_login(procurement_user)

    response = client.get(LOG)

    assert list(response.context["object_list"]) == [mine]
    assert "Notificările mele" in response.content.decode()
    assert "Trimite acum" not in response.content.decode()


def test_someone_elses_email_is_not_found(client, procurement_user, warehouse_user):
    """404, nu 403: nu dezvăluim nici măcar că emailul există."""
    other = notification(warehouse_user)
    client.force_login(procurement_user)

    assert client.get(reverse("notifications:detail", args=[other.pk])).status_code == 404


def test_admin_sees_everything_and_the_daily_runs(
    client, admin_user, procurement_user, warehouse_user
):
    notification(procurement_user)
    notification(warehouse_user, status=NotificationLog.Status.FAILED, error="SMTP: refuzat")
    DailyDigestRun.objects.create(date=datetime.date(2026, 10, 21), sent=1, failed=1)
    client.force_login(admin_user)

    response = client.get(LOG)

    html = response.content.decode()
    assert len(response.context["object_list"]) == 2
    assert "Rezumatele zilnice" in html and "Trimite acum" in html
    assert 'title="SMTP: refuzat"' in html


def test_filter_failed(client, admin_user, procurement_user):
    notification(procurement_user)
    failed = notification(procurement_user, status=NotificationLog.Status.FAILED, error="x")
    client.force_login(admin_user)

    assert list(client.get(LOG, {"status": "FAILED"}).context["object_list"]) == [failed]


def test_detail_shows_the_content_with_links(client, procurement_user):
    mine = notification(procurement_user)
    client.force_login(procurement_user)

    html = client.get(reverse("notifications:detail", args=[mine.pk])).content.decode()

    assert '<a href="https://aprovizionare.test/comenzi/1/"' in html


def test_user_menu_links_to_my_notifications(client, warehouse_user):
    client.force_login(warehouse_user)

    assert f'href="{LOG}"' in client.get(reverse("dashboard:home")).content.decode()


# --- Trimite acum --------------------------------------------------------------------------


def test_send_now_to_everyone(client, admin_user, procurement_user, warehouse_user, late_order):
    client.force_login(admin_user)

    response = client.post(SEND_NOW, follow=True)

    assert len(mail.outbox) == 2  # Maria și Depozitul; Adminul nu primește
    logs = NotificationLog.objects.all()
    assert {log.kind for log in logs} == {NotificationLog.Kind.MANUAL}
    assert {log.triggered_by for log in logs} == {admin_user}
    assert "Rezumate trimise: 2" in response.content.decode()
    event = BusinessEvent.objects.get(event_type="notifications.sent_now")
    assert event.actor == admin_user and event.data["trimise"] == 2


def test_send_now_to_one_person(client, admin_user, procurement_user, warehouse_user, late_order):
    client.force_login(admin_user)

    client.post(SEND_NOW, {"recipient": warehouse_user.pk})

    assert [message.to for message in mail.outbox] == [[warehouse_user.email]]


def test_send_now_does_not_use_up_the_daily_digest(
    client, admin_user, procurement_user, warehouse_user, late_order
):
    """„Trimite acum” la 07:30 nu împiedică rezumatul zilnic de la 08:00."""
    client.force_login(admin_user)
    client.post(SEND_NOW)

    assert not DailyDigestRun.objects.exists()


def test_send_now_with_nothing_to_report(client, admin_user, accounting_user):
    client.force_login(admin_user)

    response = client.post(SEND_NOW, follow=True)

    assert mail.outbox == []
    assert "fără nimic de rezolvat" in response.content.decode()


def test_only_admin_can_send_now(client, procurement_user, late_order):
    client.force_login(procurement_user)

    assert client.post(SEND_NOW).status_code == 403
    assert mail.outbox == []
