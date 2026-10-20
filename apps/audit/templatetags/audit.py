"""Secțiunea „Istoric”, reutilizabilă pe pagina oricărui document:

    {% load audit %}
    {% object_history comanda %}

Afișează cele mai recente intrări din jurnal pentru documentul dat și, pentru
Administrator, un link spre istoricul complet din „Jurnal de activitate”.
"""

from django import template
from django.contrib.contenttypes.models import ContentType

from ..timeline import history_for

register = template.Library()

HISTORY_LIMIT = 10


@register.inclusion_tag("audit/partials/object_history.html", takes_context=True)
def object_history(context, obj, limit=HISTORY_LIMIT):
    entries = history_for(obj, limit=limit + 1)  # +1: aflăm dacă mai sunt și altele
    return {
        "entries": entries[:limit],
        "has_more": len(entries) > limit,
        "content_type_id": ContentType.objects.get_for_model(obj).pk,
        "object_id": obj.pk,
        "user": context.get("user"),
    }
