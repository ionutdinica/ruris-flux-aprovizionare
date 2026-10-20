"""Verificarea permisiunilor din șabloane:

    {% load permissions %}
    {% if user|can:"orders.view_prices" %} ...prețuri... {% endif %}

Ascunde în interfață ce nu e permis. Protecția reală e pe server (PermissionMixin).
"""

from django import template

from ..permissions import has_permission

register = template.Library()


@register.filter
def can(user, permission):
    return has_permission(user, permission)
