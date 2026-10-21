"""„Mașina timpului” pentru datele demo: acțiunile se petrec la data dorită, în trecut.

    with travel_to(moment):
        services.send_order(order)   # sent_at, jurnalul de audit, numerele: la `moment`

Fără ea, o comandă „trimisă acum 3 luni” ar avea în jurnal ora la care a rulat scriptul,
iar istoricul ar fi fals. Toată aplicația citește ceasul prin `django.utils.timezone.now`
(direct, prin localdate()/localtime() sau prin auto_now), deci e suficient să-l înlocuim
pe acesta. Excepție: câmpurile care au ca valoare implicită chiar funcția originală
(`default=timezone.now`, ex. jurnalul django-auditlog) păstrează o referință la ea; le
mutăm și pe ele, temporar, căutându-le în toate modelele.

Doar pentru scriptul de date demo: aplicația propriu-zisă nu „călătorește” niciodată.
"""

from contextlib import contextmanager

from django.apps import apps
from django.utils import timezone

_real_now = timezone.now


@contextmanager
def travel_to(moment):
    """Ceasul aplicației arată `moment` (dată-oră cu fus orar) pe durata blocului."""
    if timezone.is_naive(moment):
        raise ValueError("travel_to cere o dată-oră cu fus orar (timezone.make_aware).")

    def fake_now():
        return moment

    fields = [
        field
        for model in apps.get_models()
        for field in model._meta.concrete_fields
        if field.default is _real_now
    ]
    timezone.now = fake_now
    for field in fields:
        _set_default(field, fake_now)
    try:
        yield
    finally:  # ceasul revine la normal orice s-ar întâmpla
        timezone.now = _real_now
        for field in fields:
            _set_default(field, _real_now)


def _set_default(field, function):
    """Django memorează valoarea implicită a câmpului la prima folosire (Field._get_default);
    fără golirea acestei memorări, schimbarea nu ar avea efect sau, mai rău, câmpul ar
    rămâne blocat pe ora falsă și după întoarcerea în prezent."""
    field.default = function
    field.__dict__.pop("_get_default", None)
