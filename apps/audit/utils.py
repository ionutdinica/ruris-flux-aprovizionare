def mask_completely(value):
    """Maschează integral un câmp sensibil în jurnalul de audit (ex. parola).

    În jurnal rămâne vizibil faptul că parola s-a schimbat, nu și valoarea ei
    (nici măcar valoarea criptată).
    """
    return "********"
