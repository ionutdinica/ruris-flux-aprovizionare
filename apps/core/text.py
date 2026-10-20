import unicodedata
from decimal import Decimal


def fold(text):
    """Text pentru căutare: fără diacritice, cu litere mici.

    „Oțelăria DUNĂREA” → „otelaria dunarea”. Tratează și ambele variante de
    ș/ț românești (cu virgulă – corectă, și cu sedilă – folosită de tastaturi vechi).
    """
    decomposed = unicodedata.normalize("NFKD", text)  # „ț” → „t” + semnul diacritic
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_marks.casefold()


def format_quantity(value, sign=False):
    """Cantitate fără zerouri inutile: 12.000 → „12”, 2.500 → „2.5”, cu semn: „+5” / „-3”.

    Acceptă și numere întregi sau text. Atenție: Decimal("10").normalize() dă „1E+1”;
    formatul „f” îl scrie corect, „10”.
    """
    number = Decimal(str(value)).normalize()
    return f"{number:+f}" if sign else f"{number:f}"
