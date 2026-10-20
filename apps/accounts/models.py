from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """Utilizatorul aplicației.

    Extinde utilizatorul standard Django (username, parolă, nume, email...)
    cu rolul echipei din care face parte. Fiecare utilizator are exact un rol
    (vezi docs/01-ipoteze.md, I-02).
    """

    class Role(models.TextChoices):
        PROCUREMENT = "PROCUREMENT", "Achiziții"
        WAREHOUSE = "WAREHOUSE", "Depozit"
        ACCOUNTING = "ACCOUNTING", "Contabilitate"
        ADMIN = "ADMIN", "Administrator"

    role = models.CharField("rol", max_length=20, choices=Role.choices)
    # Emailul e obligatoriu: pe el se trimit notificările.
    email = models.EmailField("email", unique=True)

    # Câmpurile cerute la `createsuperuser`, pe lângă username și parolă.
    REQUIRED_FIELDS = ["email", "role"]

    class Meta:
        verbose_name = "utilizator"
        verbose_name_plural = "utilizatori"

    def __str__(self):
        return self.get_full_name() or self.username

    def has_role(self, *roles):
        """Are utilizatorul unul dintre rolurile date? Ex.: user.has_role(Role.PROCUREMENT)."""
        return self.role in roles

    def can(self, permission):
        """Poate face acțiunea dată? Ex.: user.can("orders.edit").
        Regulile sunt în apps/accounts/permissions.py."""
        from .permissions import has_permission  # import aici: evită importul circular

        return has_permission(self, permission)
