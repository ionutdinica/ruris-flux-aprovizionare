import pytest
from django.urls import reverse

pytestmark = pytest.mark.django_db


def test_home_shows_user_role_and_menu(client, warehouse_user):
    client.force_login(warehouse_user)

    response = client.get(reverse("dashboard:home"))
    html = response.content.decode()

    assert response.status_code == 200
    assert "Depozit" in html  # rolul afișat
    assert "Recepții" in html  # element de meniu vizibil pentru Depozit
    assert "Facturi" not in html  # element ascuns pentru Depozit
