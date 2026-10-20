"""Fabrici de date de test (factory_boy).

În loc să scriem în fiecare test toate câmpurile unui utilizator, cerem
doar ce contează pentru test: `UserFactory(role=User.Role.WAREHOUSE)`.
Restul (username, email unic...) se generează automat.
"""

import factory

from apps.accounts.models import User

TEST_PASSWORD = "parola-de-test-123"


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    username = factory.Sequence(lambda n: f"utilizator{n}")
    email = factory.LazyAttribute(lambda u: f"{u.username}@test.local")
    first_name = factory.Faker("first_name", locale="ro_RO")
    last_name = factory.Faker("last_name", locale="ro_RO")
    role = User.Role.PROCUREMENT
    password = factory.django.Password(TEST_PASSWORD)
