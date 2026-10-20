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


def test_403_page_is_friendly(rf, warehouse_user):
    """Pagina 403 folosește layout-ul aplicației și explică de ce nu ai acces."""
    from django.core.exceptions import PermissionDenied
    from django.views.defaults import permission_denied

    request = rf.get("/facturi/")
    request.user = warehouse_user

    response = permission_denied(request, PermissionDenied())
    html = response.content.decode()

    assert response.status_code == 403
    assert "Nu ai acces" in html
    assert "Depozit" in html
