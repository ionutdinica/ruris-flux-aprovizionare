"""Regulile depozitului (docs/05-reguli-business.md §3).

Orice schimbare de stoc trece printr-o funcție de aici. Fiecare funcție:
  1. blochează în baza de date rândurile de care depinde (select_for_update), ca două
     operații simultane să nu ducă la o stare greșită (ex. două ieșiri care, împreună,
     ar face stocul negativ, sau două recepții pe aceeași comandă);
  2. verifică regulile;
  3. scrie mișcările de stoc și evenimentul în jurnalul de audit.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.audit.models import BusinessEvent
from apps.audit.services import record_event
from apps.catalog.models import Product
from apps.core.text import format_quantity
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.purchasing.services import received_quantities, refresh_status

from .models import Discrepancy, GoodsReceipt, StockMovement
from .selectors import available_stock

ZERO = Decimal("0")
Movement = StockMovement.Type


class WarehouseError(ValidationError):
    """Operația de depozit nu e permisă în situația curentă."""


_qty = format_quantity  # cantitate afișabilă: 12 în loc de 12.000


def _lock_order(order_id):
    return PurchaseOrder.objects.select_for_update().get(pk=order_id)


# --- Recepția ------------------------------------------------------------------------------


def split_quantity(quantity, order_line, already_received):
    """Regula carantinei (I-11): câtă marfă intră în stoc și câtă merge în carantină.

    acceptat = min(numărat, comandat − recepționat deja); restul → carantină.
    Fără linie de comandă (marfă necomandată), totul merge în carantină.
    Folosită ȘI la previzualizare, ȘI la confirmare: cele două nu pot calcula diferit.
    """
    if order_line is None:
        return ZERO, quantity
    remaining = max(order_line.quantity - already_received, ZERO)
    accepted = min(quantity, remaining)
    return accepted, quantity - accepted


def preview_receipt(receipt):
    """Ce s-ar întâmpla la confirmare, fără să salveze nimic: [(linie, acceptat, carantină)]."""
    received = received_quantities(receipt.purchase_order) if receipt.purchase_order_id else {}
    return [
        (
            line,
            *split_quantity(
                line.quantity_received, line.order_line, received.get(line.order_line_id, ZERO)
            ),
        )
        for line in receipt.lines.select_related("product", "order_line")
    ]


@transaction.atomic
def confirm_receipt(receipt, user):
    """Confirmă o recepție: împarte fiecare linie în acceptat (stoc) și carantină (I-11).

    acceptat = min(numărat, comandat − recepționat deja pe linie); restul → carantină.
    O linie fără linie de comandă (marfă necomandată) merge integral în carantină.
    """
    receipt = GoodsReceipt.objects.select_for_update().get(pk=receipt.pk)
    if not receipt.is_draft:
        raise WarehouseError("Recepția a fost deja confirmată.")
    lines = list(receipt.lines.select_related("product", "order_line"))
    if not any(line.quantity_received > 0 for line in lines):
        raise WarehouseError("Recepția nu are nicio cantitate numărată.")

    order, received = None, {}
    if receipt.purchase_order_id:
        # Blocarea comenzii serializează recepțiile pe aceeași comandă: a doua tranșă
        # vede corect ce a acceptat prima.
        order = _lock_order(receipt.purchase_order_id)
        if order.status not in GoodsReceipt.RECEIVABLE_ORDER_STATUSES:
            raise WarehouseError(
                f"Pe comanda {order} nu se mai poate recepționa "
                f"({order.get_status_display().lower()})."
            )
        received = received_quantities(order)

    receipt.assign_number()
    discrepancies = 0
    for line in lines:
        if line.order_line_id and (
            line.order_line.order_id != receipt.purchase_order_id
            or line.order_line.product_id != line.product_id
        ):
            raise WarehouseError(f"Linia cu produsul {line.product} nu corespunde comenzii.")

        accepted, quarantined = split_quantity(
            line.quantity_received, line.order_line, received.get(line.order_line_id, ZERO)
        )

        line.quantity_accepted, line.quantity_quarantined = accepted, quarantined
        line.save(update_fields=["quantity_accepted", "quantity_quarantined", "updated_at"])
        if accepted > 0:
            StockMovement.objects.create(
                product=line.product,
                type=Movement.RECEIPT,
                quantity=accepted,
                date=receipt.receipt_date,
                receipt_line=line,
                order_line=line.order_line,
                reason=f"Recepția {receipt.number}",
                created_by=user,
            )
        if quarantined > 0:
            Discrepancy.objects.create(
                receipt_line=line,
                type=Discrepancy.Type.OVER_DELIVERY
                if line.order_line_id
                else Discrepancy.Type.UNORDERED,
                quantity=quarantined,
            )
            discrepancies += 1

    receipt.status = GoodsReceipt.Status.CONFIRMED
    receipt.confirmed_by = user
    receipt.confirmed_at = timezone.now()
    receipt.save()
    # Întâi recepția în jurnal, apoi efectele ei (statusul comenzii, facturile reverificate),
    # ca jurnalul să se citească în ordinea cauzei: „recepție confirmată → factură deblocată”.
    record_event(
        BusinessEvent.Type.RECEIPT_CONFIRMED,
        f"Recepția {receipt.number} a fost confirmată"
        + (f" pe comanda {order}." if order else " (marfă fără comandă).")
        + (f" {discrepancies} linii au mers în carantină." if discrepancies else ""),
        target=receipt,
        actor=user,
        data={"linii": len(lines), "în carantină": discrepancies},
    )
    if order:
        refresh_status(order)  # Trimisă → Parțial recepționată → Recepționată
    return receipt


@transaction.atomic
def delete_draft_receipt(receipt):
    """O ciornă de recepție (ex. pornită pe comanda greșită) se poate șterge.
    Fiind fără număr, nu lasă goluri în numerotare."""
    receipt = GoodsReceipt.objects.select_for_update().get(pk=receipt.pk)
    if not receipt.is_draft:
        raise WarehouseError("O recepție confirmată nu se mai poate șterge.")
    receipt.delete()


# --- Discrepanțe (decizia Achizițiilor, I-12) ---------------------------------------------


def _lock_open_discrepancy(discrepancy):
    discrepancy = (
        Discrepancy.objects.select_for_update()
        .select_related("receipt_line__product", "receipt_line__receipt")
        .get(pk=discrepancy.pk)
    )
    if not discrepancy.is_open:
        raise WarehouseError("Discrepanța a fost deja rezolvată.")
    return discrepancy


def attach_candidates(discrepancy):
    """Liniile de comandă pe care poate fi atașată marfa din carantină: același furnizor
    și produs, comandă activă, iar linia mai așteaptă cel puțin cantitatea din carantină."""
    return (
        PurchaseOrderLine.objects.with_progress()
        .filter(
            product=discrepancy.receipt_line.product_id,
            order__supplier=discrepancy.receipt_line.receipt.supplier_id,
            order__status__in=GoodsReceipt.RECEIVABLE_ORDER_STATUSES,
        )
        .annotate(remaining_qty=F("quantity") - F("received_qty"))
        .filter(remaining_qty__gte=discrepancy.quantity)
        .select_related("order", "product")
        .order_by("order__expected_date", "order__number")
    )


@transaction.atomic
def attach_discrepancy(discrepancy, order_line, user, note=""):
    """Marfa din carantină e acceptată pe o linie de comandă: intră în stoc și contează
    ca recepționată pe acea linie."""
    discrepancy = _lock_open_discrepancy(discrepancy)
    order = _lock_order(order_line.order_id)
    order_line = PurchaseOrderLine.objects.get(pk=order_line.pk)

    if order_line.product_id != discrepancy.receipt_line.product_id:
        raise WarehouseError("Linia de comandă are alt produs decât marfa din carantină.")
    if order.supplier_id != discrepancy.receipt_line.receipt.supplier_id:
        raise WarehouseError("Comanda aparține altui furnizor decât cel care a livrat marfa.")
    if order.status not in GoodsReceipt.RECEIVABLE_ORDER_STATUSES:
        raise WarehouseError(
            f"Comanda {order} nu mai acceptă marfă ({order.get_status_display().lower()})."
        )
    remaining = order_line.quantity - received_quantities(order).get(order_line.pk, ZERO)
    if remaining < discrepancy.quantity:
        unit = order_line.product.unit
        raise WarehouseError(
            f"Linia mai așteaptă doar {_qty(max(remaining, ZERO))} {unit}, iar în carantină "
            f"sunt {_qty(discrepancy.quantity)}. Mărește cantitatea pe comandă (regularizare) "
            "sau alege altă linie."
        )

    StockMovement.objects.create(
        product=order_line.product,
        type=Movement.DISCREPANCY_ACCEPTED,
        quantity=discrepancy.quantity,
        receipt_line=discrepancy.receipt_line,
        order_line=order_line,
        discrepancy=discrepancy,
        reason=f"Din carantină, recepția {discrepancy.receipt_line.receipt}",
        created_by=user,
    )
    _resolve(discrepancy, Discrepancy.Resolution.ATTACHED, user, note, order_line=order_line)
    record_event(  # întâi decizia, apoi efectele ei (comanda, facturile reverificate)
        BusinessEvent.Type.DISCREPANCY_ATTACHED,
        f"{_qty(discrepancy.quantity)} {order_line.product.unit} {order_line.product.code} din "
        f"carantină au fost acceptate pe comanda {order}.",
        target=discrepancy,
        actor=user,
        data={"comandă": order.number, **({"observații": note} if note else {})},
    )
    refresh_status(order)
    return discrepancy


@transaction.atomic
def accept_over_delivery(discrepancy, user, note=""):
    """Surplusul livrat peste comandă e acceptat: cantitatea comandată pe linie crește
    cu surplusul (regularizare, vizibilă în istoricul comenzii), apoi marfa intră în stoc."""
    discrepancy = _lock_open_discrepancy(discrepancy)
    if discrepancy.type != Discrepancy.Type.OVER_DELIVERY:
        raise WarehouseError("Doar un surplus livrat peste comandă poate fi acceptat astfel.")
    order_line = discrepancy.receipt_line.order_line
    order = _lock_order(order_line.order_id)
    if not order.is_amendable:
        raise WarehouseError(
            f"Comanda {order} este {order.get_status_display().lower()}: returnează marfa "
            "sau atașeaz-o pe altă comandă."
        )
    old_quantity = order_line.quantity
    order_line.quantity = old_quantity + discrepancy.quantity
    order_line.save(update_fields=["quantity", "updated_at"])  # modificarea intră în jurnal
    note = note or (
        f"Surplus acceptat: cantitatea comandată a crescut de la {_qty(old_quantity)} "
        f"la {_qty(order_line.quantity)}."
    )
    return attach_discrepancy(discrepancy, order_line, user, note)


@transaction.atomic
def return_discrepancy(discrepancy, user, note):
    """Marfa din carantină se returnează furnizorului: nu intră niciodată în stoc."""
    note = (note or "").strip()
    if not note:
        raise WarehouseError("Motivul returului este obligatoriu.")
    discrepancy = _lock_open_discrepancy(discrepancy)
    _resolve(discrepancy, Discrepancy.Resolution.RETURNED, user, note)
    record_event(
        BusinessEvent.Type.DISCREPANCY_RETURNED,
        f"{_qty(discrepancy.quantity)} {discrepancy.product.unit} {discrepancy.product.code} din "
        f"carantină se returnează furnizorului {discrepancy.supplier}.",
        target=discrepancy,
        actor=user,
        data={"motiv": note},
    )
    return discrepancy


def _resolve(discrepancy, resolution, user, note, order_line=None):
    discrepancy.status = Discrepancy.Status.RESOLVED
    discrepancy.resolution = resolution
    discrepancy.attached_order_line = order_line
    discrepancy.resolution_note = note
    discrepancy.resolved_by = user
    discrepancy.resolved_at = timezone.now()
    discrepancy.save()


# --- Ieșiri și ajustări de stoc (I-14) ----------------------------------------------------------

# Tipurile de mișcare manuală: (tipul din registru, semnul cantității)
MANUAL_MOVEMENTS = {
    "CONSUMPTION": (Movement.CONSUMPTION, -1),
    "SUPPLIER_RETURN": (Movement.SUPPLIER_RETURN, -1),
    "ADJUSTMENT_PLUS": (Movement.ADJUSTMENT, 1),
    "ADJUSTMENT_MINUS": (Movement.ADJUSTMENT, -1),
}


@transaction.atomic
def record_stock_movement(product, kind, quantity, user, reason, order_line=None, date=None):
    """Consum, retur la furnizor sau ajustare de inventar. Stocul nu poate deveni negativ.

    Un retur legat de o linie de comandă scade cantitatea recepționată a liniei (I-15):
    comanda redevine parțial recepționată, iar furnizorul „datorează” din nou marfa.
    """
    reason = (reason or "").strip()
    if not reason:
        raise WarehouseError("Motivul este obligatoriu.")
    if quantity is None or quantity <= 0:
        raise WarehouseError("Cantitatea trebuie să fie pozitivă.")
    date = date or timezone.localdate()
    if date > timezone.localdate():
        raise WarehouseError("Data mișcării nu poate fi în viitor.")
    movement_type, sign = MANUAL_MOVEMENTS[kind]

    # Blocarea produsului serializează mișcările lui: două ieșiri simultane nu pot
    # trece amândouă de verificarea de stoc și apoi să-l facă negativ împreună.
    product = Product.objects.select_for_update().get(pk=product.pk)
    available = available_stock(product)
    if sign < 0 and quantity > available:
        raise WarehouseError(
            f"Stoc insuficient pentru {product.code}: disponibil {_qty(available)} {product.unit}, "
            f"ieșire cerută {_qty(quantity)}."
        )

    order = None
    if order_line is not None:
        if movement_type != Movement.SUPPLIER_RETURN:
            raise WarehouseError("Doar un retur la furnizor poate fi legat de o linie de comandă.")
        if order_line.product_id != product.pk:
            raise WarehouseError("Linia de comandă are alt produs.")
        order = _lock_order(order_line.order_id)
        received = received_quantities(order).get(order_line.pk, ZERO)
        if quantity > received:
            raise WarehouseError(
                f"Pe linia comenzii {order} s-au recepționat doar {_qty(received)} {product.unit}."
            )

    movement = StockMovement.objects.create(
        product=product,
        type=movement_type,
        quantity=sign * quantity,
        date=date,
        order_line=order_line,
        reason=reason,
        created_by=user,
    )
    if order:
        refresh_status(order)  # ex. Recepționată → Parțial recepționată după un retur
    return movement
