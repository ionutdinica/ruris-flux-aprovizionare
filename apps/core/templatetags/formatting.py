"""Formatarea numerelor în stil românesc, în șabloane:

{% load formatting %}
{{ line.net_amount|money }}   → 1.234,56
{{ line.quantity|qty }}       → 12,5   (fără zecimale inutile, maxim 3)
{{ n|plural:"comandă,comenzi" }} → 1 comandă, 3 comenzi
"""

from django import template
from django.template.defaultfilters import floatformat

from apps.core.text import plural

register = template.Library()


@register.filter
def money(value):
    return floatformat(value, "2g")


@register.filter
def qty(value):
    return floatformat(value, "-3g")


@register.filter(name="plural")
def plural_filter(number, forms):
    """{{ n|plural:"comandă,comenzi" }} → „1 comandă”, „3 comenzi” (acordul în română)."""
    singular, plural_form = forms.split(",")
    return plural(number, singular, plural_form)
