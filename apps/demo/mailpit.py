"""Mailpit, căsuța de email de test: emailurile demo din zilele trecute apar ca citite.

Doar pentru datele demo. Aplicația propriu-zisă nu știe nimic despre Mailpit (trimite
emailurile prin SMTP, la orice server din EMAIL_URL). Aici folosim API-ul web al
Mailpit (setarea MAILPIT_API_URL); fără el, nu se întâmplă nimic.
"""

import datetime
import json
from urllib.error import URLError
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

TIMEOUT_SECONDS = 10


class MailpitError(Exception):
    pass


def mark_past_emails_read(today):
    """Marchează ca citite emailurile datate înainte de `today`. Întoarce câte, sau None
    dacă Mailpit nu e configurat. Data unui email = data scrisă în el (Mailpit pornit cu
    MP_USE_MESSAGE_DATES), adică ziua din trecut a rezumatului demo."""
    base = settings.MAILPIT_API_URL.rstrip("/")
    if not base:
        return None
    try:
        with urlopen(f"{base}/api/v1/messages?limit=1000", timeout=TIMEOUT_SECONDS) as response:
            messages = json.load(response)["messages"]
        past = [
            message["ID"]
            for message in messages
            if not message["Read"] and _local_date(message["Created"]) < today
        ]
        if past:
            body = json.dumps({"IDs": past, "Read": True}).encode()
            request = Request(
                f"{base}/api/v1/messages",
                data=body,
                method="PUT",
                headers={"Content-Type": "application/json"},
            )
            with urlopen(request, timeout=TIMEOUT_SECONDS):
                pass
    except (URLError, OSError, ValueError, KeyError) as exc:
        raise MailpitError(f"Mailpit nu a putut fi actualizat ({exc}).") from exc
    return len(past)


def _local_date(iso_moment):
    """„2026-10-20T05:05:00Z” → ziua din calendarul României."""
    moment = datetime.datetime.fromisoformat(iso_moment.replace("Z", "+00:00"))
    return timezone.localtime(moment).date()
