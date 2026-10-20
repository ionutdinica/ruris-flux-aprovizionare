"""Autentificările (reușite sau nu) și ieșirile din cont intră în jurnal.

Django emite „semnale” la aceste momente; aici le ascultăm.
"""

from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .models import BusinessEvent
from .services import record_event


@receiver(user_logged_in)
def on_login(sender, request, user, **kwargs):
    record_event(BusinessEvent.Type.LOGIN, f"{user} s-a autentificat.", actor=user)


@receiver(user_logged_out)
def on_logout(sender, request, user, **kwargs):
    if user is not None:
        record_event(BusinessEvent.Type.LOGOUT, f"{user} a ieșit din cont.", actor=user)


@receiver(user_login_failed)
def on_login_failed(sender, credentials, request=None, **kwargs):
    # Se reține doar numele de utilizator încercat, niciodată parola.
    username = credentials.get("username", "")
    record_event(
        BusinessEvent.Type.LOGIN_FAILED,
        f"Autentificare eșuată pentru utilizatorul „{username}”.",
        data={"username": username},
    )
