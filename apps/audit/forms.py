from django import forms

from apps.accounts.models import User

from .models import BusinessEvent
from .timeline import CHANGE


def _kind_choices():
    return [
        ("", "Toate"),
        (CHANGE, "Modificări de date"),
        ("Evenimente", list(BusinessEvent.Type.choices)),  # grup în lista derulantă
    ]


class ActivityFilterForm(forms.Form):
    """Filtrele paginii „Jurnal de activitate”. Toate sunt opționale."""

    actor = forms.ModelChoiceField(
        label="Utilizator",
        queryset=User.objects.order_by("username"),
        required=False,
        empty_label="Toți",
    )
    kind = forms.ChoiceField(label="Tip", choices=_kind_choices, required=False)
    date_from = forms.DateField(
        label="De la", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    date_to = forms.DateField(
        label="Până la", required=False, widget=forms.DateInput(attrs={"type": "date"})
    )
    # Istoricul unui singur document (din link-ul „istoric complet”)
    ct = forms.IntegerField(required=False, widget=forms.HiddenInput)
    obj = forms.CharField(required=False, max_length=64, widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():  # aspectul Bootstrap pentru toate câmpurile
            is_select = isinstance(field.widget, forms.Select)
            field.widget.attrs["class"] = "form-select" if is_select else "form-control"

    def clean(self):
        data = super().clean()
        start, end = data.get("date_from"), data.get("date_to")
        if start and end and start > end:
            self.add_error("date_to", "Data de sfârșit este înaintea datei de început.")
        return data
