"""Cât s-a consumat dintr-un buget și ce face o comandă nouă cu el (docs/05, §7).

    statuses(year)          # toate bugetele anului, cu cele patru cifre
    status_for(supplier, y) # bugetul unui furnizor (sau None)
    order_impact(order)     # efectul unei comenzi în ciornă asupra bugetului (sau None)

Bugetul se consumă la COMANDĂ, nu la factură: o comandă trimisă e deja un angajament
față de furnizor (I-40). Valorile sunt fără TVA, în moneda bugetului.
"""

from dataclasses import dataclass, field
from decimal import Decimal

from apps.core.models import Currency
from apps.currency.models import ExchangeRate
from apps.invoicing.models import Invoice, InvoiceLine
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine, money

from .models import SupplierBudget

ZERO = Decimal("0")
# De la ce procent consumat apare alerta „aproape consumat”.
WARNING_PERCENT = 90

Status = PurchaseOrder.Status
# Comenzile care consumă bugetul: trimise, în orice stadiu. Ciornele încă nu sunt un
# angajament, iar cele anulate nu mai sunt. Cele închise cu rest: doar ce a sosit.
COUNTED_STATUSES = (Status.SENT, Status.PARTIALLY_RECEIVED, Status.RECEIVED, Status.CLOSED)


class NoRate(Exception):
    """Nu există niciun curs BNR pentru conversie."""


class Converter:
    """Conversia între monede la cursul BNR al zilei documentului (sau ultimul de dinainte).

    E o estimare pentru buget: comanda nu are un curs „oficial”, iar factura își are
    oricum cursul ei exact. Cursurile citite se păstrează pe durata unui calcul.
    """

    def __init__(self):
        self._cache = {}

    def lei_per_unit(self, currency, day):
        if currency == Currency.RON:
            return Decimal("1")
        key = (currency, day)
        if key not in self._cache:
            rates = ExchangeRate.objects.filter(currency=currency)
            rate = rates.filter(date__lte=day).order_by("-date").first()
            rate = rate or rates.order_by("date").first()  # document mai vechi decât arhiva
            if rate is None:
                raise NoRate(currency)
            self._cache[key] = rate.rate / rate.multiplier
        return self._cache[key]

    def convert(self, amount, from_currency, to_currency, day):
        if from_currency == to_currency:
            return amount
        lei = amount * self.lei_per_unit(from_currency, day)
        return money(lei / self.lei_per_unit(to_currency, day))


@dataclass
class BudgetStatus:
    budget: SupplierBudget
    committed: Decimal = ZERO  # angajat prin comenzi
    invoiced: Decimal = ZERO  # din care facturat
    # Comenzi care nu au putut fi convertite în moneda bugetului (lipsă curs BNR).
    unconverted: list = field(default_factory=list)

    @property
    def available(self):
        return self.budget.amount - self.committed

    @property
    def overrun(self):
        """Cu cât e depășit bugetul (0 dacă nu e depășit)."""
        return max(self.committed - self.budget.amount, ZERO)

    @property
    def percent(self):
        return int(self.committed * 100 / self.budget.amount)

    @property
    def level(self):
        """ok · warning (de la 90%) · over (depășit)."""
        if self.committed > self.budget.amount:
            return "over"
        return "warning" if self.percent >= WARNING_PERCENT else "ok"

    @property
    def color(self):
        return {"ok": "success", "warning": "warning", "over": "danger"}[self.level]

    @property
    def bar_percent(self):
        return min(self.percent, 100)


def _committed_value(line):
    quantity = line.received_qty if line.order.status == Status.CLOSED else line.quantity
    return money(quantity * line.unit_price)


def statuses(year, budgets=None):
    """Situația bugetelor anului `year` (sau doar a celor date), în ordinea furnizorilor."""
    if budgets is None:
        budgets = SupplierBudget.objects.filter(year=year)
    budgets = list(budgets.select_related("supplier").order_by("supplier__name"))
    by_supplier = {budget.supplier_id: BudgetStatus(budget) for budget in budgets}
    if not by_supplier:
        return []
    converter = Converter()

    lines = (
        PurchaseOrderLine.objects.with_progress()
        .filter(
            order__supplier_id__in=by_supplier,
            order__order_date__year=year,
            order__status__in=COUNTED_STATUSES,
        )
        .select_related("order")
    )
    for line in lines:
        order, status = line.order, by_supplier[line.order.supplier_id]
        try:
            status.committed += converter.convert(
                _committed_value(line), order.currency, status.budget.currency, order.order_date
            )
        except NoRate:
            if order not in status.unconverted:
                status.unconverted.append(order)

    invoice_lines = InvoiceLine.objects.filter(
        order_line__order__supplier_id__in=by_supplier,
        order_line__order__order_date__year=year,
        order_line__order__status__in=COUNTED_STATUSES,
        invoice__status__in=Invoice.INVOICED_STATUSES,
    ).select_related("invoice", "order_line__order")
    for line in invoice_lines:
        invoice, status = line.invoice, by_supplier[line.order_line.order.supplier_id]
        try:
            status.invoiced += converter.convert(
                line.net_amount, invoice.currency, status.budget.currency, invoice.invoice_date
            )
        except NoRate:
            pass  # informativ; lipsa cursului se vede deja la comandă

    return list(by_supplier.values())


def status_for(supplier, year):
    budgets = SupplierBudget.objects.filter(supplier=supplier, year=year)
    found = statuses(year, budgets)
    return found[0] if found else None


@dataclass
class OrderImpact:
    """Ce face o comandă (încă netrimisă) cu bugetul furnizorului."""

    status: BudgetStatus
    amount: Decimal  # valoarea comenzii fără TVA, în moneda bugetului

    @property
    def available_after(self):
        return self.status.available - self.amount

    @property
    def exceeds(self):
        return self.amount > 0 and self.available_after < 0

    @property
    def excess(self):
        """Cu cât depășește bugetul DIN CAUZA acestei comenzi."""
        return min(self.amount, -self.available_after) if self.exceeds else ZERO


def order_impact(order):
    """None dacă furnizorul nu are buget pe anul comenzii (nicio verificare)."""
    status = status_for(order.supplier, order.order_date.year)
    if status is None:
        return None
    try:
        amount = Converter().convert(
            order.net_amount, order.currency, status.budget.currency, order.order_date
        )
    except NoRate:
        return None  # fără niciun curs nu putem estima; trimiterea nu se blochează
    return OrderImpact(status, amount)
