"""Plasa de siguranță pentru permisiuni: verifică AUTOMAT toate paginile aplicației.

Testul parcurge toate rutele (urls.py) și, pentru fiecare pagină din `apps/`:
  1. verifică faptul că declară o permisiune (PermissionMixin) – o pagină nouă
     nu poate rămâne, din greșeală, deschisă tuturor celor autentificați;
  2. verifică faptul că fiecare rol fără acea permisiune primește 403, iar
     fiecare rol cu permisiune nu primește 403.

Paginile adăugate în capitolele următoare intră automat în aceste verificări.
"""

import pytest
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from apps.accounts.models import User
from apps.accounts.permissions import PERMISSIONS, PermissionMixin

from .factories import UserFactory

# Pagini accesibile oricărui utilizator autentificat, intenționat.
OPEN_TO_ALL_AUTHENTICATED = {"apps.dashboard.views.HomeView"}

# Valori de umplutură pentru parametrii din adrese (ex. <int:pk>). Permisiunea se
# verifică înainte de căutarea documentului, deci obiectul nu trebuie să existe.
DUMMY_VALUES = {"int": 1, "str": "x", "slug": "x", "uuid": "00000000-0000-0000-0000-000000000000"}


def _app_routes(patterns=None, namespace=""):
    """(nume rută, clasa view-ului, parametri) pentru toate paginile din `apps/`."""
    for entry in patterns if patterns is not None else get_resolver().url_patterns:
        if isinstance(entry, URLResolver):
            ns = f"{namespace}{entry.namespace}:" if entry.namespace else namespace
            yield from _app_routes(entry.url_patterns, ns)
        elif isinstance(entry, URLPattern):
            view_class = getattr(entry.callback, "view_class", None)
            if view_class and view_class.__module__.startswith("apps.") and entry.name:
                kwargs = {
                    name: DUMMY_VALUES[type(conv).__name__.removesuffix("Converter").lower()]
                    for name, conv in entry.pattern.converters.items()
                }
                yield f"{namespace}{entry.name}", view_class, kwargs


ROUTES = sorted(_app_routes(), key=lambda r: r[0])
PROTECTED = [r for r in ROUTES if issubclass(r[1], PermissionMixin)]


def _qualified_name(view_class):
    return f"{view_class.__module__}.{view_class.__qualname__}"


def test_routes_are_discovered():
    """Dacă descoperirea rutelor s-ar strica, celelalte teste ar trece „în gol”."""
    assert "audit:log" in [name for name, _, _ in ROUTES]


@pytest.mark.parametrize(("name", "view_class", "kwargs"), ROUTES, ids=[r[0] for r in ROUTES])
def test_every_page_declares_a_permission(name, view_class, kwargs):
    if _qualified_name(view_class) in OPEN_TO_ALL_AUTHENTICATED:
        return
    assert issubclass(view_class, PermissionMixin), (
        f"Pagina „{name}” nu declară nicio permisiune. Adaugă PermissionMixin și "
        f"`permission = ...`, sau trec-o explicit în OPEN_TO_ALL_AUTHENTICATED."
    )
    assert view_class.permission in PERMISSIONS


@pytest.mark.django_db
@pytest.mark.parametrize(("name", "view_class", "kwargs"), PROTECTED, ids=[r[0] for r in PROTECTED])
@pytest.mark.parametrize("role", list(User.Role))
def test_page_access_matches_permission_matrix(client, name, view_class, kwargs, role):
    client.force_login(UserFactory(role=role))

    response = client.get(reverse(name, kwargs=kwargs))

    if role in PERMISSIONS[view_class.permission]:
        assert response.status_code != 403
    else:
        assert response.status_code == 403
