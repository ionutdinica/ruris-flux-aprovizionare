"""Zile lucrătoare: luni–vineri.

Simplificare declarată (docs/01-ipoteze.md, I-32): sărbătorile legale nu sunt
considerate. Efectul e mic și sigur: în cel mai rău caz o factură e semnalată cu o
zi mai devreme, iar rezumatul zilnic pleacă și într-o zi de sărbătoare.
"""

import datetime


def is_business_day(day):
    return day.weekday() < 5  # 0 = luni … 4 = vineri


def business_days_between(start, end):
    """Câte zile lucrătoare au trecut de la `start` până la `end` (fără ziua de start).

    Vineri → luni = 1; luni → luni = 0; luni → vineri aceeași săptămână = 4.
    """
    if end <= start:
        return 0
    days = (start + datetime.timedelta(days=n) for n in range(1, (end - start).days + 1))
    return sum(1 for day in days if is_business_day(day))
