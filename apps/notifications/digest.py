"""Compunerea rezumatului zilnic al unei persoane: subiect, text și HTML.

Nu trimite nimic (asta face services.py): doar transformă lista de probleme
(alerts.py) într-un email. Așa se poate testa conținutul fără un server de email.
"""

from dataclasses import dataclass

from django.conf import settings
from django.template.loader import render_to_string

from .alerts import Section

# Culoarea barei din stânga fiecărei probleme, pe secțiuni.
SECTION_COLORS = {
    Section.LATE: "#d97706",
    Section.BLOCKED: "#dc2626",
    Section.TODAY: "#2563eb",
    Section.BUDGET: "#7c3aed",  # violet
}


@dataclass
class Digest:
    subject: str
    text: str
    html: str
    keys: list  # cheile problemelor incluse, salvate în NotificationLog.items


def build_digest(user, alerts, previous_keys=()):
    """Emailul pentru `user`. `previous_keys` = cheile din rezumatul anterior (pentru „NOU”)."""
    previous = set(previous_keys)
    items = [
        {"alert": alert, "is_new": alert.key not in previous, "link": _absolute(alert.url)}
        for alert in alerts
    ]
    sections = [
        {
            "title": Section.TITLES[section],
            "color": SECTION_COLORS[section],
            "items": [item for item in items if item["alert"].section == section],
        }
        for section in Section.ORDER
    ]
    sections = [section for section in sections if section["items"]]
    new_count = sum(1 for item in items if item["is_new"])

    context = {
        "user": user,
        "name": user.first_name or user.get_username(),
        "sections": sections,
        "total": len(items),
        "new_count": new_count,
        "site_url": settings.SITE_URL,
        "notification_hour": settings.NOTIFICATION_HOUR,
    }
    return Digest(
        subject=_subject(len(items), new_count),
        text=render_to_string("notifications/email/digest.txt", context),
        html=render_to_string("notifications/email/digest.html", context),
        keys=[alert.key for alert in alerts],
    )


def _subject(total, new_count):
    things = "un lucru" if total == 1 else f"{total} lucruri"
    news = ""
    if new_count == total and total > 1:
        news = " (toate noi)"
    elif new_count == 1:
        news = " (1 nou)"
    elif new_count > 1:
        news = f" ({new_count} noi)"
    return f"Aprovizionare: {things} de rezolvat{news}"


def _absolute(url):
    return f"{settings.SITE_URL.rstrip('/')}{url}"
