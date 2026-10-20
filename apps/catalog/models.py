"""Nomenclatoarele: furnizorii și produsele.

Nu se șterg niciodată (sunt referite de comenzi, recepții și facturi): se
dezactivează. Un element inactiv nu mai poate fi ales pe documente noi, dar
rămâne vizibil pe cele vechi.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.urls import reverse

from apps.core.models import Currency, SearchableModel, TimeStampedModel
from apps.core.validators import normalize_cui, validate_cui


class ActiveQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True)


class Supplier(SearchableModel, TimeStampedModel):
    SEARCH_FIELDS = ("name", "tax_id", "email")

    name = models.CharField("denumire", max_length=200)
    country = models.CharField(
        "țara",
        max_length=2,
        default="RO",
        # Literele mici sunt acceptate aici: clean() le transformă în majuscule.
        # (Django validează câmpurile individual ÎNAINTE de a rula clean().)
        validators=[RegexValidator(r"^[A-Za-z]{2}$", "Codul țării are 2 litere (ex. RO, DE).")],
        help_text="Codul ISO din 2 litere (RO, DE, IT...).",
    )
    tax_id = models.CharField(
        "cod fiscal",
        max_length=20,
        unique=True,
        help_text="Pentru firme din România: CUI-ul, cu sau fără RO. Pentru străine: codul de TVA.",
    )
    email = models.EmailField("email", blank=True)
    phone = models.CharField("telefon", max_length=30, blank=True)
    address = models.TextField("adresă", blank=True)
    default_currency = models.CharField(
        "moneda implicită",
        max_length=3,
        choices=Currency.choices,
        default=Currency.RON,
        help_text="Propusă automat la comenzile noi către acest furnizor.",
    )
    is_active = models.BooleanField("activ", default=True)

    objects = ActiveQuerySet.as_manager()

    class Meta:
        verbose_name = "furnizor"
        verbose_name_plural = "furnizori"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("catalog:supplier_detail", args=[self.pk])

    def clean(self):
        """Validările care depind de mai multe câmpuri (rulează la salvarea formularelor)."""
        self.country = (self.country or "").strip().upper()
        if self.tax_id:
            if self.country == "RO":
                # CUI-ul românesc se validează (cifra de control) și se păstrează
                # fără prefixul RO, ca „RO14399840” și „14399840” să fie același furnizor.
                try:
                    validate_cui(self.tax_id)
                except ValidationError as error:
                    raise ValidationError({"tax_id": error.messages}) from error
                self.tax_id = normalize_cui(self.tax_id)
            else:
                self.tax_id = self.tax_id.strip().upper().replace(" ", "")


class Product(SearchableModel, TimeStampedModel):
    SEARCH_FIELDS = ("code", "name")

    class Unit(models.TextChoices):
        PIECE = "buc", "bucată (buc)"
        KG = "kg", "kilogram (kg)"
        TONNE = "t", "tonă (t)"
        METER = "m", "metru (m)"
        SQUARE_METER = "m2", "metru pătrat (m²)"
        LITER = "l", "litru (l)"
        SET = "set", "set"
        PACK = "pachet", "pachet"

    class VatRate(models.TextChoices):
        # Cotele de TVA din România în vigoare din 1 august 2025 (I-20).
        STANDARD = "21.00", "21% (standard)"
        REDUCED = "11.00", "11% (redusă)"
        ZERO = "0.00", "0% (scutit / taxare inversă)"

    code = models.CharField("cod", max_length=50, unique=True)
    name = models.CharField("denumire", max_length=200)
    unit = models.CharField("unitate de măsură", max_length=10, choices=Unit.choices)
    vat_rate = models.DecimalField(
        "cota TVA (%)",
        max_digits=5,
        decimal_places=2,
        choices=[(Decimal(value), label) for value, label in VatRate.choices],
        default=Decimal(VatRate.STANDARD),
    )
    description = models.TextField("descriere", blank=True)
    is_active = models.BooleanField("activ", default=True)

    objects = ActiveQuerySet.as_manager()

    class Meta:
        verbose_name = "produs"
        verbose_name_plural = "produse"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} – {self.name}"

    def get_absolute_url(self):
        return reverse("catalog:product_detail", args=[self.pk])

    def clean(self):
        self.code = self.code.strip().upper()
