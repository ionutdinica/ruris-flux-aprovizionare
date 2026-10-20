"""Autentificare: cine poate intra, cine nu, și ce se întâmplă la ieșire."""

import pytest
from django.urls import reverse

from apps.accounts.models import User

from .factories import TEST_PASSWORD

pytestmark = pytest.mark.django_db  # toate testele din fișier folosesc baza de test


def test_pages_require_login(client):
    """Un vizitator neautentificat e trimis la login, cu pagina cerută păstrată în `next`."""
    response = client.get(reverse("dashboard:home"))

    assert response.status_code == 302
    assert response.url == f"{reverse('accounts:login')}?next=/"


def test_login_page_is_public(client):
    response = client.get(reverse("accounts:login"))

    assert response.status_code == 200


def test_login_with_valid_credentials(client, procurement_user):
    response = client.post(
        reverse("accounts:login"),
        {"username": procurement_user.username, "password": TEST_PASSWORD},
    )

    assert response.status_code == 302
    assert response.url == reverse("dashboard:home")


def test_login_with_wrong_password_shows_error(client, procurement_user):
    response = client.post(
        reverse("accounts:login"),
        {"username": procurement_user.username, "password": "gresita"},
    )

    assert response.status_code == 200  # rămâne pe pagina de login
    assert response.context["form"].errors
    assert "_auth_user_id" not in client.session  # nu e autentificat


def test_inactive_user_cannot_log_in(client, procurement_user):
    """Utilizatorii nu se șterg, se dezactivează (vezi docs/02-model-date.md)."""
    procurement_user.is_active = False
    procurement_user.save()

    client.post(
        reverse("accounts:login"),
        {"username": procurement_user.username, "password": TEST_PASSWORD},
    )

    assert "_auth_user_id" not in client.session


def test_logout_requires_post(client, procurement_user):
    """Ieșirea nu se poate declanșa printr-un simplu link (GET)."""
    client.force_login(procurement_user)

    assert client.get(reverse("accounts:logout")).status_code == 405
    response = client.post(reverse("accounts:logout"))

    assert response.url == reverse("accounts:login")
    assert "_auth_user_id" not in client.session


def test_has_role():
    user = User(role=User.Role.WAREHOUSE)

    assert user.has_role(User.Role.WAREHOUSE)
    assert user.has_role(User.Role.PROCUREMENT, User.Role.WAREHOUSE)
    assert not user.has_role(User.Role.ACCOUNTING)
