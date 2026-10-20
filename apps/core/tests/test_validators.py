import pytest
from django.core.exceptions import ValidationError

from apps.core.validators import cui_control_digit, normalize_cui, validate_cui


@pytest.mark.parametrize(
    "value",
    [
        "14399840",  # CUI real (Dante International / eMAG)
        "RO14399840",  # cu prefixul plătitorilor de TVA
        "ro 14 399 840",  # cu spații și litere mici
        "19",  # CUI scurt (2 cifre): 000000001 × 753217532 = 2; 2×10 mod 11 = 9
    ],
)
def test_valid_cui(value):
    validate_cui(value)  # nu ridică eroare


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("14399841", "cifra de control greșită"),
        ("14398940", "două cifre inversate"),
        ("RO", "fără cifre"),
        ("1", "prea scurt"),
        ("12345678901", "prea lung"),
        ("1439A840", "conține litere"),
    ],
)
def test_invalid_cui(value, reason):
    with pytest.raises(ValidationError):
        validate_cui(value)


def test_control_digit_algorithm():
    # 001439984 × 753217532 = 0+0+3+8+3+63+45+24+8 = 154; 154×10 mod 11 = 0
    assert cui_control_digit("1439984") == 0


def test_normalize_cui():
    assert normalize_cui(" ro14399840 ") == "14399840"
