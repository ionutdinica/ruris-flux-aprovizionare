"""Clientul BNR: descarcă fișierele XML cu cursurile de referință și le citește.

Nu știe nimic despre baza de date; întoarce doar o listă de cursuri publicate.
Salvarea și regulile de alegere a cursului sunt în services.py.

Fișierele BNR (https://curs.bnr.ro):
    nbrfxrates10days.xml          ultimele 10 zile de publicare (folosit zilnic)
    files/xml/years/nbrfxratesAAAA.xml   arhiva unui an (istoricul)

Formatul (prescurtat):
    <DataSet xmlns="https://www.bnr.ro/xsd">
      <Body>
        <Cube date="2026-10-20">
          <Rate currency="EUR">5.3285</Rate>
          <Rate currency="HUF" multiplier="100">1.4608</Rate>
        </Cube>
      </Body>
    </DataSet>
"""

import datetime
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from urllib.error import URLError
from urllib.request import Request, urlopen

from defusedxml import DefusedXmlException
from defusedxml.ElementTree import ParseError, fromstring
from django.conf import settings

TIMEOUT_SECONDS = 20
MAX_SIZE = 5 * 1024 * 1024  # o arhivă anuală are ~350 KB; orice e mult mai mare e suspect


class BnrError(Exception):
    """BNR nu a putut fi citit: rețea, server indisponibil sau răspuns neașteptat."""


@dataclass(frozen=True)
class PublishedRate:
    date: datetime.date
    currency: str
    rate: Decimal
    multiplier: int


def recent_url():
    return f"{settings.BNR_BASE_URL}/nbrfxrates10days.xml"


def year_url(year):
    return f"{settings.BNR_BASE_URL}/files/xml/years/nbrfxrates{year}.xml"


def download(url):
    """Conținutul fișierului de la `url`, sau BnrError."""
    request = Request(url, headers={"User-Agent": "RURIS-Aprovizionare/1.0"})
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            content = response.read(MAX_SIZE + 1)
    except (URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise BnrError(f"BNR nu răspunde ({reason}).") from exc
    if len(content) > MAX_SIZE:
        raise BnrError("Răspunsul BNR este neobișnuit de mare și a fost ignorat.")
    return content


def _local_name(tag):
    """„{https://www.bnr.ro/xsd}Cube” → „Cube”.

    BNR și-a schimbat deja o dată spațiul de nume (http → https); căutând după
    numele simplu al elementului, o nouă schimbare nu ne mai afectează.
    """
    return tag.rsplit("}", 1)[-1]


def parse_rates(content):
    """Lista cursurilor din fișierul XML; BnrError dacă nu e un fișier BNR valid.

    Important: dacă adresa se schimbă, BNR nu răspunde cu o eroare, ci redirecționează
    către prima pagină a site-ului (HTML, cod 200). De aceea orice răspuns care nu e
    exact formatul așteptat e tratat ca eroare, nu ca „nu există cursuri noi”.
    """
    try:
        # defusedxml refuză construcțiile XML periculoase (ex. entități care se
        # expandează la gigabytes); DTD-urile nu au ce căuta într-un fișier de cursuri.
        root = fromstring(content, forbid_dtd=True)
    except (ParseError, DefusedXmlException) as exc:
        raise BnrError("Răspunsul BNR nu este un fișier XML de cursuri valid.") from exc

    if _local_name(root.tag) != "DataSet":
        raise BnrError("Răspunsul BNR nu are formatul așteptat (lipsește DataSet).")

    rates = []
    for cube in root.iter():
        if _local_name(cube.tag) != "Cube":
            continue
        try:
            date = datetime.date.fromisoformat(cube.get("date", ""))
        except ValueError as exc:
            raise BnrError(f"Dată invalidă în fișierul BNR: {cube.get('date')!r}.") from exc
        for element in cube:
            if _local_name(element.tag) == "Rate":
                rates.append(_parse_rate(date, element))

    if not rates:
        raise BnrError("Fișierul BNR nu conține niciun curs.")
    return rates


def _parse_rate(date, element):
    currency = element.get("currency", "")
    try:
        rate = Decimal((element.text or "").strip())
        multiplier = int(element.get("multiplier", "1"))
    except (InvalidOperation, ValueError) as exc:
        raise BnrError(f"Curs invalid pentru {currency} din {date}.") from exc
    if len(currency) != 3 or not currency.isalpha() or rate <= 0 or multiplier <= 0:
        raise BnrError(f"Curs invalid pentru {currency!r} din {date}.")
    return PublishedRate(date, currency.upper(), rate, multiplier)
