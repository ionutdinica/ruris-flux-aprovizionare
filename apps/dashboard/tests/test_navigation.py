"""Meniul pe rol trebuie să corespundă matricei din docs/04-permisiuni.md."""

import pytest

from apps.accounts.models import User
from apps.dashboard.navigation import build_menu

R = User.Role


def labels(menu):
    """Transformă meniul într-o listă simplă de etichete, ușor de comparat."""
    result = []
    for entry in menu:
        result.append(entry["label"])
        result.extend(f"{entry['label']} > {c['label']}" for c in entry.get("children", []))
    return result


def menu_for(role):
    return labels(build_menu(User(role=role), "/"))


@pytest.mark.parametrize("role", list(R))
def test_every_role_sees_common_pages(role):
    menu = menu_for(role)
    for label in ["Panou", "Comenzi", "Recepții", "Discrepanțe", "Stoc"]:
        assert label in menu


def test_warehouse_does_not_see_invoices_or_exchange_rates():
    menu = menu_for(R.WAREHOUSE)

    assert "Facturi" not in menu
    assert "Nomenclatoare > Cursuri BNR" not in menu
    assert "Nomenclatoare > Furnizori" in menu


@pytest.mark.parametrize("role", [R.PROCUREMENT, R.ACCOUNTING, R.ADMIN])
def test_invoices_visible_for_procurement_accounting_admin(role):
    assert "Facturi" in menu_for(role)


@pytest.mark.parametrize("role", [R.PROCUREMENT, R.WAREHOUSE, R.ACCOUNTING])
def test_administration_group_hidden_for_non_admins(role):
    """Un grup fără niciun element vizibil nu apare deloc."""
    assert not any(label.startswith("Administrare") for label in menu_for(role))


def test_admin_sees_administration():
    menu = menu_for(R.ADMIN)

    assert "Administrare > Jurnal de activitate" in menu
    assert "Administrare > Utilizatori" in menu


def test_pages_not_built_yet_have_no_url():
    """Paginile din capitolele viitoare apar ca „în curând” (fără link)."""
    menu = {e["label"]: e for e in build_menu(User(role=R.ADMIN), "/")}

    assert menu["Panou"]["url"] == "/"
    assert menu["Comenzi"]["url"] is None


def test_active_item():
    menu = {e["label"]: e for e in build_menu(User(role=R.ADMIN), "/")}

    assert menu["Panou"]["active"] is True
