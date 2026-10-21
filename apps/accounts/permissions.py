"""Matricea de permisiuni a aplicației – sursa unică de adevăr în cod.

Fiecare acțiune are o cheie (ex. "orders.edit") și lista rolurilor care o pot
face. Este transcrierea directă a tabelului din docs/04-permisiuni.md.

Restul aplicației nu verifică niciodată roluri direct, ci doar permisiuni:
    user.can("orders.edit")                          – în Python
    {% if user|can:"orders.view_prices" %}           – în șabloane
    permission = "orders.edit"                       – pe un view (PermissionMixin)
Astfel, dacă o regulă de acces se schimbă, se schimbă într-un singur loc.
"""

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

from .models import User

R = User.Role
P, W, A, ADMIN = R.PROCUREMENT, R.WAREHOUSE, R.ACCOUNTING, R.ADMIN
ALL = frozenset(R)

PERMISSIONS = {
    # Nomenclatoare: furnizori, produse
    "catalog.view": ALL,
    "catalog.edit": {P, ADMIN},
    # Comenzi
    "orders.view": ALL,
    "orders.view_prices": {P, A, ADMIN},  # Depozitul vede comenzile fără prețuri
    "orders.edit": {P, ADMIN},  # creare, editare, trimitere, anulare, închidere
    "orders.import": {P, ADMIN},
    "orders.export": {P, A, ADMIN},
    # Recepții
    "receipts.view": ALL,
    "receipts.edit": {W, ADMIN},  # creare, confirmare
    # Discrepanțe (marfă în carantină)
    "discrepancies.view": ALL,
    "discrepancies.resolve": {P, ADMIN},  # atașare la comandă / retur
    # Stoc
    "stock.view": ALL,
    "stock.move": {W, ADMIN},  # consum, retur, ajustare de inventar
    # Facturi
    "invoices.view": {P, A, ADMIN},  # Achizițiile văd statusul și motivele de blocare
    "invoices.view_payment": {A, ADMIN},  # detaliile de plată
    "invoices.edit": {A, ADMIN},  # înregistrare, validare, aprobare, forțare, plată
    # Cursuri BNR
    "rates.view": {P, A, ADMIN},
    "rates.refresh": {A, ADMIN},  # „Actualizează acum” (altfel automat, zilnic)
    # Panou: problemele întregii firme (ceilalți văd doar problemele care îi privesc)
    "alerts.view_all": {ADMIN},
    # Notificări
    "notifications.view_own": ALL,  # fiecare își vede emailurile primite
    "notifications.view_all": {ADMIN},
    "notifications.send_now": {ADMIN},
    # Administrare
    "audit.view": {ADMIN},  # jurnalul global de activitate
    "users.manage": {ADMIN},
}


def has_permission(user, permission):
    """Poate `user` să facă acțiunea `permission`?

    O cheie necunoscută (ex. o greșeală de scriere) ridică KeyError în loc să
    întoarcă în tăcere False – așa greșelile se văd imediat, în teste.
    """
    allowed_roles = PERMISSIONS[permission]
    return bool(user.is_authenticated and user.is_active and user.role in allowed_roles)


class PermissionMixin:
    """Pentru view-uri (clase): permite accesul doar cu permisiunea dată.

        class OrderCreateView(PermissionMixin, CreateView):
            permission = "orders.edit"

    Fără permisiune → 403 Interzis (cu pagina templates/403.html).
    """

    permission = None

    def dispatch(self, request, *args, **kwargs):
        if self.permission is None:
            raise ValueError(f"{type(self).__name__}: lipsește atributul `permission`.")
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not has_permission(request.user, self.permission):
            raise PermissionDenied
        return super().dispatch(request, *args, **kwargs)
