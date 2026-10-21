import unicodedata
from decimal import ROUND_HALF_UP, Decimal


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


def format_money(value):
    """Sumă în format românesc, cu 2 zecimale: 1250.5 → „1.250,50”, -60 → „-60,00”.

    Pentru textele salvate (ex. motivele de blocare ale unei facturi), care trebuie să
    arate la fel oriunde sunt afișate: pagină, email, export.
    """
    # Rotunjire comercială întâi: formatarea Python ar rotunji „bancherește” (0,005 → 0,00).
    rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    english = f"{rounded:,.2f}"  # 1,250.50
    return english.replace(",", " ").replace(".", ",").replace(" ", ".")


def plural(number, singular, plural_form):
    """Numărul cu forma potrivită: „1 factură”, „3 facturi”, „0 facturi”."""
    return f"{number} {singular if number == 1 else plural_form}"
