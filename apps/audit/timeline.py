"""Cronologia unificată a jurnalului de audit.

Avem două surse: modificările automate de câmpuri (django-auditlog, `LogEntry`)
și evenimentele de business (`BusinessEvent`). Pentru utilizator ele formează
o singură poveste – „ce s-a întâmplat, în ordine” – așa că le afișăm împreună.

Cum le combinăm eficient, fără să încărcăm tot jurnalul în memorie:
  1. din fiecare tabel luăm doar (sursă, id, dată), filtrate;
  2. le unim într-o singură interogare SQL (UNION), ordonată după dată,
     pe care se face paginarea direct în baza de date;
  3. doar pentru rândurile paginii curente (ex. 25) încărcăm detaliile complete.
"""

from dataclasses import dataclass, field
from datetime import datetime

from auditlog.models import LogEntry
from django.contrib.contenttypes.models import ContentType
from django.db.models import CharField, Q, Value

from .models import BusinessEvent

CHANGE = "change"  # sursa: modificare automată de câmpuri
EVENT = "event"  # sursa: eveniment de business

# Cum se afișează fiecare tip de intrare: (etichetă, culoare Bootstrap, iconiță)
ACTION_STYLE = {
    LogEntry.Action.CREATE: ("Creare", "success", "plus-circle"),
    LogEntry.Action.UPDATE: ("Modificare", "primary", "pencil"),
    LogEntry.Action.DELETE: ("Ștergere", "danger", "trash"),
    LogEntry.Action.ACCESS: ("Accesare", "secondary", "eye"),
}
EVENT_STYLE = {
    BusinessEvent.Type.LOGIN: ("secondary", "box-arrow-in-right"),
    BusinessEvent.Type.LOGOUT: ("secondary", "box-arrow-right"),
    BusinessEvent.Type.LOGIN_FAILED: ("danger", "shield-exclamation"),
    BusinessEvent.Type.ORDER_SENT: ("primary", "send"),
    BusinessEvent.Type.ORDER_CANCELLED: ("danger", "x-circle"),
    BusinessEvent.Type.ORDER_CLOSED: ("warning", "slash-circle"),
    BusinessEvent.Type.ORDERS_IMPORTED: ("info", "file-earmark-arrow-up"),
    BusinessEvent.Type.ORDERS_EXPORTED: ("secondary", "file-earmark-arrow-down"),
    BusinessEvent.Type.RECEIPT_CONFIRMED: ("success", "box-seam"),
    BusinessEvent.Type.DISCREPANCY_ATTACHED: ("success", "link-45deg"),
    BusinessEvent.Type.DISCREPANCY_RETURNED: ("warning", "arrow-return-left"),
    BusinessEvent.Type.INVOICE_VALIDATED: ("info", "check2-circle"),
    BusinessEvent.Type.INVOICE_RECHECKED: ("info", "arrow-repeat"),
    BusinessEvent.Type.INVOICE_REOPENED: ("secondary", "pencil-square"),
    BusinessEvent.Type.INVOICE_APPROVED: ("success", "check2-all"),
    BusinessEvent.Type.INVOICE_FORCE_APPROVED: ("warning", "exclamation-triangle"),
    BusinessEvent.Type.INVOICE_PAID: ("dark", "cash-coin"),
    BusinessEvent.Type.INVOICE_REJECTED: ("danger", "x-circle"),
}
DEFAULT_EVENT_STYLE = ("info", "flag")


@dataclass
class TimelineEntry:
    """O intrare din cronologie, în același format indiferent de sursă."""

    source: str
    timestamp: datetime
    actor: object  # User sau None (acțiune a sistemului / vizitator anonim)
    label: str
    color: str
    icon: str
    title: str  # documentul vizat, ex. „Utilizator «Ion Popescu»”
    message: str = ""
    changes: list = field(default_factory=list)  # [(câmp, valoare veche, valoare nouă)]
    details: dict = field(default_factory=dict)
    remote_addr: str | None = None
    content_type_id: int | None = None
    object_id: str = ""


# --- Conversia fiecărei surse în TimelineEntry ------------------------------------


def _document_title(content_type, object_repr):
    if content_type is None:
        return ""
    model = content_type.model_class()
    name = model._meta.verbose_name if model else content_type.model
    return f"{str(name).capitalize()} «{object_repr}»"


# Valori pe care biblioteca le dă „ca în Python”, traduse pentru afișare.
READABLE_VALUES = {"True": "Da", "False": "Nu", "None": ""}


def _readable(value):
    return READABLE_VALUES.get(value, value)


def from_log_entry(entry):
    label, color, icon = ACTION_STYLE.get(entry.action, ("Modificare", "primary", "pencil"))
    changes = []
    if entry.action == LogEntry.Action.UPDATE:
        # changes_display_dict: nume de câmpuri și valori „pe înțelesul omului”
        # (ex. rol: „Depozit” în loc de „WAREHOUSE”).
        for name, (old, new) in entry.changes_display_dict.items():
            changes.append((name, _readable(old), _readable(new)))
    return TimelineEntry(
        source=CHANGE,
        timestamp=entry.timestamp,
        actor=entry.actor,
        label=label,
        color=color,
        icon=icon,
        title=_document_title(entry.content_type, entry.object_repr),
        changes=changes,
        remote_addr=entry.remote_addr,
        content_type_id=entry.content_type_id,
        object_id=entry.object_pk,
    )


def from_event(event):
    color, icon = EVENT_STYLE.get(event.event_type, DEFAULT_EVENT_STYLE)
    return TimelineEntry(
        source=EVENT,
        timestamp=event.timestamp,
        actor=event.actor,
        label=event.get_event_type_display(),
        color=color,
        icon=icon,
        title=_document_title(event.content_type, event.object_repr),
        message=event.message,
        details=event.data,
        remote_addr=event.remote_addr,
        content_type_id=event.content_type_id,
        object_id=event.object_id,
    )


# --- Filtrare, unire, încărcarea detaliilor ------------------------------------------


@dataclass
class TimelineFilters:
    actor_id: int | None = None
    kind: str = ""  # "" = tot; "change" = doar modificări; altfel un tip de eveniment
    date_from: object = None
    date_to: object = None
    content_type_id: int | None = None  # istoricul unui singur document
    object_id: str = ""


# Câmpul care identifică documentul vizat diferă între cele două tabele.
OBJECT_FIELD = {CHANGE: "object_pk", EVENT: "object_id"}


def _filtered_sources(f):
    """Sursele incluse de filtru, fiecare filtrată: {"change": qs, "event": qs}."""
    sources = {CHANGE: LogEntry.objects.all(), EVENT: BusinessEvent.objects.all()}

    if f.kind == CHANGE:
        del sources[EVENT]
    elif f.kind:  # un anumit tip de eveniment de business
        del sources[CHANGE]
        sources[EVENT] = sources[EVENT].filter(event_type=f.kind)

    common = {}
    if f.actor_id:
        common["actor_id"] = f.actor_id
    if f.date_from:
        common["timestamp__date__gte"] = f.date_from
    if f.date_to:
        common["timestamp__date__lte"] = f.date_to

    for source, qs in sources.items():
        qs = qs.filter(**common)
        if f.content_type_id:
            qs = qs.filter(_document_condition(source, f.content_type_id, f.object_id))
        sources[source] = qs
    return sources


def _document_condition(source, content_type_id, object_id):
    """Intrările despre un document: ale lui și, pentru modificări, ale părților lui.

    Ex.: istoricul unei comenzi include și modificările liniilor ei. Liniile își
    declară „părintele” prin get_additional_data() (vezi PurchaseOrderLine).
    """
    condition = Q(content_type_id=content_type_id, **{OBJECT_FIELD[source]: object_id})
    if source == CHANGE:
        content_type = ContentType.objects.get_for_id(content_type_id)
        parent_key = f"{content_type.app_label}.{content_type.model}:{object_id}"
        condition |= Q(additional_data__parent=parent_key)
    return condition


def timeline_rows(filters):
    """Interogarea unificată (UNION), ordonată descrescător după dată.

    Conține doar (id, dată, sursă) – suficient pentru ordonare și paginare.
    """
    parts = [
        # .order_by() fără argumente anulează ordonarea implicită a modelului:
        # SQL nu permite ORDER BY în părțile unui UNION, doar pe rezultatul final.
        qs.order_by()
        .annotate(source=Value(source, output_field=CharField()))
        .values("id", "timestamp", "source")
        for source, qs in _filtered_sources(filters).items()
    ]
    combined = parts[0] if len(parts) == 1 else parts[0].union(parts[1], all=True)
    return combined.order_by("-timestamp", "-id")


def hydrate(rows):
    """Încarcă detaliile complete doar pentru rândurile date, păstrând ordinea."""
    rows = list(rows)
    change_ids = [r["id"] for r in rows if r["source"] == CHANGE]
    event_ids = [r["id"] for r in rows if r["source"] == EVENT]
    changes = LogEntry.objects.select_related("actor", "content_type").in_bulk(change_ids)
    events = BusinessEvent.objects.select_related("actor", "content_type").in_bulk(event_ids)
    return [
        from_log_entry(changes[r["id"]]) if r["source"] == CHANGE else from_event(events[r["id"]])
        for r in rows
    ]


def history_for(obj, limit=None):
    """Istoricul complet al unui document (comandă, factură...), cel mai recent primul."""
    filters = TimelineFilters(
        content_type_id=ContentType.objects.get_for_model(obj).pk, object_id=str(obj.pk)
    )
    rows = timeline_rows(filters)
    return hydrate(rows[:limit] if limit else rows)


def redact(entries, user, model):
    """Ascunde din istoric ce utilizatorul nu are voie să vadă.

    Un model își declară informațiile sensibile și permisiunea care le dezvăluie:

        AUDIT_RESTRICTED = {
            "invoices.view_payment": {"fields": ("paid_at",), "details": ("referința",)},
        }

    `fields` = câmpuri ale modelului (din modificările automate), `details` = chei din
    detaliile evenimentelor de business. Fără această filtrare, istoricul ar dezvălui
    exact ce pagina ascunde (ex. detaliile plății, docs/04-permisiuni.md).
    """
    hidden_fields, hidden_details = set(), set()
    for permission, restricted in getattr(model, "AUDIT_RESTRICTED", {}).items():
        if not user.can(permission):
            hidden_fields |= {
                str(model._meta.get_field(name).verbose_name).lower()
                for name in restricted.get("fields", ())
            }
            hidden_details |= set(restricted.get("details", ()))
    if not (hidden_fields or hidden_details):
        return entries

    visible = []
    for entry in entries:
        if entry.changes:
            entry.changes = [c for c in entry.changes if str(c[0]).lower() not in hidden_fields]
            if not entry.changes:
                continue  # o modificare formată doar din câmpuri ascunse nu se mai arată
        entry.details = {k: v for k, v in (entry.details or {}).items() if k not in hidden_details}
        visible.append(entry)
    return visible
