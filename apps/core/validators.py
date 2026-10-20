"""Validarea codului fiscal (CUI / CIF) al firmelor românești.

CUI-ul are între 2 și 10 cifre, iar ultima este o cifră de control calculată
din celelalte cu cheia „753217532”. Verificarea prinde greșelile de tastare
(o cifră greșită sau două cifre inversate) înainte ca furnizorul să fie salvat.

Algoritmul:
  1. se elimină prefixul „RO” (îl au plătitorii de TVA) și spațiile;
  2. cifrele fără cea de control se completează cu zerouri la stânga până la 9;
  3. se înmulțește fiecare cifră cu cifra corespunzătoare din cheie și se adună;
  4. cifra de control = (suma × 10) mod 11; dacă rezultatul e 10, devine 0.
"""

from django.core.exceptions import ValidationError

CUI_KEY = "753217532"


def normalize_cui(value):
    """„ro 14 399 840” → „14399840”."""
    value = value.strip().upper().replace(" ", "")
    return value.removeprefix("RO")


def cui_control_digit(digits_without_control):
    padded = digits_without_control.rjust(9, "0")
    total = sum(int(d) * int(k) for d, k in zip(padded, CUI_KEY, strict=True))
    control = total * 10 % 11
    return 0 if control == 10 else control


def validate_cui(value):
    cui = normalize_cui(value)
    if not cui.isdigit() or not 2 <= len(cui) <= 10:
        raise ValidationError(
            "CUI-ul trebuie să aibă între 2 și 10 cifre (opțional cu prefixul RO)."
        )
    if cui_control_digit(cui[:-1]) != int(cui[-1]):
        raise ValidationError(
            "CUI invalid: cifra de control nu corespunde. Verifică dacă a fost tastat corect."
        )
