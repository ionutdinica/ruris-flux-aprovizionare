from django import forms


class DateInput(forms.DateInput):
    """Câmp de dată cu calendarul browserului.

    Browserul acceptă în <input type="date"> doar formatul ISO (2026-10-21); cu limba
    română, Django ar scrie implicit „21.10.2026”, pe care browserul îl ignoră în tăcere,
    iar câmpul apare gol. De aceea formatul e fixat aici, o singură dată.
    """

    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs=attrs, format="%Y-%m-%d")


class BootstrapFormMixin:
    """Aplică automat stilul Bootstrap pe câmpurile oricărui formular.

        class SupplierForm(BootstrapFormMixin, forms.ModelForm): ...

    Câmpurile cu erori primesc și clasa `is-invalid` (chenar roșu + mesajul sub câmp).
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, forms.Select | forms.SelectMultiple):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs["class"] = f"{widget.attrs.get('class', '')} {css}".strip()

    def full_clean(self):
        super().full_clean()
        for name in self.errors:
            if name in self.fields:
                widget = self.fields[name].widget
                widget.attrs["class"] = f"{widget.attrs.get('class', '')} is-invalid".strip()
