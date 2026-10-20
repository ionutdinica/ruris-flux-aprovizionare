"""Obiecte comune pentru toate testele („fixtures”).

Un test care are un parametru cu numele unei funcții de aici o primește
automat. Ex.: `def test_ceva(warehouse_user): ...`
"""

import pytest

from apps.accounts.models import User
from apps.accounts.tests.factories import UserFactory


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
