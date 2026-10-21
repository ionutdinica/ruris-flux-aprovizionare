"""Semnalele modulului de comenzi.

`order_progress_changed` se trimite după orice eveniment care poate schimba ce s-a
recepționat sau ce s-a comandat pe o comandă: recepție confirmată, marfă acceptată din
carantină, retur, linie nouă sau cantitate mărită, anulare. Facturile ascultă și se
reverifică (apps/invoicing/receivers.py), fără ca modulul de comenzi să depindă de ele.
"""

from django.dispatch import Signal

order_progress_changed = Signal()  # argument: order
