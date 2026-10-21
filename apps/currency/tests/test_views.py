"""Pagina „Cursuri BNR”: istoric, starea cursului de azi, „ce curs se aplică?”, actualizare."""

from decimal import Decimal

import pytest
from django.urls import reverse

from apps.currency.models import RateSync

from .conftest import at, load

pytestmark = pytest.mark.django_db

LIST = reverse("currency:rate_list")
LOOKUP = reverse("currency:rate_lookup")
REFRESH = reverse("currency:rate_refresh")


@pytest.fixture
def rates(clock):
    load("recent.xml")


def test_history_with_daily_change(client, accounting_user, rates):
    client.force_login(accounting_user)

    response = client.get(LIST)

    rows = response.context["object_list"]
    assert [r.date.isoformat() for r in rows][:2] == ["2026-10-20", "2026-10-19"]
    assert rows[0].change == Decimal("0.0013")  # 5,3285 − 5,3272
    assert rows[len(rows) - 1].change is None  # cel mai vechi nu are cu ce compara
    assert "5,3285" in response.content.decode()


def test_other_currency_and_unknown_currency(client, procurement_user, rates):
    client.force_login(procurement_user)

    huf = client.get(LIST, {"moneda": "huf"})
    unknown = client.get(LIST, {"moneda": "XYZ"})

    assert huf.context["currency"] == "HUF"
    assert "100 HUF =" in huf.content.decode()
    assert unknown.context["currency"] == "EUR"


def test_today_card_shows_pending_before_publication(client, accounting_user, rates):
    client.force_login(accounting_user)

    html = client.get(LIST).content.decode()

    assert "În așteptare" in html
    assert "13:00" in html


def test_lookup_explains_weekend_rate(client, accounting_user, rates):
    client.force_login(accounting_user)

    html = client.get(LOOKUP, {"data": "2026-10-17", "moneda": "EUR"}).content.decode()

    assert "5,3368" in html and "16.10.2026" in html
    assert "nu a publicat curs în ziua facturii" in html


def test_lookup_also_works_without_javascript(client, accounting_user, rates):
    client.force_login(accounting_user)

    response = client.get(LIST, {"data": "2026-10-20"})

    assert response.context["quote"].rate == Decimal("5.3285")


@pytest.mark.parametrize(
    ("date", "expected"), [("2026-11-01", "viitor"), ("2026-10-21", "13:00"), ("ieri", "")]
)
def test_lookup_errors(client, accounting_user, rates, date, expected):
    client.force_login(accounting_user)

    html = client.get(LOOKUP, {"data": date}).content.decode()

    assert expected in html


def test_refresh_now(client, accounting_user, clock, fake_bnr):
    clock.set("2026-10-21 13:20")
    client.force_login(accounting_user)

    response = client.post(REFRESH, {"moneda": "USD"}, follow=True)

    assert response.redirect_chain[-1][0] == f"{LIST}?moneda=USD"
    assert "Cursurile au fost actualizate" in response.content.decode()
    assert RateSync.objects.filter(triggered_by=accounting_user).count() == 3


def test_refresh_failure_is_explained(client, accounting_user, rates, fake_bnr):
    fake_bnr.down = True
    client.force_login(accounting_user)

    html = client.post(REFRESH, follow=True).content.decode()

    assert "Actualizarea a eșuat" in html
    assert "Ultima încercare de actualizare" in html  # avertismentul rămâne pe pagină


def test_procurement_cannot_refresh(client, procurement_user, fake_bnr):
    client.force_login(procurement_user)

    assert client.post(REFRESH).status_code == 403
    assert fake_bnr.calls == []


def test_refresh_button_only_for_allowed_roles(client, procurement_user, accounting_user, rates):
    client.force_login(procurement_user)
    assert REFRESH not in client.get(LIST).content.decode()

    client.force_login(accounting_user)
    assert REFRESH in client.get(LIST).content.decode()


def test_failed_sync_banner(client, accounting_user, rates):
    RateSync.objects.create(
        started_at=at("2026-10-21 09:00"),
        url="https://bnr.test/x.xml",
        success=False,
        error="BNR nu răspunde (timed out).",
    )
    client.force_login(accounting_user)

    html = client.get(LIST).content.decode()

    assert "21.10.2026 09:00" in html and "timed out" in html
