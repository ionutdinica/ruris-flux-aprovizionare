"""Bugetul unui furnizor, pe paginile altor module (furnizor, comandă):

    {% load budgets %}
    {% supplier_budget supplier %}                    # cardul bugetului pe anul curent
    {% supplier_budget order.supplier order=order %}  # bugetul anului comenzii + efectul ei
    {% order_budget_impact order as impact %}         # efectul unei ciorne (sau None)

Ca istoricul din `audit`: catalogul și comenzile nu depind de bugete, doar șabloanele lor
le afișează. Cine nu are budgets.view (Depozitul) nu vede nimic.
"""

from django import template
from django.utils import timezone

from apps.purchasing.models import PurchaseOrder

from .. import services

register = template.Library()


@register.inclusion_tag("budgets/partials/budget_card.html", takes_context=True)
def supplier_budget(context, supplier, order=None):
    user = context["user"]
    if not user.can("budgets.view"):
        return {}
    year = order.order_date.year if order else timezone.localdate().year
    status = services.status_for(supplier, year)
    return {
        "status": status,
        "impact": _impact(order) if status and order else None,
        "year": year,
        "supplier": supplier,
        "offer_new": order is None and user.can("budgets.edit"),
    }


@register.simple_tag(takes_context=True)
def order_budget_impact(context, order):
    return _impact(order) if context["user"].can("budgets.view") else None


def _impact(order):
    if order.status != PurchaseOrder.Status.DRAFT:
        return None
    return services.order_impact(order)
