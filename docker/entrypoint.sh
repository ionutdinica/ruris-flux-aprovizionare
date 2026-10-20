#!/bin/sh
# Rulează la fiecare pornire a containerului, înainte de comanda principală.
set -e  # oprește-te la prima eroare

echo "→ Aplic migrațiile bazei de date..."
python manage.py migrate --noinput

echo "→ Adun fișierele statice (CSS, JS)..."
python manage.py collectstatic --noinput --verbosity 0

echo "→ Pornesc: $*"
exec "$@"
