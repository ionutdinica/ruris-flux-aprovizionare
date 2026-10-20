"""Cardul de stoc al unui produs, folosit pe fișa produsului din nomenclator:

{% load stock %}{% product_stock product %}
"""

from django import template

from ..selectors import available_stock, quarantined_stock

register = template.Library()


@register.inclusion_tag("warehouse/partials/product_stock_card.html")
def product_stock(product):
    return {
        "product": product,
        "available": available_stock(product),
        "quarantined": quarantined_stock(product),
    }
