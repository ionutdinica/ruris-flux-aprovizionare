"""Cardurile panoului și listele la care duc nu se pot contrazice.

Pe datele demo complete, pentru fiecare utilizator: „clic” pe fiecare card, iar lista
deschisă trebuie să aibă exact numărul de pe card (pentru sume: numărul de facturi).
Greșeala prinsă la testarea manuală: cardul „Comenzile mele întârziate: 1” ducea la o
listă cu 3 comenzi (ale tuturor, nu doar ale mele).
"""

import pytest
from django.db import transaction
from django.urls import reverse

from apps.accounts.models import User
from apps.demo.catalog import TEAM
from apps.demo.testing import seed_demo_for_tests


@pytest.fixture(scope="module")
def demo(django_db_setup, django_db_blocker):
    with django_db_blocker.unblock(), transaction.atomic():
        yield seed_demo_for_tests()
        transaction.set_rollback(True)


pytestmark = pytest.mark.django_db


def listed(response):
    paginator = response.context.get("paginator")
    return paginator.count if paginator else len(response.context["object_list"])


@pytest.mark.parametrize("username", [member[0] for member in TEAM])
def test_every_card_matches_its_list(demo, client, username):
    client.force_login(User.objects.get(username=username))
    cards = client.get(reverse("dashboard:home")).context["kpis"]

    assert cards
    mismatches = []
    for card in cards:
        shown = listed(client.get(card.url))
        if shown != card.list_count:
            mismatches.append(f"{card.label}: card {card.list_count}, listă {shown} ({card.url})")
    assert not mismatches, mismatches


def test_mine_filter_is_offered_only_to_order_owners(demo, client):
    client.force_login(User.objects.get(username="maria.pop"))
    assert "Doar ale mele" in client.get(reverse("purchasing:order_list")).content.decode()

    client.force_login(User.objects.get(username="ion.marin"))
    response = client.get(reverse("warehouse:discrepancy_list"), {"ale_mele": "1"})
    assert "Doar ale mele" not in response.content.decode()
    # Fără opțiune, parametrul e ignorat: Depozitul vede toată carantina.
    assert listed(response) == listed(client.get(reverse("warehouse:discrepancy_list")))
