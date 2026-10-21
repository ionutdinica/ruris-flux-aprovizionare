"""Bugetele anuale pe furnizor (plafonul unui contract-cadru).

Un buget = un furnizor + un an + o sumă fără TVA, în moneda furnizorului. Cât s-a
consumat din el nu se stochează: se calculează din comenzi (services.py), deci nu se
poate desincroniza de documente.
"""

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.urls import reverse

from apps.catalog.models import Supplier
from apps.core.models import Currency, TimeStampedModel


class SupplierBudget(TimeStampedModel):
    supplier = models.ForeignKey(
        Supplier, verbose_name="furnizor", on_delete=models.PROTECT, related_name="budgets"
    )
    year = models.PositiveSmallIntegerField(
        "anul", validators=[MinValueValidator(2000), MaxValueValidator(2100)]
    )
    amount = models.DecimalField(
        "buget (fără TVA)",
        max_digits=14,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0.01"), "Bugetul trebuie să fie pozitiv.")],
    )
    # Moneda furnizorului la crearea bugetului (ca într-un contract); nu se mai schimbă.
    currency = models.CharField("monedă", max_length=3, choices=Currency.choices, editable=False)
    notes = models.TextField(
        "observații", blank=True, help_text="Opțional: contractul, aprobarea, condițiile."
    )

    class Meta:
        verbose_name = "buget"
        verbose_name_plural = "bugete"
        ordering = ["-year", "supplier__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["supplier", "year"],
                name="unique_budget_per_supplier_and_year",
                violation_error_message="Furnizorul are deja un buget pentru acest an.",
            )
        ]

    def __str__(self):
        return f"Buget {self.year} · {self.supplier}"

    def save(self, *args, **kwargs):
        if not self.currency:
            self.currency = self.supplier.default_currency
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("budgets:budget_list") + f"?an={self.year}"
