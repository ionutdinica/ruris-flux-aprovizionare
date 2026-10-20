import factory

from apps.catalog.models import Product, Supplier
from apps.core.validators import cui_control_digit


def _valid_cui(n):
    """Generează un CUI românesc valid (cu cifra de control corectă)."""
    base = str(1000000 + n)
    return f"{base}{cui_control_digit(base)}"


class SupplierFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Supplier

    name = factory.Sequence(lambda n: f"Furnizor {n} SRL")
    tax_id = factory.Sequence(_valid_cui)
    email = factory.LazyAttribute(lambda s: f"contact{s.tax_id}@furnizor.test")


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    code = factory.Sequence(lambda n: f"P{n:04d}")
    name = factory.Sequence(lambda n: f"Produs {n}")
    unit = Product.Unit.PIECE
