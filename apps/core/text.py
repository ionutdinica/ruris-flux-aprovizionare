import unicodedata


def fold(text):
    """Text pentru căutare: fără diacritice, cu litere mici.

    „Oțelăria DUNĂREA” → „otelaria dunarea”. Tratează și ambele variante de
    ș/ț românești (cu virgulă – corectă, și cu sedilă – folosită de tastaturi vechi).
    """
    decomposed = unicodedata.normalize("NFKD", text)  # „ț” → „t” + semnul diacritic
    without_marks = "".join(c for c in decomposed if not unicodedata.combining(c))
    return without_marks.casefold()
