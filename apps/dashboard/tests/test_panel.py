"""Panoul pe rol: cifrele-cheie, lista „De rezolvat”, ce NU vede fiecare rol."""

import datetime
import re

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.accounts.tests.factories import UserFactory
from apps.invoicing.services import approve_invoice
from apps.invoicing.tests.scenarios import validated
from apps.purchasing.models import PurchaseOrder, PurchaseOrderLine
from apps.warehouse.models import GoodsReceipt
from apps.warehouse.tests.scenarios import receive, sent_order

pytestmark = pytest.mark.django_db

HOME = reverse("dashboard:home")
TODAY = timezone.localdate()


def kpis(response):
    return {kpi.label: kpi.value for kpi in response.context["kpis"]}


@pytest.fixture
def situation(procurement_user, warehouse_user, accounting_user):
    """O zi obișnuită: o comandă a Mariei întârziată (6 din 10 sosite), facturată
    integral (deci blocată), cu 2 bucăți în plus în carantină pe altă comandă."""
    late = sent_order("10")
    PurchaseOrder.objects.filter(pk=late.pk).update(owner=procurement_user)
    PurchaseOrderLine.objects.filter(order=late).update(
        expected_date=TODAY - datetime.timedelta(days=3)
    )
    receive(late, warehouse_user, "6")
    invoice = validated(late, "10")

    surplus = sent_order("5")
    PurchaseOrder.objects.filter(pk=surplus.pk).update(owner=procurement_user)
    receive(surplus, warehouse_user, "7")
    return {"late": late, "invoice": invoice, "surplus": surplus}


def test_procurement_panel(client, procurement_user, situation):
    client.force_login(procurement_user)

    response = client.get(HOME)

    assert kpis(response) == {
        "Comenzile mele întârziate": 1,
        "Marfă în carantină": 1,
        "Facturi blocate": 1,
        "Comenzile mele deschise": 1,  # comanda cu surplus e recepționată complet
    }
    html = response.content.decode()
    assert "De rezolvat" in html and situation["late"].number in html
    assert response.context["alert_count"] == 3


def test_warehouse_panel_has_no_money(client, warehouse_user, situation):
    """Depozitul nu vede prețuri, valori sau facturi (docs/04-permisiuni.md)."""
    GoodsReceipt.objects.create(supplier=situation["late"].supplier)  # o ciornă
    client.force_login(warehouse_user)

    response = client.get(HOME)

    assert kpis(response) == {
        "Livrări așteptate azi": 0,
        "Comenzi întârziate": 1,
        "Marfă în carantină": 1,
        "Recepții în ciornă": 1,
    }
    html = response.content.decode()
    assert "lei" not in html and "RON" not in html
    assert situation["invoice"].number not in html
    assert not re.search(r"\d+,\d{2}\b", html)  # nicio sumă de bani (ex. 1.210,00)


def test_accounting_panel(client, accounting_user, warehouse_user, situation):
    paid_soon = sent_order("2")
    receive(paid_soon, warehouse_user, "2")
    approve_invoice(validated(paid_soon, "2"), accounting_user)  # 2 × 100 + TVA = 242
    client.force_login(accounting_user)

    response = client.get(HOME)

    values = kpis(response)
    assert values["Facturi de rezolvat"] == 1
    assert values["Valoarea facturilor blocate"] == situation["invoice"].total_ron
    assert values["De plătit în 7 zile"] == 0  # scadența e peste 30 de zile
    assert values["Scadențe depășite"] == 0
    assert "1.210,00" in response.content.decode()  # valoarea blocată, formatată


def test_admin_sees_the_whole_company(client, admin_user, situation):
    client.force_login(admin_user)

    response = client.get(HOME)

    assert "Probleme deschise în firmă" in response.content.decode()
    assert response.context["alert_count"] == 3
    assert kpis(response)["Comenzi întârziate"] == 1


def test_others_only_see_what_concerns_them(client, situation):
    """Un alt om din Achiziții nu vede problemele comenzilor Mariei."""
    colleague = UserFactory(role="PROCUREMENT")
    client.force_login(colleague)

    response = client.get(HOME)

    assert response.context["alert_count"] == 0
    assert "Nimic de rezolvat acum" in response.content.decode()


def test_panel_and_email_show_the_same_problems(client, procurement_user, situation):
    """Aceeași sursă: ce arată panoul e exact ce ar conține emailul de azi."""
    from apps.notifications.alerts import alerts_for

    client.force_login(procurement_user)
    response = client.get(HOME)

    shown = [alert.key for section in response.context["sections"] for alert in section["alerts"]]
    assert shown == [alert.key for alert in alerts_for(procurement_user)]


def test_kpi_cards_link_to_filtered_lists(client, procurement_user, situation):
    client.force_login(procurement_user)

    html = client.get(HOME).content.decode()

    assert f'href="{reverse("purchasing:order_list")}?status=late"' in html


def test_admin_list_is_capped(client, admin_user, procurement_user):
    for _ in range(17):
        order = sent_order("1")
        PurchaseOrderLine.objects.filter(order=order).update(
            expected_date=TODAY - datetime.timedelta(days=1)
        )
    client.force_login(admin_user)

    response = client.get(HOME)

    assert response.context["hidden_count"] == 2
    assert "… și încă 2." in response.content.decode()
