"""Formatarea numerelor în stil românesc, în șabloane:

{% load formatting %}
{{ line.net_amount|money }}   → 1.234,56
{{ line.quantity|qty }}       → 12,5   (fără zecimale inutile, maxim 3)
"""

from django import template
from django.template.defaultfilters import floatformat

register = template.Library()


@register.filter
def money(value):
    return floatformat(value, "2g")


@register.filter
def qty(value):
    return floatformat(value, "-3g")
