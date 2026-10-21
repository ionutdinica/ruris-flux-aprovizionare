"""Obiecte comune pentru toate testele („fixtures”).

Un test care are un parametru cu numele unei funcții de aici o primește
automat. Ex.: `def test_ceva(warehouse_user): ...`
"""

import pytest

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory


@pytest.fixture(autouse=True)
def _simple_static_storage(settings):
    """În teste, fișierele statice se servesc simplu, fără pasul `collectstatic`
    cerut de stocarea de producție (indiferent de valoarea lui DEBUG)."""
    settings.STORAGES = {
        **settings.STORAGES,
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings):
    """Criptarea parolelor e intenționat lentă (protecție la ghicire). În teste
    nu contează securitatea, ci viteza, așa că folosim un algoritm rapid."""
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Testele nu ies niciodată pe internet: ar fi lente, ar depinde de starea BNR și
    ar trece sau ar pica la întâmplare. Clientul BNR e înlocuit în teste cu fișiere
    locale (apps/currency/tests/data); orice scăpare pică imediat, cu mesaj clar."""

    def refuse(*args, **kwargs):
        raise AssertionError("Testele nu au voie să acceseze rețeaua (BNR).")

    monkeypatch.setattr("apps.currency.bnr.urlopen", refuse)


@pytest.fixture
def procurement_user(db):
    return UserFactory(role=User.Role.PROCUREMENT)


@pytest.fixture
def warehouse_user(db):
    return UserFactory(role=User.Role.WAREHOUSE)


@pytest.fixture
def accounting_user(db):
    return UserFactory(role=User.Role.ACCOUNTING)


@pytest.fixture
def admin_user(db):
    return UserFactory(role=User.Role.ADMIN, is_staff=True, is_superuser=True)
