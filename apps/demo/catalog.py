"""Datele de bază ale demo-ului: echipa (câte un utilizator pe rol) și catalogul.

Firmele sunt inventate, dar plauzibile pentru un producător de utilaje din Craiova.
CUI-urile românești au cifra de control calculată corect, deci trec aceeași validare
ca un CUI real (apps/core/validators.py). Nu corespund unor firme existente.
"""

from decimal import Decimal

from apps.accounts.models import User
from apps.catalog.models import Product, Supplier
from apps.core.validators import cui_control_digit

D = Decimal
Role = User.Role

# (utilizator, prenume, nume, rol). Doi oameni în Achiziții: fiecare își vede comenzile lui.
TEAM = [
    ("andrei.ionescu", "Andrei", "Ionescu", Role.ADMIN),
    ("maria.pop", "Maria", "Pop", Role.PROCUREMENT),
    ("radu.vasile", "Radu", "Vasile", Role.PROCUREMENT),
    ("ion.marin", "Ion", "Marin", Role.WAREHOUSE),
    ("elena.dobre", "Elena", "Dobre", Role.ACCOUNTING),
]
EMAIL_DOMAIN = "demo.ruris.local"


# cheie internă → (denumire, țară, primele cifre ale CUI / cod TVA, monedă, punctualitate)
# Punctualitatea (probabilitatea unei livrări integrale la termen) dă formă graficului
# „Livrări la timp, pe furnizor”: unii furnizori sunt de încredere, alții nu.
SUPPLIERS = {
    "motoare": ("Motoare Industriale SA", "RO", "1438257", "RON", 0.55),
    "rulmenti": ("Rulmenți Oltenia SRL", "RO", "2847361", "RON", 0.95),
    "otel": ("Oțelăria Dunărea SRL", "RO", "3512748", "RON", 0.80),
    "plastic": ("Plastic Injecție Dolj SRL", "RO", "4123985", "RON", 0.85),
    "vopsele": ("Vopsele Industriale Craiova SRL", "RO", "3916472", "RON", 0.90),
    "electrice": ("Componente Electrice Banat SRL", "RO", "2264839", "RON", 0.70),
    "hidraulic": ("Hydraulik Teile GmbH", "DE", "DE814563201", "EUR", 0.90),
    "transmisii": ("Trasmissioni Italia S.r.l.", "IT", "IT03856120987", "EUR", 0.75),
}

# cod → (denumire, UM, cota TVA, furnizor, preț unitar în moneda furnizorului)
PRODUCTS = {
    "MOT-65": ("Motor benzină 6,5 CP", "buc", "21", "motoare", "1450"),
    "MOT-90": ("Motor diesel 9 CP", "buc", "21", "motoare", "3890"),
    "FIL-A20": ("Filtru aer motor", "buc", "21", "motoare", "42.5"),
    "RUL-6204": ("Rulment 6204-2RS", "buc", "21", "rulmenti", "18.9"),
    "RUL-6305": ("Rulment 6305-ZZ", "buc", "21", "rulmenti", "31.4"),
    "CUR-A42": ("Curea transmisie A42", "buc", "21", "rulmenti", "18.5"),
    "TAB-2": ("Tablă oțel laminată 2 mm", "kg", "21", "otel", "6.2"),
    "TEV-30": ("Țeavă oțel rotundă Ø30", "m", "21", "otel", "24.8"),
    "PLA-C1": ("Carcasă plastic motocultor", "buc", "21", "plastic", "64"),
    "PLA-M2": ("Mâner ergonomic", "buc", "21", "plastic", "17.3"),
    "VOP-R": ("Vopsea email roșie RAL 3020", "l", "21", "vopsele", "38"),
    "VOP-G": ("Grund anticoroziv", "l", "21", "vopsele", "29.5"),
    "CAB-15": ("Cablu flexibil 3×1,5 mm²", "m", "21", "electrice", "5.6"),
    "COM-P1": ("Comutator pornire", "buc", "21", "electrice", "23"),
    "HID-P12": ("Pompă hidraulică P12", "buc", "21", "hidraulic", "185"),
    "HID-F10": ("Furtun hidraulic DN10", "m", "21", "hidraulic", "7.9"),
    "RED-T3": ("Reductor unghiular T3", "buc", "21", "transmisii", "240"),
    "AMB-K2": ("Ambreiaj centrifugal K2", "buc", "21", "transmisii", "96"),
}


def romanian_cui(first_digits):
    """CUI valid: primele cifre + cifra de control (algoritmul ANAF)."""
    return f"{first_digits}{cui_control_digit(first_digits)}"


def create_team(password):
    """Câte un utilizator pe rol, cu aceeași parolă demo. Adminul are acces și la /admin."""
    users = {}
    for username, first, last, role in TEAM:
        user = User(
            username=username,
            first_name=first,
            last_name=last,
            email=f"{username}@{EMAIL_DOMAIN}",
            role=role,
            is_staff=role == Role.ADMIN,
            is_superuser=role == Role.ADMIN,
        )
        user.set_password(password)
        user.full_clean()
        user.save()
        users[username] = user
    return users


def create_catalog():
    """Furnizorii și produsele. Întoarce (furnizori, produse) ca dicționare după cheie."""
    suppliers = {}
    for key, (name, country, tax, currency, _) in SUPPLIERS.items():
        supplier = Supplier(
            name=name,
            country=country,
            tax_id=romanian_cui(tax) if country == "RO" else tax,
            email=f"comenzi@{key}.example",
            default_currency=currency,
        )
        supplier.full_clean()  # aceleași validări ca formularul (inclusiv CUI-ul)
        supplier.save()
        suppliers[key] = supplier

    products = {}
    for code, (name, unit, vat, _, _) in PRODUCTS.items():
        product = Product(code=code, name=name, unit=unit, vat_rate=D(vat))
        product.full_clean()
        product.save()
        products[code] = product
    return suppliers, products


def price_of(code):
    return D(PRODUCTS[code][4])


def supplier_key_of(code):
    return PRODUCTS[code][3]


def punctuality(supplier_key):
    return SUPPLIERS[supplier_key][4]
