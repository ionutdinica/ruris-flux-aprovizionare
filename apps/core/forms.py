from django import forms


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
