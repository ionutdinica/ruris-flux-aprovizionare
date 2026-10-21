"""Alegerea cursului pentru o factură: regulile I-25…I-28 (docs/01-ipoteze.md)."""

from decimal import Decimal

import pytest

from apps.core.models import ImmutableRecordError
from apps.currency.bnr import PublishedRate
from apps.currency.models import ExchangeRate, RateSync
from apps.currency.services import (
    InvalidRateDate,
    RatePending,
    RateQuote,
    get_rate,
    is_covered,
    store_rates,
)

from .conftest import at, day, load

pytestmark = pytest.mark.django_db

D = Decimal


def quote(currency, date):
    q = get_rate(currency, day(date))
    return q.rate, q.date.isoformat()


def bnr_checked_at(text):
    """O interogare reușită a BNR, făcută la ora dată."""
    RateSync.objects.create(started_at=at(text), url="https://bnr.test/x.xml", success=True)


# --- I-25: cursul zilei sau ultimul publicat înainte -----------------------------------------


def test_ron_needs_no_rate(clock):
    assert get_rate("RON", day("2026-10-21")) == RateQuote("RON", D("1"), day("2026-10-21"))


def test_exact_day(clock):
    load("recent.xml")

    assert quote("EUR", "2026-10-20") == (D("5.3285"), "2026-10-20")
    assert quote("USD", "2026-10-14") == (D("4.7706"), "2026-10-14")


@pytest.mark.parametrize("invoice_day", ["2026-10-17", "2026-10-18"])  # sâmbătă, duminică
def test_weekend_uses_friday(clock, invoice_day):
    load("recent.xml")

    assert quote("EUR", invoice_day) == (D("5.3368"), "2026-10-16")


@pytest.mark.parametrize(
    ("invoice_day", "rate_day", "rate"),
    [
        ("2025-12-25", "2025-12-24", "5.0890"),  # Crăciunul
        ("2025-12-28", "2025-12-24", "5.0890"),  # 25-28: sărbătoare + weekend
        ("2026-01-01", "2025-12-31", "5.0985"),  # Anul Nou: cursul din anul anterior
        ("2026-01-04", "2025-12-31", "5.0985"),
        ("2026-01-07", "2026-01-05", "5.0905"),  # Boboteaza și Sf. Ioan (6-7 ian.)
    ],
)
def test_holidays_use_last_published_rate(clock, invoice_day, rate_day, rate):
    load("year2025.xml")
    load("year2026.xml")

    assert quote("EUR", invoice_day) == (D(rate), rate_day)


def test_multiplier_is_kept_and_used_in_conversion(clock):
    load("recent.xml")

    huf = get_rate("HUF", day("2026-10-20"))

    assert (huf.rate, huf.multiplier) == (D("1.4608"), 100)
    assert huf.to_ron(D("1000")) == D("14.61")  # 1000 HUF × 1,4608 / 100 = 14,608


def test_conversion_rounds_half_up_like_accounting():
    """2,005 → 2,01 (rotunjire comercială), nu 2,00 (rotunjirea „bancherului”)."""
    assert RateQuote("EUR", D("2.0050"), day("2026-10-20")).to_ron(D("1")) == D("2.01")


# --- I-27: fără facturi din viitor ------------------------------------------------------------


def test_future_date_is_rejected(clock):
    load("recent.xml")

    with pytest.raises(InvalidRateDate, match="viitor"):
        get_rate("EUR", day("2026-10-22"))


# --- I-26: cursul de azi, înainte și după publicare -------------------------------------------


def test_today_before_publication_waits(clock):
    load("recent.xml")  # ultimul curs: 20.10; azi e 21.10, ora 10:00

    with pytest.raises(RatePending, match="13:00"):
        get_rate("EUR", day("2026-10-21"))


def test_today_after_publication_uses_todays_rate(clock):
    load("recent.xml")
    # BNR a publicat la 13:00, job-ul a adus cursul.
    store_rates([PublishedRate(day("2026-10-21"), "EUR", D("5.3300"), 1)])
    clock.set("2026-10-21 13:20")

    assert quote("EUR", "2026-10-21") == (D("5.3300"), "2026-10-21")


def test_bnr_checked_too_early_is_not_proof_of_a_holiday(clock):
    """O interogare la 13:30 fără cursul zilei nu dovedește nimic: BNR poate întârzia."""
    load("recent.xml")
    bnr_checked_at("2026-10-21 13:30")
    clock.set("2026-10-21 13:45")

    with pytest.raises(RatePending):
        get_rate("EUR", day("2026-10-21"))


def test_holiday_known_after_deadline_uses_previous_rate(clock):
    """După ora 14:00, BNR interogat cu succes și tot fără curs → zi fără publicare."""
    load("recent.xml")
    bnr_checked_at("2026-10-21 14:05")
    clock.set("2026-10-21 14:10")

    assert quote("EUR", "2026-10-21") == (D("5.3285"), "2026-10-20")


def test_weekend_is_known_without_asking_bnr(clock):
    """Sâmbăta BNR nu publică niciodată: cursul de vineri se aplică imediat."""
    load("recent.xml", until="2026-10-16")
    clock.set("2026-10-17 09:00")

    assert quote("EUR", "2026-10-17") == (D("5.3368"), "2026-10-16")


def test_monday_morning_waits_for_mondays_rate(clock):
    load("recent.xml", until="2026-10-16")
    clock.set("2026-10-19 09:00")

    assert is_covered(day("2026-10-18"))  # duminica e acoperită de cursul de vineri
    with pytest.raises(RatePending, match="13:00"):
        get_rate("EUR", day("2026-10-19"))


# --- I-28: BNR indisponibil / istoric lipsă ---------------------------------------------------


def test_bnr_unreachable_waits(clock):
    """Ieri (20.10) n-am reușit să aducem cursul: factura de ieri așteaptă, nu primește
    cursul de alaltăieri ca și cum ieri ar fi fost sărbătoare."""
    load("recent.xml", until="2026-10-19")
    RateSync.objects.create(
        started_at=at("2026-10-20 15:00"),
        url="https://bnr.test/x.xml",
        success=False,
        error="BNR nu răspunde",
    )
    clock.set("2026-10-21 10:00")

    with pytest.raises(RatePending, match="se reîncearcă automat"):
        get_rate("EUR", day("2026-10-20"))


def test_empty_history_waits(clock):
    with pytest.raises(RatePending):
        get_rate("EUR", day("2026-10-20"))


def test_gap_in_history_is_not_bridged_with_an_old_rate(clock):
    """Istoric doar din ianuarie și octombrie: o factură din mai NU primește cursul din
    ianuarie (prea vechi), ci așteaptă încărcarea istoricului."""
    load("year2026.xml")

    with pytest.raises(RatePending, match="--year 2026"):
        get_rate("EUR", day("2026-05-15"))


def test_rates_are_immutable(clock):
    load("recent.xml")
    rate = ExchangeRate.objects.first()
    rate.rate = D("9.9999")

    with pytest.raises(ImmutableRecordError):
        rate.save()
    with pytest.raises(ImmutableRecordError):
        ExchangeRate.objects.all().delete()
