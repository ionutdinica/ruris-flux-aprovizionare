"""Meniul principal al aplicației, filtrat după rolul utilizatorului.

Meniul e definit o singură dată, aici, ca date. Fiecare element spune ce
roluri îl văd (conform docs/04-permisiuni.md). Șablonul doar afișează ce
primește, fără logică de permisiuni în HTML.

Elementele ale căror pagini nu există încă (capitolele viitoare) apar
dezactivate, cu eticheta „în curând”, și devin active automat când
pagina respectivă este adăugată.
"""

from dataclasses import dataclass

from django.urls import NoReverseMatch, reverse

from apps.accounts.models import User

R = User.Role
ALL_ROLES = (R.PROCUREMENT, R.WAREHOUSE, R.ACCOUNTING, R.ADMIN)


@dataclass(frozen=True)
class MenuItem:
    label: str
    icon: str  # numele unei iconițe Bootstrap Icons, ex. "cart"
    url_name: str  # numele rutei Django, ex. "purchasing:order_list"
    roles: tuple = ALL_ROLES


@dataclass(frozen=True)
class MenuGroup:
    """Un meniu derulant (dropdown) cu mai multe elemente."""

    label: str
    icon: str
    items: tuple


MENU = (
    MenuItem("Panou", "speedometer2", "dashboard:home"),
    MenuItem("Comenzi", "cart", "purchasing:order_list"),
    MenuItem("Recepții", "box-seam", "warehouse:receipt_list"),
    MenuItem("Discrepanțe", "exclamation-triangle", "warehouse:discrepancy_list"),
    MenuItem("Stoc", "boxes", "warehouse:stock"),
    MenuItem(
        "Facturi", "receipt", "invoicing:invoice_list", (R.PROCUREMENT, R.ACCOUNTING, R.ADMIN)
    ),
    MenuGroup(
        "Nomenclatoare",
        "journal-text",
        (
            MenuItem("Furnizori", "truck", "catalog:supplier_list"),
            MenuItem("Produse", "tag", "catalog:product_list"),
            MenuItem(
                "Cursuri BNR",
                "currency-exchange",
                "currency:rate_list",
                (R.PROCUREMENT, R.ACCOUNTING, R.ADMIN),
            ),
        ),
    ),
    MenuGroup(
        "Administrare",
        "gear",
        (
            MenuItem("Jurnal de activitate", "clock-history", "audit:log", (R.ADMIN,)),
            MenuItem("Notificări trimise", "envelope", "notifications:log", (R.ADMIN,)),
            MenuItem("Utilizatori", "people", "admin:accounts_user_changelist", (R.ADMIN,)),
        ),
    ),
)


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
            items = [_resolve(i, current_path) for i in entry.items if user.has_role(*i.roles)]
            if items:  # un grup fără niciun element vizibil nu se afișează
                menu.append({"label": entry.label, "icon": entry.icon, "children": items})
        elif user.has_role(*entry.roles):
            menu.append(_resolve(entry, current_path))
    return menu
