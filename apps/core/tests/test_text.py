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
