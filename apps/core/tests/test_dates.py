import datetime

import pytest

from apps.core.dates import business_days_between, is_business_day

D = datetime.date


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (D(2026, 10, 16), D(2026, 10, 19), 1),  # vineri → luni
        (D(2026, 10, 19), D(2026, 10, 19), 0),  # aceeași zi
        (D(2026, 10, 19), D(2026, 10, 23), 4),  # luni → vineri
        (D(2026, 10, 17), D(2026, 10, 18), 0),  # sâmbătă → duminică
        (D(2026, 10, 14), D(2026, 10, 21), 5),  # miercuri → miercuri
        (D(2026, 10, 21), D(2026, 10, 14), 0),  # invers: 0, nu negativ
    ],
)
def test_business_days_between(start, end, expected):
    assert business_days_between(start, end) == expected


def test_weekend_is_not_a_business_day():
    assert is_business_day(D(2026, 10, 16)) and not is_business_day(D(2026, 10, 17))
