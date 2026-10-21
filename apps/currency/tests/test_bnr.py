"""Clientul BNR: citirea fișierelor XML și tratarea răspunsurilor greșite."""

import io
from decimal import Decimal
from urllib.error import URLError

import pytest

from apps.currency import bnr

from .conftest import DATA, day

# Formatul exact al fișierului zilnic (pe un singur rând), cu spațiul de nume VECHI
# (http://). Parserul trebuie să-l citească la fel ca pe cel nou (https://).
OLD_NAMESPACE_DAILY = (
    b'<?xml version="1.0" encoding="utf-8"?><DataSet xmlns="http://www.bnr.ro/xsd">'
    b"<Header><PublishingDate>2024-03-15</PublishingDate></Header><Body>"
    b'<Cube date="2024-03-15"><Rate currency="EUR">4.9725</Rate>'
    b'<Rate currency="JPY" multiplier="100">3.0712</Rate></Cube></Body></DataSet>'
)


def test_parses_real_format():
    rates = bnr.parse_rates((DATA / "recent.xml").read_bytes())

    assert len(rates) == 7 * 3  # 7 zile × 3 monede
    eur = next(r for r in rates if r.currency == "EUR" and r.date == day("2026-10-20"))
    assert eur.rate == Decimal("5.3285") and eur.multiplier == 1


def test_reads_multiplier_and_ignores_namespace():
    rates = bnr.parse_rates(OLD_NAMESPACE_DAILY)

    assert [(r.currency, r.rate, r.multiplier) for r in rates] == [
        ("EUR", Decimal("4.9725"), 1),
        ("JPY", Decimal("3.0712"), 100),
    ]


@pytest.mark.parametrize(
    "content",
    [
        # Ce primim când adresa BNR se schimbă: prima pagină a site-ului, cu cod 200.
        b"<!doctype html><html><head><title>BNR</title></head><body><p>EUR</p></body></html>",
        b"<html><body>Mentenanta</body></html>",  # XML valid, dar nu e fișier de cursuri
        b"",
        b'<DataSet xmlns="https://www.bnr.ro/xsd"><Body></Body></DataSet>',  # fără cursuri
        b'<DataSet><Cube date="ieri"><Rate currency="EUR">5</Rate></Cube></DataSet>',
        b'<DataSet><Cube date="2026-10-20"><Rate currency="EUR">abc</Rate></Cube></DataSet>',
        b'<DataSet><Cube date="2026-10-20"><Rate currency="EUR">-5</Rate></Cube></DataSet>',
        b'<DataSet><Cube date="2026-10-20"><Rate currency="E1">5</Rate></Cube></DataSet>',
        b'<DataSet><Cube date="2026-10-20"><Rate currency="EUR" multiplier="0">5</Rate>'
        b"</Cube></DataSet>",
    ],
    ids=[
        "pagina-html",
        "alt-xml",
        "gol",
        "fara-cursuri",
        "data",
        "curs",
        "negativ",
        "moneda",
        "multiplicator",
    ],
)
def test_anything_but_a_valid_rates_file_is_an_error(content):
    with pytest.raises(bnr.BnrError):
        bnr.parse_rates(content)


def test_refuses_dangerous_xml():
    """„Billion laughs”: câteva rânduri de XML care s-ar expanda la gigabytes în memorie."""
    bomb = (
        b'<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol">'
        b'<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">]>'
        b"<DataSet>&lol2;</DataSet>"
    )
    with pytest.raises(bnr.BnrError):
        bnr.parse_rates(bomb)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def test_download_returns_content(monkeypatch):
    monkeypatch.setattr(bnr, "urlopen", lambda request, timeout: FakeResponse(b"<DataSet/>"))

    assert bnr.download("https://curs.bnr.ro/nbrfxrates10days.xml") == b"<DataSet/>"


def test_download_network_error_becomes_bnr_error(monkeypatch):
    def offline(request, timeout):
        raise URLError("Name or service not known")

    monkeypatch.setattr(bnr, "urlopen", offline)

    with pytest.raises(bnr.BnrError, match="BNR nu răspunde"):
        bnr.download("https://curs.bnr.ro/nbrfxrates10days.xml")


def test_download_refuses_huge_responses(monkeypatch):
    huge = FakeResponse(b"x" * (bnr.MAX_SIZE + 1))
    monkeypatch.setattr(bnr, "urlopen", lambda request, timeout: huge)

    with pytest.raises(bnr.BnrError, match="neobișnuit de mare"):
        bnr.download("https://curs.bnr.ro/nbrfxrates10days.xml")


def test_urls_follow_the_setting(settings):
    settings.BNR_BASE_URL = "https://alt-server.ro"

    assert bnr.recent_url() == "https://alt-server.ro/nbrfxrates10days.xml"
    assert bnr.year_url(2025) == "https://alt-server.ro/files/xml/years/nbrfxrates2025.xml"


def test_tests_cannot_reach_the_network():
    """Plasa de siguranță din conftest.py: un apel real ar pica imediat."""
    with pytest.raises(AssertionError, match="rețeaua"):
        bnr.download("https://curs.bnr.ro/nbrfxrates.xml")
