import pytest

from apps.core.text import fold


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Oțelăria DUNĂREA", "otelaria dunarea"),
        ("ÎNCĂLȚĂMINTE", "incaltaminte"),
        ("Şurub ţeavă", "surub teava"),  # ș/ț cu sedilă (tastaturi vechi)
        ("Șurub țeavă", "surub teava"),  # ș/ț cu virgulă (forma corectă)
        ("Hydraulik Teile GmbH", "hydraulik teile gmbh"),
    ],
)
def test_fold(text, expected):
    assert fold(text) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("12.000", "12"), ("2.500", "2.5"), (10, "10"), ("10.000", "10"), ("0.001", "0.001")],
)
def test_format_quantity(value, expected):
    from apps.core.text import format_quantity

    assert format_quantity(value) == expected


def test_format_quantity_with_sign():
    from apps.core.text import format_quantity

    assert format_quantity("5", sign=True) == "+5"
    assert format_quantity("-3.50", sign=True) == "-3.5"
