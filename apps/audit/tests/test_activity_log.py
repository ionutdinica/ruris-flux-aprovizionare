"""Pagina „Jurnal de activitate” și secțiunea „Istoric” a unui document."""

from datetime import timedelta

import pytest
from auditlog.context import set_actor
from django.contrib.contenttypes.models import ContentType
from django.template import Context, Template
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory
from apps.audit.models import BusinessEvent
from apps.audit.services import record_event
from apps.audit.timeline import CHANGE, EVENT, TimelineFilters, history_for, timeline_rows

pytestmark = pytest.mark.django_db

URL = reverse("audit:log")
T = BusinessEvent.Type


def sources(filters=None):
    return [row["source"] for row in timeline_rows(filters or TimelineFilters())]


# --- Cronologia unificată -------------------------------------------------------------


def test_timeline_merges_both_logs_newest_first(admin_user):
    with set_actor(admin_user):
        user = UserFactory()  # 1. modificare de date (creare)
    record_event(T.LOGIN, "Eveniment", actor=user)  # 2. eveniment, mai nou

    rows = list(timeline_rows(TimelineFilters()))

    assert [r["source"] for r in rows][:2] == [EVENT, CHANGE]
    assert rows[0]["timestamp"] >= rows[1]["timestamp"]


def test_filter_only_data_changes(admin_user):
    record_event(T.LOGIN, "Eveniment", actor=admin_user)

    assert set(sources(TimelineFilters(kind=CHANGE))) == {CHANGE}


def test_filter_by_event_type(admin_user):
    record_event(T.LOGIN, "Intrare", actor=admin_user)
    record_event(T.LOGOUT, "Ieșire", actor=admin_user)

    rows = list(timeline_rows(TimelineFilters(kind=T.LOGOUT)))

    assert len(rows) == 1
    assert BusinessEvent.objects.get(pk=rows[0]["id"]).event_type == T.LOGOUT


def test_filter_by_actor(procurement_user, warehouse_user):
    record_event(T.LOGIN, "A", actor=procurement_user)
    record_event(T.LOGIN, "B", actor=warehouse_user)

    rows = list(timeline_rows(TimelineFilters(actor_id=warehouse_user.pk)))

    assert [BusinessEvent.objects.get(pk=r["id"]).message for r in rows] == ["B"]


def test_filter_by_date(admin_user):
    record_event(T.LOGIN, "Azi", actor=admin_user)
    tomorrow = timezone.localdate() + timedelta(days=1)

    assert sources(TimelineFilters(date_from=tomorrow)) == []
    assert sources(TimelineFilters(date_to=tomorrow))


def test_history_for_single_document(admin_user, procurement_user, warehouse_user):
    with set_actor(admin_user):
        warehouse_user.role = User.Role.ACCOUNTING
        warehouse_user.save()
    record_event(T.LOGIN, "Alt document", actor=admin_user, target=procurement_user)

    entries = history_for(warehouse_user)

    assert entries  # creare + modificare rol
    assert all(e.title.endswith(f"«{warehouse_user}»") for e in entries)
    assert entries[0].changes == [("rol", "Depozit", "Contabilitate")]


def test_boolean_changes_are_readable(admin_user, warehouse_user):
    with set_actor(admin_user):
        warehouse_user.is_active = False
        warehouse_user.save()

    assert history_for(warehouse_user)[0].changes == [("activ", "Da", "Nu")]


# --- Pagina -----------------------------------------------------------------------------


@pytest.mark.parametrize("role", [User.Role.PROCUREMENT, User.Role.WAREHOUSE, User.Role.ACCOUNTING])
def test_only_admin_can_open_the_log(client, role):
    client.force_login(UserFactory(role=role))

    assert client.get(URL).status_code == 403


def test_page_shows_changes_and_events(client, admin_user):
    with set_actor(admin_user):
        target = UserFactory(first_name="Ana", last_name="Pop", role=User.Role.WAREHOUSE)
        target.role = User.Role.ACCOUNTING
        target.save()
    record_event(T.LOGIN_FAILED, "Autentificare eșuată pentru „hacker”.", data={"utilizator": "x"})
    client.force_login(admin_user)

    html = client.get(URL).content.decode()

    assert "Utilizator «Ana Pop»" in html
    assert "Depozit" in html and "Contabilitate" in html  # valori vechi → noi, traduse
    assert "Autentificare eșuată" in html


def test_password_value_never_appears(client, admin_user, procurement_user):
    procurement_user.set_password("parola-noua-secreta-123")
    procurement_user.save()
    client.force_login(admin_user)

    html = client.get(URL).content.decode()

    assert "********" in html
    assert procurement_user.password not in html  # nici măcar valoarea criptată


def test_pagination(client, admin_user):
    for i in range(30):
        record_event(T.LOGOUT, f"Eveniment {i}", actor=admin_user)
    client.force_login(admin_user)  # emite și el un eveniment, dar de tip LOGIN

    first = client.get(URL, {"kind": T.LOGOUT})
    second = client.get(URL, {"kind": T.LOGOUT, "page": 2})

    assert first.context["page"].paginator.count == 30
    assert len(first.context["entries"]) == 25
    assert len(second.context["entries"]) == 5


def test_htmx_request_returns_only_results(client, admin_user):
    client.force_login(admin_user)

    response = client.get(URL, headers={"HX-Request": "true"})

    html = response.content.decode()
    assert "<html" not in html
    assert "înregistrări" in html


def test_invalid_filters_show_everything_with_warning(client, admin_user):
    client.force_login(admin_user)

    response = client.get(URL, {"date_from": "2026-05-10", "date_to": "2026-05-01"})

    assert response.status_code == 200
    assert "Filtre invalide" in response.content.decode()


def test_document_history_link(client, admin_user, warehouse_user):
    client.force_login(admin_user)
    ct = ContentType.objects.get_for_model(User)

    response = client.get(URL, {"ct": ct.pk, "obj": warehouse_user.pk})

    assert response.context["document"] == warehouse_user
    assert "Istoricul documentului" in response.content.decode()


def test_menu_item_is_now_active(client, admin_user):
    client.force_login(admin_user)

    html = client.get(URL).content.decode()

    assert f'href="{URL}"' in html  # nu mai e „în curând”


# --- Secțiunea „Istoric” (template tag) -------------------------------------------------


def test_object_history_tag(admin_user, warehouse_user):
    with set_actor(admin_user):
        warehouse_user.first_name = "Nume nou"
        warehouse_user.save()
    template = Template("{% load audit %}{% object_history obj %}")

    html = template.render(Context({"obj": warehouse_user, "user": admin_user}))

    assert "Istoric" in html
    assert "Nume nou" in html
    assert "Istoricul complet" in html  # Admin vede link-ul spre jurnal


def test_object_history_tag_hides_full_log_link_for_non_admin(procurement_user, warehouse_user):
    template = Template("{% load audit %}{% object_history obj %}")

    html = template.render(Context({"obj": warehouse_user, "user": procurement_user}))

    assert "Istoricul complet" not in html
