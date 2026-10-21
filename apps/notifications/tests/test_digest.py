"""Conținutul rezumatului: subiect, secțiuni, marcajul NOU, link-uri, HTML sigur."""

import pytest

from apps.notifications.alerts import Alert, Section
from apps.notifications.digest import _subject, build_digest

pytestmark = pytest.mark.django_db


def alert(key, section=Section.BLOCKED, title="FAC-2026-0001 · Furnizor SRL"):
    return Alert(
        code="INVOICE_BLOCKED",
        section=section,
        key=key,
        title=title,
        detail="4 buc nesosite.",
        url="/facturi/1/",
    )


@pytest.fixture(autouse=True)
def _site(settings):
    settings.SITE_URL = "https://aprovizionare.test"


@pytest.mark.parametrize(
    ("total", "new", "expected"),
    [
        (1, 1, "Aprovizionare: un lucru de rezolvat (1 nou)"),
        (3, 3, "Aprovizionare: 3 lucruri de rezolvat (toate noi)"),
        (3, 1, "Aprovizionare: 3 lucruri de rezolvat (1 nou)"),
        (3, 2, "Aprovizionare: 3 lucruri de rezolvat (2 noi)"),
        (3, 0, "Aprovizionare: 3 lucruri de rezolvat"),
    ],
)
def test_subject(total, new, expected):
    assert _subject(total, new) == expected


def test_text_version(procurement_user):
    procurement_user.first_name = "Maria"

    digest = build_digest(procurement_user, [alert("A"), alert("B", Section.LATE)], ["B"])

    assert digest.text.startswith("Bună ziua, Maria!")
    assert "== ÎNTÂRZIERI ȘI SCADENȚE ==" in digest.text
    assert "[NOU] FAC-2026-0001" in digest.text
    assert "https://aprovizionare.test/facturi/1/" in digest.text  # link complet, nu relativ
    assert digest.text.index("ÎNTÂRZIERI") < digest.text.index("BLOCAJE")
    assert digest.keys == ["A", "B"]


def test_only_problems_missing_from_the_previous_digest_are_new(procurement_user):
    digest = build_digest(procurement_user, [alert("A"), alert("B")], previous_keys=["A"])

    assert digest.text.count("[NOU]") == 1
    assert digest.subject.endswith("(1 nou)")


def test_html_is_escaped(procurement_user):
    """Numele unui furnizor nu poate injecta HTML în email."""
    digest = build_digest(procurement_user, [alert("A", title="A & B <b>SRL</b>")])

    assert "A &amp; B &lt;b&gt;SRL&lt;/b&gt;" in digest.html
    assert "A & B <b>SRL</b>" in digest.text  # textul simplu rămâne citibil


def test_empty_sections_are_not_shown(procurement_user):
    digest = build_digest(procurement_user, [alert("A")])

    assert "BLOCAJE" in digest.text and "AZI" not in digest.text
