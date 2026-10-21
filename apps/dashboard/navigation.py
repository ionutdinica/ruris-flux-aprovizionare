"""Meniul principal al aplicației, filtrat după permisiunile utilizatorului.

Meniul e definit o singură dată, aici, ca date. Fiecare element spune ce
permisiune trebuie să aibă utilizatorul ca să-l vadă (vezi
apps/accounts/permissions.py). Șablonul doar afișează ce primește,
fără logică de permisiuni în HTML.

Elementele ale căror pagini nu există încă (capitolele viitoare) apar
dezactivate, cu eticheta „în curând”, și devin active automat când
pagina respectivă este adăugată.
"""

from dataclasses import dataclass

from django.urls import NoReverseMatch, reverse


@dataclass(frozen=True)
class MenuItem:
    label: str
    icon: str  # numele unei iconițe Bootstrap Icons, ex. "cart"
    url_name: str  # numele rutei Django, ex. "purchasing:order_list"
    permission: str | None = None  # None = vizibil pentru orice utilizator autentificat


@dataclass(frozen=True)
class MenuGroup:
    """Un meniu derulant (dropdown) cu mai multe elemente."""

    label: str
    icon: str
    items: tuple


MENU = (
    MenuItem("Panou", "speedometer2", "dashboard:home"),
    MenuItem("Comenzi", "cart", "purchasing:order_list", "orders.view"),
    MenuItem("Recepții", "box-seam", "warehouse:receipt_list", "receipts.view"),
    MenuItem(
        "Discrepanțe", "exclamation-triangle", "warehouse:discrepancy_list", "discrepancies.view"
    ),
    MenuItem("Stoc", "boxes", "warehouse:stock", "stock.view"),
    MenuItem("Facturi", "receipt", "invoicing:invoice_list", "invoices.view"),
    MenuItem("Bugete", "piggy-bank", "budgets:budget_list", "budgets.view"),
    MenuGroup(
        "Nomenclatoare",
        "journal-text",
        (
            MenuItem("Furnizori", "truck", "catalog:supplier_list", "catalog.view"),
            MenuItem("Produse", "tag", "catalog:product_list", "catalog.view"),
            MenuItem("Cursuri BNR", "currency-exchange", "currency:rate_list", "rates.view"),
        ),
    ),
    MenuGroup(
        "Administrare",
        "gear",
        (
            MenuItem("Jurnal de activitate", "clock-history", "audit:log", "audit.view"),
            MenuItem(
                "Notificări trimise", "envelope", "notifications:log", "notifications.view_all"
            ),
            MenuItem("Utilizatori", "people", "admin:accounts_user_changelist", "users.manage"),
        ),
    ),
)


def _visible(item, user):
    return item.permission is None or user.can(item.permission)


def _resolve(item, current_path):
    try:
        url = reverse(item.url_name)
    except NoReverseMatch:
        url = None  # pagina nu există încă
    # Elementul e „activ” (evidențiat) dacă suntem pe pagina lui sau pe o subpagină.
    # Excepție: "/" (Panou) e activ doar pe pagina de start, altfel ar fi mereu activ.
    active = url is not None and (
        current_path == url or (url != "/" and current_path.startswith(url))
    )
    return {"label": item.label, "icon": item.icon, "url": url, "active": active}


def build_menu(user, current_path):
    """Întoarce meniul vizibil pentru `user`, gata de afișat în șablon."""
    menu = []
    for entry in MENU:
        if isinstance(entry, MenuGroup):
            items = [_resolve(i, current_path) for i in entry.items if _visible(i, user)]
            if items:  # un grup fără niciun element vizibil nu se afișează
                menu.append({"label": entry.label, "icon": entry.icon, "children": items})
        elif _visible(entry, user):
            menu.append(_resolve(entry, current_path))
    return menu
