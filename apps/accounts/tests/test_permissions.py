"""Permisiunile trebuie să corespundă exact matricei din docs/04-permisiuni.md.

Matricea e rescrisă aici intenționat, independent de cod: dacă cineva schimbă
o permisiune în apps/accounts/permissions.py fără să schimbe documentația
(și acest test), testul pică.
"""

import pytest
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.template import Context, Template
from django.test import RequestFactory
from django.views import View

from apps.accounts.models import User
from apps.accounts.permissions import PERMISSIONS, PermissionMixin, has_permission

from .factories import UserFactory

# Coloane: Achiziții, Depozit, Contabilitate, Admin   (1 = are voie, 0 = nu)
EXPECTED_MATRIX = {
    "catalog.view":            (1, 1, 1, 1),
    "catalog.edit":            (1, 0, 0, 1),
    "orders.view":             (1, 1, 1, 1),
    "orders.view_prices":      (1, 0, 1, 1),
    "orders.edit":             (1, 0, 0, 1),
    "orders.import":           (1, 0, 0, 1),
    "orders.export":           (1, 0, 1, 1),
    "receipts.view":           (1, 1, 1, 1),
    "receipts.edit":           (0, 1, 0, 1),
    "discrepancies.view":      (1, 1, 1, 1),
    "discrepancies.resolve":   (1, 0, 0, 1),
    "stock.view":              (1, 1, 1, 1),
    "stock.move":              (0, 1, 0, 1),
    "invoices.view":           (1, 0, 1, 1),
    "invoices.view_payment":   (0, 0, 1, 1),
    "invoices.edit":           (0, 0, 1, 1),
    "rates.view":              (1, 0, 1, 1),
    "rates.refresh":           (0, 0, 1, 1),
    "alerts.view_all":         (0, 0, 0, 1),
    "system.view":             (0, 0, 0, 1),
    "notifications.view_own":  (1, 1, 1, 1),
    "notifications.view_all":  (0, 0, 0, 1),
    "notifications.send_now":  (0, 0, 0, 1),
    "audit.view":              (0, 0, 0, 1),
    "users.manage":            (0, 0, 0, 1),
}  # fmt: skip
ROLES = (User.Role.PROCUREMENT, User.Role.WAREHOUSE, User.Role.ACCOUNTING, User.Role.ADMIN)


def test_matrix_covers_exactly_the_same_permissions():
    assert set(PERMISSIONS) == set(EXPECTED_MATRIX)


@pytest.mark.parametrize("permission", EXPECTED_MATRIX)
@pytest.mark.parametrize("role_index", range(4))
def test_permission_matrix(permission, role_index):
    user = User(role=ROLES[role_index])
    expected = bool(EXPECTED_MATRIX[permission][role_index])

    assert user.can(permission) is expected


def test_unknown_permission_fails_loudly():
    """O greșeală de scriere nu trebuie să ascundă în tăcere o pagină."""
    with pytest.raises(KeyError):
        User(role=User.Role.ADMIN).can("orders.edti")


def test_inactive_user_has_no_permissions():
    user = User(role=User.Role.ADMIN, is_active=False)

    assert not user.can("orders.view")


def test_user_without_role_has_no_permissions():
    assert not User(role="").can("orders.view")


def test_anonymous_user_has_no_permissions():
    from django.contrib.auth.models import AnonymousUser

    assert not has_permission(AnonymousUser(), "orders.view")


# --- PermissionMixin -------------------------------------------------------------


class EditOrdersView(PermissionMixin, View):
    permission = "orders.edit"

    def get(self, request):
        return HttpResponse("ok")


@pytest.mark.django_db
def test_mixin_allows_user_with_permission():
    request = RequestFactory().get("/")
    request.user = UserFactory(role=User.Role.PROCUREMENT)

    assert EditOrdersView.as_view()(request).status_code == 200


@pytest.mark.django_db
def test_mixin_denies_user_without_permission():
    request = RequestFactory().get("/")
    request.user = UserFactory(role=User.Role.WAREHOUSE)

    with pytest.raises(PermissionDenied):
        EditOrdersView.as_view()(request)


def test_mixin_requires_permission_attribute():
    class Forgotten(PermissionMixin, View):
        pass

    request = RequestFactory().get("/")
    request.user = User(role=User.Role.ADMIN)

    with pytest.raises(ValueError, match="permission"):
        Forgotten.as_view()(request)


# --- Filtrul din șabloane ----------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "visible"), [(User.Role.ACCOUNTING, True), (User.Role.WAREHOUSE, False)]
)
def test_template_filter(role, visible):
    template = Template(
        '{% load permissions %}{% if user|can:"orders.view_prices" %}PRET{% endif %}'
    )

    html = template.render(Context({"user": User(role=role)}))

    assert ("PRET" in html) is visible
