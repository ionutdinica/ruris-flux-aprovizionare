"""Generatorul datelor demo: o firmă care lucrează de ~4 luni.

Totul se creează prin aceleași reguli ca aplicația (services.py, full_clean), nu prin
inserări directe: demo-ul nu poate conține o stare imposibilă (o factură e „potrivită”
pentru că motorul de potrivire a decis asta). Fiecare acțiune se petrece la data ei,
în trecut (clock.travel_to), și în numele omului care ar face-o (acting_as).

Cum: întâi se PLANIFICĂ toate evenimentele („pe 12.07 la 10:20 Maria trimite comanda”),
apoi se EXECUTĂ în ordine cronologică. Altfel numerele documentelor și jurnalul ar sări
înainte și înapoi în timp (recepția unei comenzi vechi creată după o comandă nouă).

Datele sunt relative la ziua rulării; aleatoriul are sămânță fixă (aceeași zi de rulare
dă aceleași date). Evenimentele se opresc ieri: azi e ziua în care intră utilizatorul.
"""

import datetime
import random
from contextlib import contextmanager
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from auditlog.context import set_actor
from django.conf import settings
from django.utils import timezone

from apps.audit.context import audit_context
from apps.budgets import services as budgets
from apps.budgets.models import SupplierBudget
from apps.core.dates import is_business_day
from apps.currency import services as currency
from apps.invoicing import services as invoicing
from apps.invoicing.models import Invoice, InvoiceLine
from apps.notifications import services as notifications
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.warehouse import services as warehouse
from apps.warehouse.models import Discrepancy, GoodsReceipt, GoodsReceiptLine
from apps.warehouse.selectors import available_stock

from .catalog import PRODUCTS, SUPPLIERS, create_catalog, create_team, price_of, punctuality
from .clock import travel_to

D = Decimal
HISTORY_DAYS = 120  # cât de departe în trecut începe activitatea
ORDERS_PER_WEEK = 3
RANDOM_SEED = 2026
DIGEST_DAYS = 3  # rezumatele zilnice trimise în ultimele zile lucrătoare (pagina Notificări)

# Bugetele anului curent: cât din buget consumă comenzile demo. Doi furnizori ilustrează
# alertele: unul aproape consumat, unul depășit (ultima lui comandă, trimisă cu justificare).
BUDGET_USAGE = {
    "motoare": 0.75,
    "rulmenti": 0.55,  # loc pentru ciclul din README (o comandă nouă de ~2.800 lei)
    "otel": 0.70,
    "plastic": 0.94,  # aproape consumat
    "vopsele": 0.65,
    "hidraulic": 0.60,
    "transmisii": 0.80,
}
OVER_BUDGET_SUPPLIER = "electrice"
OVER_BUDGET_REASON = (
    "Stocul de cabluri a scăzut sub minim și linia de asamblare s-ar fi oprit. "
    "Suplimentarea bugetului e în aprobare la director."
)

# Cantități tipice, pe unitate de măsură: (minim, maxim, pas).
QUANTITIES = {"buc": (5, 40, 5), "kg": (200, 800, 50), "m": (50, 300, 25), "l": (40, 200, 20)}
EXPENSIVE = {"MOT-65": (2, 12), "MOT-90": (1, 6), "HID-P12": (2, 10), "RED-T3": (2, 8)}


@contextmanager
def acting_as(user):
    """Acțiunile din bloc apar în jurnal ca făcute de `user` (ambele jurnale de audit)."""
    with audit_context(actor=user), set_actor(user):
        yield


def moment(day, hour=9, minute=0):
    """Dată-oră locală (București) pentru o zi și o oră."""
    return timezone.make_aware(datetime.datetime.combine(day, datetime.time(hour, minute)))


@dataclass
class Story:
    """Ce s-a întâmplat cu o comandă: obiectele create, pe măsură ce agenda rulează."""

    label: str
    order: PurchaseOrder = None
    invoices: list = field(default_factory=list)


class DemoSeeder:
    def __init__(self, password, today=None, fetch_rates=True, now=None):
        self.password = password
        self.now = now or timezone.localtime()  # momentul generării (testele îl pot fixa)
        self.today = today or self.now.date()
        self.start = self.today - datetime.timedelta(days=HISTORY_DAYS)
        self.fetch_rates = fetch_rates
        self.random = random.Random(RANDOM_SEED)
        self.agenda = []  # (moment, ordine, cine, acțiune)
        self.planned_orders = []  # (zi, furnizor, valoare fără TVA): pentru bugete
        self.log = []  # ce s-a creat, pentru rezumatul afișat la final
        self.eur_rates = True

    # --- Ordinea generală ------------------------------------------------------------------

    def run(self):
        self.prepare_exchange_rates()
        self.create_base_data()
        self.plan_regular_activity()
        self.plan_requirement_scenarios()
        self.plan_budgets()
        self.plan_daily_digests()
        self.execute_agenda()
        self.summarize()
        return self.log

    def prepare_exchange_rates(self):
        """Cursurile BNR reale (arhiva anuală), pentru facturile în EUR. Fără ele, facturile
        EUR ar rămâne „în așteptare”: nu inventăm cursuri (I-28)."""
        if self.fetch_rates and currency.latest_rate_date() is None:
            syncs = currency.sync_rates(force=True)
            if not syncs or not syncs[-1].success:
                self.eur_rates = False
                self.log.append("BNR indisponibil: facturile în EUR rămân „în așteptare”.")

    def create_base_data(self):
        """Echipa și catalogul există dinaintea primei comenzi."""
        with travel_to(moment(self.start - datetime.timedelta(days=7))):
            self.users = create_team(self.password)
            with acting_as(self.users["andrei.ionescu"]):
                self.suppliers, self.products = create_catalog()
        self.buyers = [self.users["maria.pop"], self.users["radu.vasile"]]
        self.storekeeper = self.users["ion.marin"]
        self.accountant = self.users["elena.dobre"]

    # --- Agenda -----------------------------------------------------------------------------

    def at(self, day, hour, user, action):
        """Planifică `action` în ziua `day` (mutată pe o zi lucrătoare), dacă e în trecut."""
        day = self.workday(day)
        if day >= self.today:
            return False  # încă nu s-a întâmplat
        when = moment(day, hour, self.random.randrange(0, 60, 5))
        self.agenda.append((when, len(self.agenda), user, action))
        return True

    def workday(self, day):
        while not is_business_day(day):
            day += datetime.timedelta(days=1)
        return day

    def execute_agenda(self):
        for when, _, user, action in sorted(self.agenda, key=lambda item: item[:2]):
            with travel_to(when), acting_as(user):
                action()

    # --- Acțiunile (se execută la data lor) -------------------------------------------------

    def order(self, story, owner, supplier_key, items, order_day, expected_day):
        """Achizițiile creează și trimit comanda (o comandă = un furnizor, o monedă)."""

        def action():
            supplier = self.suppliers[supplier_key]
            order = PurchaseOrder(
                supplier=supplier,
                owner=owner,
                currency=supplier.default_currency,
                order_date=timezone.localdate(),
                expected_date=expected_day,
            )
            order.full_clean()
            order.save()
            for code, quantity in items:
                PurchaseOrderLine.objects.create(
                    order=order,
                    product=self.products[code],
                    quantity=D(quantity),
                    unit_price=price_of(code),
                    vat_rate=self.products[code].vat_rate,
                    expected_date=expected_day,
                )
            # Justificarea contează doar dacă depășește bugetul (o singură comandă, vezi
            # plan_budgets); altfel e ignorată.
            story.order = budgets.send_order(order, reason=OVER_BUDGET_REASON)

        scheduled = self.at(order_day, 10, owner, action)
        if scheduled:
            value = sum(D(quantity) * price_of(code) for code, quantity in items)
            self.planned_orders.append((self.workday(order_day), supplier_key, value))
        return scheduled

    def receive(self, story, day, quantities, extra=(), hour=11):
        """Depozitul numără marfa: {cod: cantitate} pe liniile comenzii; `extra` = marfă
        care nu e pe comandă [(cod, cantitate)]."""

        def action():
            order = story.order
            receipt = GoodsReceipt.objects.create(
                supplier=order.supplier, purchase_order=order, receipt_date=timezone.localdate()
            )
            for line in order.lines.select_related("product"):
                if line.product.code in quantities:
                    GoodsReceiptLine.objects.create(
                        receipt=receipt,
                        product=line.product,
                        order_line=line,
                        quantity_received=D(quantities[line.product.code]),
                    )
            for code, quantity in extra:
                GoodsReceiptLine.objects.create(
                    receipt=receipt, product=self.products[code], quantity_received=D(quantity)
                )
            warehouse.confirm_receipt(receipt, self.storekeeper)

        return self.at(day, hour, self.storekeeper, action)

    def receive_without_order(self, supplier_key, day, items):
        """Marfă venită fără comandă: intră în carantină și așteaptă Achizițiile."""

        def action():
            receipt = GoodsReceipt.objects.create(
                supplier=self.suppliers[supplier_key], receipt_date=timezone.localdate()
            )
            for code, quantity in items:
                GoodsReceiptLine.objects.create(
                    receipt=receipt, product=self.products[code], quantity_received=D(quantity)
                )
            warehouse.confirm_receipt(receipt, self.storekeeper)

        return self.at(day, 12, self.storekeeper, action)

    def invoice(self, story, day, quantities=None, prices=None, declared_total=None, then=None):
        """Contabilitatea înregistrează și validează factura furnizorului.

        Implicit: exact cantitățile recepționate, la prețul din comandă. `then(invoice)`
        rulează imediat după validare (ex. o verificare în scenariile speciale).
        """

        def action():
            order = story.order
            lines = PurchaseOrderLine.objects.with_progress().filter(order=order)
            wanted = quantities or {
                line.product.code: line.received_qty - line.invoiced_qty for line in lines
            }
            day_ = timezone.localdate()
            invoice = Invoice.objects.create(
                supplier=order.supplier,
                supplier_invoice_number=self.supplier_number(order),
                invoice_date=invoice_day or day_,
                due_date=(invoice_day or day_) + datetime.timedelta(days=30),
                currency=order.currency,
                declared_net=0,
                declared_vat=0,
                declared_total=0,
            )
            for line in lines.select_related("product"):
                quantity = D(wanted.get(line.product.code, 0))
                if quantity > 0:
                    InvoiceLine.objects.create(
                        invoice=invoice,
                        order_line=line,
                        quantity=quantity,
                        unit_price=D((prices or {}).get(line.product.code, line.unit_price)),
                        vat_rate=line.vat_rate,
                    )
            invoice.declared_net = invoice.computed_net
            invoice.declared_vat = invoice.computed_vat
            invoice.declared_total = declared_total or invoice.computed_total
            invoice.save()
            story.invoices.append(invoicing.validate_invoice(invoice))

        invoice_day = None
        if isinstance(day, tuple):  # (data facturii, data înregistrării)
            invoice_day, day = day
        return self.at(day, 14, self.accountant, action)

    def decide(self, story, day, decision, *args):
        """Aprobare / plată / forțare / respingere a ultimei facturi a comenzii."""

        def action():
            invoice = Invoice.objects.get(pk=story.invoices[-1].pk)
            if decision == "approve" and invoice.status == Invoice.Status.MATCHED:
                invoicing.approve_invoice(invoice, self.accountant)
            elif decision == "pay" and invoice.status == Invoice.Status.APPROVED:
                invoicing.mark_paid(invoice, timezone.localdate(), f"OP {invoice.pk:04d}")
            elif decision == "force" and invoice.status == Invoice.Status.BLOCKED:
                invoicing.force_approve_invoice(invoice, self.accountant, *args)
            elif decision == "reject" and invoice.status in (
                Invoice.Status.BLOCKED,
                Invoice.Status.REGISTERED,
            ):
                invoicing.reject_invoice(invoice, *args)

        hour = {"approve": 15, "pay": 12, "force": 16, "reject": 16}[decision]
        return self.at(day, hour, self.accountant, action)

    def consume(self, day, code, share):
        """Producția consumă o parte din stocul disponibil (cât există)."""

        def action():
            product = self.products[code]
            quantity = (available_stock(product) * D(share)).quantize(D("1"), ROUND_HALF_UP)
            if quantity > 0:
                warehouse.record_stock_movement(
                    product,
                    "CONSUMPTION",
                    quantity,
                    self.storekeeper,
                    "Consum pentru producția săptămânii",
                    date=timezone.localdate(),
                )

        return self.at(day, 16, self.storekeeper, action)

    def resolve(self, day, decision, note, product_code=None):
        """Achizițiile decid asupra mărfii din carantină (cea mai veche discrepanță deschisă)."""

        def action():
            open_ = Discrepancy.objects.filter(status=Discrepancy.Status.OPEN)
            if product_code:
                open_ = open_.filter(receipt_line__product__code=product_code)
            discrepancy = open_.order_by("created_at").first()
            if discrepancy is None:
                return
            if decision == "accept":
                warehouse.accept_over_delivery(discrepancy, self.buyers[0], note)
            else:
                warehouse.return_discrepancy(discrepancy, self.buyers[0], note)

        return self.at(day, 15, self.buyers[0], action)

    def supplier_number(self, order):
        """Numărul facturii, ca pe documentul furnizorului: prefix + număr."""
        prefix = "".join(word[0] for word in order.supplier.name.split()[:2]).upper()
        self._invoice_counter = getattr(self, "_invoice_counter", 1000) + 1
        return f"{prefix}-{self._invoice_counter}"

    # --- Activitatea obișnuită (dă formă graficelor) -----------------------------------------

    def plan_regular_activity(self):
        """~3 comenzi pe săptămână; furnizorii livrează după punctualitatea lor; facturile
        vin la câteva zile după marfă, se aprobă și se plătesc înainte de scadență."""
        rng = self.random
        catalog = {key: [c for c, p in PRODUCTS.items() if p[3] == key] for key in SUPPLIERS}
        week = self.start
        while week < self.today - datetime.timedelta(days=3):
            for slot in range(ORDERS_PER_WEEK):
                supplier = rng.choice(list(SUPPLIERS))
                if SUPPLIERS[supplier][3] == "EUR" and rng.random() < 0.5:
                    supplier = rng.choice(["rulmenti", "otel", "plastic", "vopsele"])
                codes = rng.sample(
                    catalog[supplier], k=min(len(catalog[supplier]), rng.randint(1, 2))
                )
                items = [(code, self.quantity(code)) for code in codes]
                order_day = week + datetime.timedelta(days=slot * 2)
                expected = self.workday(order_day + datetime.timedelta(days=rng.randint(7, 18)))
                story = Story(f"comandă obișnuită {supplier}")
                owner = self.buyers[(len(self.agenda) + slot) % 2]
                if not self.order(story, owner, supplier, items, order_day, expected):
                    continue
                self.plan_delivery_and_invoice(story, supplier, items, expected)
            for code in rng.sample(list(PRODUCTS), k=4):
                self.consume(week + datetime.timedelta(days=4), code, rng.choice([0.3, 0.5, 0.7]))
            week += datetime.timedelta(days=7)

    def plan_delivery_and_invoice(self, story, supplier, items, expected):
        rng = self.random
        everything = {code: quantity for code, quantity in items}
        if rng.random() < punctuality(supplier):
            arrival = expected - datetime.timedelta(days=rng.randint(0, 3))
            self.receive(story, arrival, everything)
        elif rng.random() < 0.5:  # două tranșe: o parte la termen, restul cu întârziere
            first = {code: max(1, int(quantity) // 2) for code, quantity in items}
            rest = {code: int(everything[code]) - first[code] for code in first}
            self.receive(story, expected - datetime.timedelta(days=1), first)
            arrival = expected + datetime.timedelta(days=rng.randint(3, 9))
            self.receive(story, arrival, rest)
        else:
            arrival = expected + datetime.timedelta(days=rng.randint(2, 12))
            self.receive(story, arrival, everything)

        if SUPPLIERS[supplier][3] == "EUR" and not self.eur_rates:
            return
        invoiced = arrival + datetime.timedelta(days=rng.randint(1, 5))
        if self.invoice(story, invoiced):
            approved = invoiced + datetime.timedelta(days=rng.randint(1, 3))
            if self.decide(story, approved, "approve"):
                self.decide(story, approved + datetime.timedelta(days=rng.randint(5, 25)), "pay")

    def quantity(self, code):
        if code in EXPENSIVE:
            return self.random.randint(*EXPENSIVE[code])
        low, high, step = QUANTITIES[PRODUCTS[code][1]]
        return self.random.randrange(low, high + 1, step)

    # --- Fiecare situație din cerință, garantat, aproape de azi -----------------------------

    def ago(self, days):
        return self.today - datetime.timedelta(days=days)

    def plan_requirement_scenarios(self):
        maria, radu = self.buyers
        self.scenarios = {}

        # 1. Livrare în două tranșe, facturată corect, aprobată și plătită.
        two = self.scenario("Livrare în două tranșe, facturată și plătită")
        self.order(
            two,
            maria,
            "rulmenti",
            [("RUL-6204", 200), ("CUR-A42", 120)],
            self.ago(32),
            self.ago(22),
        )
        self.receive(two, self.ago(23), {"RUL-6204": 120, "CUR-A42": 120})
        self.receive(two, self.ago(15), {"RUL-6204": 80})
        self.invoice(two, self.ago(13))
        self.decide(two, self.ago(12), "approve")
        self.decide(two, self.ago(6), "pay")

        # 2. Livrare parțială + factură pe tot: blocată (facturat, dar nerecepționat),
        #    iar comanda e și întârziată (15 filtre nesosite).
        partial = self.scenario("Livrare parțială, factură pe tot (blocată: marfă nesosită)")
        self.order(
            partial, maria, "motoare", [("MOT-65", 12), ("FIL-A20", 40)], self.ago(24), self.ago(8)
        )
        self.receive(partial, self.ago(9), {"MOT-65": 12, "FIL-A20": 25})
        self.invoice(partial, self.ago(5), quantities={"MOT-65": 12, "FIL-A20": 40})

        # 3. Factură cu preț greșit: blocată (preț diferit).
        price = self.scenario("Factură cu preț diferit de comandă (blocată)")
        self.order(
            price, radu, "vopsele", [("VOP-R", 160), ("VOP-G", 80)], self.ago(20), self.ago(11)
        )
        self.receive(price, self.ago(11), {"VOP-R": 160, "VOP-G": 80})
        self.invoice(price, self.ago(7), prices={"VOP-R": "39.50"})

        # 4. Marfă necomandată: în carantină, așteaptă decizia Achizițiilor.
        self.scenario("Marfă necomandată (în carantină)")
        self.receive_without_order("plastic", self.ago(3), [("PLA-M2", 30)])

        # 5. Livrare peste comandă: surplusul așteaptă decizia responsabilului.
        over = self.scenario("Livrare peste comandă (surplus în carantină)")
        self.order(over, radu, "otel", [("TAB-2", 500)], self.ago(14), self.ago(4))
        self.receive(over, self.ago(4), {"TAB-2": 540})

        # 6. Comandă întârziată, nimic sosit.
        late = self.scenario("Comandă întârziată (nimic sosit)")
        self.order(
            late, radu, "electrice", [("CAB-15", 250), ("COM-P1", 40)], self.ago(19), self.ago(6)
        )

        # 7. Factură în EUR emisă sâmbăta: se aplică cursul BNR de vineri.
        if self.eur_rates:
            saturday = self.ago(14)
            while saturday.weekday() != 5:
                saturday -= datetime.timedelta(days=1)
            eur = self.scenario("Factură în EUR emisă sâmbăta (curs de vineri)")
            self.order(
                eur,
                maria,
                "hidraulic",
                [("HID-P12", 6), ("HID-F10", 120)],
                saturday - datetime.timedelta(days=16),
                saturday - datetime.timedelta(days=4),
            )
            self.receive(eur, saturday - datetime.timedelta(days=5), {"HID-P12": 6, "HID-F10": 120})
            self.invoice(eur, (saturday, saturday + datetime.timedelta(days=2)))
            self.decide(eur, saturday + datetime.timedelta(days=3), "approve")

            # 8. Factură forțată la plată, cu justificare (diferență de preț acceptată).
            forced = self.scenario("Factură blocată, forțată la plată cu justificare")
            self.order(
                forced,
                radu,
                "transmisii",
                [("RED-T3", 4), ("AMB-K2", 10)],
                self.ago(40),
                self.ago(28),
            )
            self.receive(forced, self.ago(28), {"RED-T3": 4, "AMB-K2": 10})
            self.invoice(forced, self.ago(25), prices={"AMB-K2": "98.40"})
            self.decide(
                forced,
                self.ago(24),
                "force",
                "Furnizorul a aplicat noua listă de prețuri (+2,5%); acceptat telefonic de "
                "Radu Vasile, care a confirmat cu directorul de achiziții.",
            )

        # 9. Factură respinsă: furnizorul a facturat de două ori aceeași livrare.
        twice = self.scenario("Factură duplicat, respinsă")
        self.order(twice, maria, "plastic", [("PLA-C1", 60)], self.ago(30), self.ago(21))
        self.receive(twice, self.ago(21), {"PLA-C1": 60})
        self.invoice(twice, self.ago(19))
        self.decide(twice, self.ago(18), "approve")
        self.invoice(twice, self.ago(10), quantities={"PLA-C1": 60})
        self.decide(
            twice,
            self.ago(9),
            "reject",
            "Aceeași livrare facturată a doua oară; furnizorul a confirmat stornarea.",
        )

        # 10. Factură potrivită, dar neaprobată de peste 3 zile lucrătoare.
        waiting = self.scenario("Factură potrivită, neaprobată de câteva zile")
        self.order(waiting, maria, "rulmenti", [("RUL-6305", 90)], self.ago(26), self.ago(16))
        self.receive(waiting, self.ago(16), {"RUL-6305": 90})
        self.invoice(waiting, self.ago(8))

        # 11. Facturi aprobate: una cu scadența peste 2 zile, una cu scadența depășită.
        due = self.scenario("Factură aprobată cu scadența apropiată")
        self.order(due, radu, "otel", [("TEV-30", 150)], self.ago(45), self.ago(35))
        self.receive(due, self.ago(35), {"TEV-30": 150})
        self.invoice(due, (self.ago(28), self.ago(27)))
        self.decide(due, self.ago(26), "approve")
        overdue = self.scenario("Factură aprobată cu scadența depășită")
        self.order(overdue, maria, "vopsele", [("VOP-G", 120)], self.ago(50), self.ago(40))
        self.receive(overdue, self.ago(40), {"VOP-G": 120})
        self.invoice(overdue, (self.ago(34), self.ago(33)))
        self.decide(overdue, self.ago(32), "approve")

        # 12. Surplus din trecut acceptat, marfă necomandată returnată (istoricul discrepanțelor).
        accepted = self.scenario("Surplus acceptat de Achiziții (rezolvat)")
        self.order(accepted, maria, "rulmenti", [("RUL-6204", 100)], self.ago(60), self.ago(50))
        self.receive(accepted, self.ago(50), {"RUL-6204": 110})
        self.resolve(self.ago(48), "accept", "Surplus util, acceptat pe comandă.", "RUL-6204")
        self.receive_without_order("electrice", self.ago(44), [("COM-P1", 15)])
        self.resolve(self.ago(43), "return", "Necomandat; returnat furnizorului.", "COM-P1")

        # 13. Livrări așteptate în zilele următoare (panoul și graficul Depozitului).
        for offset, (owner, supplier, items) in enumerate(
            [
                (maria, "motoare", [("MOT-90", 3)]),
                (radu, "plastic", [("PLA-C1", 80)]),
                (maria, "rulmenti", [("RUL-6204", 150)]),
                (radu, "vopsele", [("VOP-R", 100)]),
            ]
        ):
            soon = self.scenario(f"Livrare așteptată în {offset * 3} zile")
            self.order(
                soon,
                owner,
                supplier,
                items,
                self.ago(6 + offset),
                self.today + datetime.timedelta(days=offset * 3),
            )

    def scenario(self, label):
        story = Story(label)
        self.scenarios[label] = story
        return story

    # --- Bugetele anului ----------------------------------------------------------------------

    def plan_budgets(self):
        """Contabilitatea stabilește bugetele anului înaintea primei comenzi din an.

        Sumele vin din comenzile deja planificate (BUDGET_USAGE). Furnizorul „depășit”
        primește un buget care ajunge pentru toate comenzile, mai puțin jumătate din
        ultima: aceea se trimite peste buget, cu justificare, ca în realitate.
        """
        year = self.today.year
        totals, last = {}, {}
        for day, supplier, value in sorted(self.planned_orders):
            if day.year == year:
                totals[supplier] = totals.get(supplier, D(0)) + value
                last[supplier] = value
        first_day = self.workday(max(self.start, datetime.date(year, 1, 1)))

        def action():
            for key, supplier in self.suppliers.items():
                total = totals.get(key, D(0))
                if key == OVER_BUDGET_SUPPLIER and total:
                    amount = total - last[key] / 2
                elif total:
                    amount = total / D(str(BUDGET_USAGE[key]))
                else:  # nicio comandă în acest an (încă): un plafon obișnuit
                    amount = D(20000)
                budget = SupplierBudget(
                    supplier=supplier,
                    year=year,
                    amount=(amount / 100).quantize(D(1), rounding=ROUND_HALF_UP) * 100,
                    notes=f"Contract-cadru {year}",
                )
                budget.full_clean()
                budget.save()

        self.agenda.append((moment(first_day, 8, 30), len(self.agenda), self.accountant, action))

    # --- Rezumatele de pe email din ultimele zile -------------------------------------------

    def plan_daily_digests(self):
        """Rezumatele zilnice din ultimele zile lucrătoare: pagina „Notificări trimise” are
        istoric, iar marcajul NOU funcționează deja la primul rezumat real.

        Dacă generarea are loc azi după ora rezumatului, se simulează și rezumatul de azi
        (la ora obișnuită, ca în zilele trecute), ca istoria demo să fie uniformă.
        """
        days = []
        today_at = moment(self.today, settings.NOTIFICATION_HOUR, 5)
        self.digest_today = is_business_day(self.today) and self.now >= today_at
        if self.digest_today:
            days.append(self.today)
        day = self.today - datetime.timedelta(days=1)
        while len(days) < DIGEST_DAYS + self.digest_today:
            if is_business_day(day):
                days.append(day)
            day -= datetime.timedelta(days=1)
        for day in days:
            when = moment(day, settings.NOTIFICATION_HOUR, 5)
            self.agenda.append(
                (
                    when,
                    len(self.agenda),
                    None,
                    lambda w=when: notifications.send_daily_digests(now=w),
                )
            )

    # --- Rezumat -----------------------------------------------------------------------------

    def summarize(self):
        counts = {
            "comenzi": PurchaseOrder.objects.count(),
            "recepții": GoodsReceipt.objects.count(),
            "facturi": Invoice.objects.count(),
        }
        self.log.append(
            f"{len(self.users)} utilizatori, {len(self.suppliers)} furnizori, "
            f"{len(self.products)} produse"
        )
        self.log.append(", ".join(f"{count} {name}" for name, count in counts.items()))
        statuses = Invoice.objects.values_list("status", flat=True)
        by_status = {Invoice.Status(s).label: list(statuses).count(s) for s in set(statuses)}
        self.log.append(
            "facturi: "
            + ", ".join(f"{n} {label.lower()}" for label, n in sorted(by_status.items()))
        )
        self.log.append(f"{len(self.scenarios)} situații din cerință: " + "; ".join(self.scenarios))
        levels = [status.level for status in budgets.statuses(self.today.year)]
        self.log.append(
            f"bugete {self.today.year}: {len(levels)} ({levels.count('over')} depășit, "
            f"{levels.count('warning')} aproape consumat)"
        )
