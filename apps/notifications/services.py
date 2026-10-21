"""Trimiterea rezumatelor pe email (docs/05-reguli-business.md, §5).

    send_daily_digests()          # job-ul: o dată pe zi lucrătoare, după ora configurată
    send_digest(user, ...)        # un singur email (folosit și de „Trimite acum”)

Emailul se predă serverului SMTP din setarea EMAIL_URL (local: Mailpit, care îl
reține și îl arată la http://localhost:8025). Fiecare încercare rămâne în
NotificationLog; o eroare la un destinatar nu îi oprește pe ceilalți.
"""

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from apps.accounts.models import User
from apps.audit.models import BusinessEvent
from apps.audit.services import record_event
from apps.core.dates import is_business_day

from .alerts import alerts_for, collect, for_user
from .digest import build_digest
from .models import DailyDigestRun, NotificationLog

# Rolurile care primesc rezumat; Administratorul nu (docs/01-ipoteze.md, I-33).
DIGEST_ROLES = (User.Role.PROCUREMENT, User.Role.WAREHOUSE, User.Role.ACCOUNTING)
# De câte ori pe zi se încearcă un email care nu a putut fi trimis.
MAX_DAILY_ATTEMPTS = 3


def local_now():
    """Ora curentă (fusul orar al aplicației). Un singur loc, ca testele să o poată fixa."""
    return timezone.localtime()


def previous_keys(user):
    """Problemele din ultimul rezumat trimis cu succes: față de ele se marchează „NOU”."""
    last = NotificationLog.objects.filter(recipient=user, status=NotificationLog.Status.SENT)
    last = last.order_by("-sent_at", "-id").first()
    return last.items if last else []


def send_digest(user, *, alerts=None, kind=NotificationLog.Kind.DAILY, triggered_by=None):
    """Trimite rezumatul lui `user`. Fără probleme → nu trimite nimic și întoarce None (I-31)."""
    if alerts is None:
        alerts = alerts_for(user, local_now().date())
    if not alerts:
        return None

    digest = build_digest(user, alerts, previous_keys(user))
    message = EmailMultiAlternatives(
        subject=digest.subject,
        body=digest.text,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
    )
    message.attach_alternative(digest.html, "text/html")
    try:
        message.send()
    except Exception as exc:  # orice eroare de rețea / SMTP: se notează, nu oprește job-ul
        status, error = NotificationLog.Status.FAILED, f"{type(exc).__name__}: {exc}"
    else:
        status, error = NotificationLog.Status.SENT, ""

    return NotificationLog.objects.create(
        recipient=user,
        email=user.email,
        kind=kind,
        subject=digest.subject,
        body_text=digest.text,
        items=digest.keys,
        status=status,
        error=error,
        triggered_by=triggered_by,
    )


def digest_recipients():
    return (
        User.objects.filter(is_active=True, role__in=DIGEST_ROLES).exclude(email="").order_by("pk")
    )


def is_due(now):
    """E momentul rezumatului? Zi lucrătoare, la sau după ora configurată (implicit 08:00)."""
    return is_business_day(now.date()) and now.hour >= settings.NOTIFICATION_HOUR


def send_daily_digests(*, now=None):
    """Job-ul zilnic. Poate rula oricât de des: face rezumatul o singură dată pe zi, apoi
    doar reîncearcă emailurile eșuate (de cel mult MAX_DAILY_ATTEMPTS ori pe zi).

    Dacă serverul a fost oprit la ora rezumatului, rezumatul pleacă la prima rulare de după.
    Întoarce încercările făcute acum (NotificationLog).
    """
    now = now or local_now()
    today = now.date()
    if not is_due(now):
        return []

    run = _start_run(today)
    if run is None:
        return _retry_failed(today)

    alerts = collect(today)  # o singură dată pentru toți destinatarii
    logs = []
    for user in digest_recipients():
        log = send_digest(user, alerts=for_user(alerts, user))
        if log is None:
            run.nothing_to_report += 1
            continue
        logs.append(log)
        if log.status == NotificationLog.Status.SENT:
            run.sent += 1
        else:
            run.failed += 1
    run.save(update_fields=["sent", "failed", "nothing_to_report"])
    return logs


def _start_run(today):
    """Marchează rezumatul zilei ca pornit. None dacă era deja pornit (de alt proces)."""
    try:
        with transaction.atomic():
            return DailyDigestRun.objects.create(date=today)
    except IntegrityError:  # data e unică: două procese simultane nu pot porni amândouă
        return None


def _retry_failed(today):
    """Destinatarii care azi au doar încercări eșuate (sub limită) primesc o nouă încercare."""
    todays = NotificationLog.objects.filter(kind=NotificationLog.Kind.DAILY, sent_at__date=today)
    logs = []
    for user in digest_recipients().filter(pk__in=todays.values("recipient")):
        mine = todays.filter(recipient=user)
        if mine.filter(status=NotificationLog.Status.SENT).exists():
            continue
        if mine.count() >= MAX_DAILY_ATTEMPTS:
            continue
        log = send_digest(user)
        if log is not None:
            logs.append(log)
            if log.status == NotificationLog.Status.SENT:
                # Actualizare direct în baza de date: corectă și cu procese simultane.
                DailyDigestRun.objects.filter(date=today).update(
                    sent=F("sent") + 1, failed=F("failed") - 1
                )
    return logs


def send_now(*, triggered_by=None, recipients=None):
    """„Trimite acum”: rezumatul curent, imediat, indiferent de oră și de ce s-a trimis azi.

    Util la demonstrații sau după rezolvarea unei probleme de configurare. Nu înlocuiește
    rezumatul zilnic (care rămâne o dată pe zi) și rămâne consemnat în jurnalul de audit.
    Întoarce (încercările făcute, numărul celor fără probleme).
    """
    recipients = digest_recipients() if recipients is None else recipients
    alerts = collect(local_now().date())
    logs, nothing = [], 0
    for user in recipients:
        log = send_digest(
            user,
            alerts=for_user(alerts, user),
            kind=NotificationLog.Kind.MANUAL,
            triggered_by=triggered_by,
        )
        if log is None:
            nothing += 1
        else:
            logs.append(log)

    sent = sum(1 for log in logs if log.status == NotificationLog.Status.SENT)
    record_event(
        BusinessEvent.Type.NOTIFICATIONS_SENT_NOW,
        f"Rezumate trimise manual: {sent} trimise, {len(logs) - sent} eșuate.",
        data={"trimise": sent, "eșuate": len(logs) - sent, "fără probleme": nothing},
        actor=triggered_by,
    )
    return logs, nothing
