"""Starea sistemului, pe panoul Administratorului: merg lucrurile care rulează în spate?

Job-urile (cursul BNR, rezumatul pe email) nu au o pagină a lor; dacă planificatorul
se oprește, nimeni nu observă imediat. Verificările de aici transformă tăcerea în
semnal: verde = în regulă, galben = de urmărit, roșu = cere intervenție.
"""

import datetime
from dataclasses import dataclass

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.core.dates import is_business_day
from apps.currency import services as currency
from apps.notifications.models import DailyDigestRun, NotificationLog
from apps.notifications.services import DIGEST_ROLES

OK, WARNING, ERROR = "ok", "warning", "error"
FAILED_EMAILS_DAYS = 7


@dataclass(frozen=True)
class Check:
    label: str
    status: str  # ok / warning / error
    detail: str
    url: str = ""

    @property
    def color(self):
        return {OK: "success", WARNING: "warning", ERROR: "danger"}[self.status]

    @property
    def icon(self):
        return {
            OK: "check-circle-fill",
            WARNING: "exclamation-circle-fill",
            ERROR: "x-circle-fill",
        }[self.status]


def system_checks(now):
    return [_exchange_rate(now), _daily_digest(now), _failed_emails(now), _users()]


def _exchange_rate(now):
    url = reverse("currency:rate_list")
    latest = currency.latest_rate_date()
    last = currency.last_sync()
    if latest is None:
        return Check("Cursul BNR", ERROR, "Niciun curs salvat: job-ul nu a rulat încă.", url)
    if currency.is_covered(now.date(), now=now):
        return Check("Cursul BNR", OK, f"La zi; ultimul curs publicat: {latest:%d.%m.%Y}.", url)
    if last is not None and not last.success:
        return Check(
            "Cursul BNR",
            ERROR,
            f"Ultima actualizare ({_local(last.started_at):%d.%m %H:%M}) a eșuat: {last.error}",
            url,
        )
    return Check(
        "Cursul BNR",
        WARNING,
        "Cursul de azi e în așteptare (BNR publică în jurul orei 13:00); "
        f"ultimul: {latest:%d.%m.%Y}.",
        url,
    )


def _daily_digest(now):
    url = reverse("notifications:log")
    today = now.date()
    run = DailyDigestRun.objects.filter(date=today).first()
    if run is not None:
        status = ERROR if run.failed else OK
        detail = (
            f"Azi la {_local(run.started_at):%H:%M}: {run.sent} trimise, {run.failed} eșuate, "
            f"{run.nothing_to_report} fără nimic de rezolvat."
        )
        return Check("Rezumatul zilnic", status, detail, url)
    if is_business_day(today) and now.hour >= settings.NOTIFICATION_HOUR:
        # Ar fi trebuit să ruleze: semnul tipic al unui planificator oprit.
        return Check(
            "Rezumatul zilnic",
            ERROR,
            f"Nu a rulat azi, deși ora {settings.NOTIFICATION_HOUR}:00 a trecut. "
            "Planificatorul (run_scheduler) este pornit?",
            url,
        )
    last = DailyDigestRun.objects.first()
    when = f"ultimul: {last.date:%d.%m.%Y}" if last else "nu a rulat încă niciodată"
    reason = "zi nelucrătoare" if not is_business_day(today) else "nu e încă ora"
    return Check(
        "Rezumatul zilnic", WARNING if last is None else OK, f"Azi: {reason}; {when}.", url
    )


def _failed_emails(now):
    since = now - datetime.timedelta(days=FAILED_EMAILS_DAYS)
    failed = NotificationLog.objects.filter(
        status=NotificationLog.Status.FAILED, sent_at__gte=since
    )
    count = failed.count()
    url = reverse("notifications:log") + "?status=FAILED"
    if not count:
        return Check("Emailuri eșuate", OK, f"Niciunul în ultimele {FAILED_EMAILS_DAYS} zile.", url)
    last = failed.first()
    return Check(
        "Emailuri eșuate",
        ERROR,
        f"{count} în ultimele {FAILED_EMAILS_DAYS} zile; ultimul: {last.error}",
        url,
    )


def _users():
    url = reverse("admin:accounts_user_changelist")
    active = User.objects.filter(is_active=True)
    per_role = {role: active.filter(role=role).count() for role in User.Role}
    summary = ", ".join(f"{User.Role(role).label}: {count}" for role, count in per_role.items())
    missing = [User.Role(role).label for role in DIGEST_ROLES if not per_role[role]]
    if missing:
        return Check(
            "Utilizatori activi",
            WARNING,
            f"{summary}. Niciun utilizator activ pentru: {', '.join(missing)}: problemele "
            "acestor echipe nu ajung la nimeni.",
            url,
        )
    return Check("Utilizatori activi", OK, summary + ".", url)


def _local(moment):
    """Orele sunt salvate în UTC; afișate în ora României (ex. 08:00, nu 05:00)."""
    return timezone.localtime(moment)
