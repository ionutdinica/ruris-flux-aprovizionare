"""Semnalele aplicației de curs valutar.

`rates_synced` se trimite după fiecare actualizare reușită de la BNR (chiar și fără
cursuri noi: o zi fără publicare devine astfel „cunoscută”). Facturile aflate în
„Curs în așteptare” ascultă acest semnal și se reiau (capitolul 7). Astfel modulul
de curs nu depinde de modulul de facturi.
"""

from django.dispatch import Signal

rates_synced = Signal()  # argument: syncs (lista de RateSync)
