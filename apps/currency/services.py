"""Cursul valutar: salvarea cursurilor BNR și alegerea cursului pentru o factură.

Regulile (docs/01-ipoteze.md, I-25…I-28; docs/05-reguli-business.md, §2):
- se folosește cursul BNR din ziua facturii; dacă BNR nu a publicat în acea zi
  (weekend, sărbătoare), ultimul curs publicat înainte (I-25);
- dacă nu știm încă sigur care e cursul zilei (BNR publică în jurul orei 13:00 sau
  nu răspunde), factura AȘTEAPTĂ; nu primește niciodată un curs ghicit (I-26, I-28);
- facturile cu dată în viitor sunt respinse (I-27).
"""

import datetime
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.core.models import Currency

from . import bnr
from .models import ExchangeRate, RateSync
from .signals import rates_synced

# BNR publică în jurul orei 13:00. Înainte de această oră nu are rost să întrebăm.
PUBLICATION_TIME = datetime.time(13, 0)
# Dacă după această oră BNR tot nu are curs pentru ziua respectivă, nu mai publică
# în acea zi (sărbătoare legală). Marja de o oră acoperă publicările întârziate.
PUBLICATION_DEADLINE = datetime.time(14, 0)
# Fișierul zilnic acoperă ultimele 10 zile de publicare (~2 săptămâni). Dacă ultimul
# curs știut e mai vechi, completăm golul din arhivele anuale.
RECENT_FILE_DAYS = 10
# Cea mai lungă pauză reală de publicare (sărbătorile de iarnă + weekend) e de ~5 zile.
# Un curs mai vechi de atât față de data facturii înseamnă istoric lipsă, nu pauză.
MAX_RATE_AGE_DAYS = 7

CENT = Decimal("0.01")


class RateError(Exception):
    """Cursul nu poate fi stabilit (deocamdată). Mesajul e pentru utilizator."""


class RatePending(RateError):
    """Cursul nu e cunoscut ÎNCĂ: factura așteaptă și va fi reluată automat (I-26, I-28)."""


class InvalidRateDate(RateError):
    """Data nu poate avea curs: e în viitor (I-27)."""


@dataclass(frozen=True)
class RateQuote:
    """Cursul aplicabil: valoarea și data EFECTIVĂ a cursului (poate fi anterioară)."""

    currency: str
    rate: Decimal  # lei pentru `multiplier` unități
    date: datetime.date
    multiplier: int = 1

    def to_ron(self, amount):
        """Suma în lei, rotunjită comercial la bani (ROUND_HALF_UP, ca în contabilitate)."""
        return (amount * self.rate / self.multiplier).quantize(CENT, rounding=ROUND_HALF_UP)


def local_now():
    """Ora curentă (fusul orar al aplicației). Un singur loc, ca testele să o poată fixa."""
    return timezone.localtime()


def _at(day, time):
    return timezone.make_aware(datetime.datetime.combine(day, time))


def latest_rate_date():
    return ExchangeRate.objects.aggregate(latest=Max("date"))["latest"]


def is_covered(day, *, now=None):
    """Știm SIGUR care e cursul valabil pentru `day`?

    Dacă avem un curs din `day` sau de după, da. Dacă nu, lipsa cursului poate
    însemna două lucruri foarte diferite: BNR nu l-a publicat ÎNCĂ sau nu îl
    publică deloc (weekend, sărbătoare). Le deosebim astfel:
      - sâmbăta și duminica BNR nu publică niciodată;
      - altfel, ne bazăm pe o interogare reușită a BNR făcută după ora-limită a zilei.
    """
    now = now or local_now()
    if day > now.date():
        return False
    if ExchangeRate.objects.filter(date__gte=day).exists():
        return True
    latest = latest_rate_date()
    if latest is None:
        return False  # istoric gol: nu știm nimic
    gap = (latest + datetime.timedelta(days=n) for n in range(1, (day - latest).days + 1))
    if all(d.weekday() >= 5 for d in gap):  # 5, 6 = sâmbătă, duminică
        return True
    return RateSync.objects.filter(
        success=True, started_at__gte=_at(day, PUBLICATION_DEADLINE)
    ).exists()


def get_rate(currency, day, *, now=None):
    """Cursul aplicabil unei facturi în `currency` din data `day` → RateQuote.

    Ridică RatePending dacă trebuie așteptat și InvalidRateDate pentru o dată din viitor.
    """
    now = now or local_now()
    if currency == Currency.RON:
        return RateQuote(Currency.RON, Decimal("1"), day)
    if day > now.date():
        raise InvalidRateDate(f"Data {day:%d.%m.%Y} este în viitor (I-27).")
    if not is_covered(day, now=now):
        if day == now.date() and now.time() < PUBLICATION_DEADLINE:
            raise RatePending(
                f"BNR publică cursul zilei {day:%d.%m.%Y} în jurul orei 13:00; "
                "factura se finalizează automat după publicare."
            )
        raise RatePending(
            f"Cursul BNR pentru {day:%d.%m.%Y} nu a putut fi încă obținut; se reîncearcă automat."
        )

    rate = ExchangeRate.objects.filter(currency=currency, date__lte=day).order_by("-date").first()
    if rate is None or (day - rate.date).days > MAX_RATE_AGE_DAYS:
        raise RatePending(
            f"Lipsește istoricul cursurilor {currency} pentru {day:%d.%m.%Y}. Se încarcă "
            f"cu: python manage.py fetch_bnr_rates --year {day.year}"
        )
    return RateQuote(currency, rate.rate, rate.date, rate.multiplier)


# --- Actualizarea cursurilor ------------------------------------------------------------


def store_rates(published):
    """Salvează cursurile noi; cele deja salvate sunt ignorate. Întoarce câte sunt noi."""
    with transaction.atomic():
        before = ExchangeRate.objects.count()
        ExchangeRate.objects.bulk_create(
            [
                ExchangeRate(date=r.date, currency=r.currency, rate=r.rate, multiplier=r.multiplier)
                for r in published
            ],
            ignore_conflicts=True,  # (moneda, data) existente rămân neschimbate
        )
        return ExchangeRate.objects.count() - before


def _sync_file(url, user):
    """Descarcă și salvează un fișier BNR; fiecare încercare rămâne în RateSync."""
    started_at = local_now()
    try:
        published = bnr.parse_rates(bnr.download(url))
    except bnr.BnrError as exc:
        return RateSync.objects.create(
            started_at=started_at, url=url, success=False, error=str(exc), triggered_by=user
        )
    return RateSync.objects.create(
        started_at=started_at,
        url=url,
        success=True,
        rates_created=store_rates(published),
        latest_date=max(r.date for r in published),
        triggered_by=user,
    )


def needs_sync(*, now=None):
    """Are rost să întrebăm acum BNR? Job-ul rulează des, dar descarcă doar la nevoie."""
    now = now or local_now()
    today = now.date()
    if is_covered(today, now=now):
        return False  # cursul de azi e deja știut (sau azi nu se publică)
    if now.time() < PUBLICATION_TIME:
        # Cursul de azi nu există încă; întrebăm doar dacă ne lipsesc zile anterioare.
        return not is_covered(today - datetime.timedelta(days=1), now=now)
    return True


def sync_rates(*, user=None, force=False, now=None):
    """Aduce de la BNR cursurile lipsă. Întoarce lista încercărilor (RateSync).

    - prima rulare (istoric gol): arhivele anului curent și ale celui anterior;
    - după o pauză mai lungă decât acoperă fișierul zilnic: arhivele care lipsesc,
      ca istoricul să nu aibă goluri (altfel o factură din gol ar primi un curs vechi);
    - apoi fișierul cu ultimele 10 zile.
    La prima eroare se oprește; job-ul reîncearcă la rularea următoare (I-28).
    """
    now = now or local_now()
    if not force and not needs_sync(now=now):
        return []

    latest = latest_rate_date()
    urls = []
    if latest is None:
        urls += [bnr.year_url(year) for year in (now.year - 1, now.year)]
    elif (now.date() - latest).days > RECENT_FILE_DAYS:
        urls += [bnr.year_url(year) for year in range(latest.year, now.year + 1)]
    urls.append(bnr.recent_url())

    syncs = []
    for url in urls:
        sync = _sync_file(url, user)
        syncs.append(sync)
        if not sync.success:
            break
    if syncs[-1].success:
        # Facturile în așteptare (capitolul 7) ascultă acest semnal și se reiau.
        rates_synced.send(sender=RateSync, syncs=syncs)
    return syncs


def load_year(year, *, user=None):
    """Încarcă explicit arhiva unui an (ex. pentru facturi mai vechi decât istoricul)."""
    sync = _sync_file(bnr.year_url(year), user)
    if sync.success:
        rates_synced.send(sender=RateSync, syncs=[sync])
    return sync


def last_sync():
    return RateSync.objects.first()


def last_successful_sync():
    return RateSync.objects.filter(success=True).first()
