#!/bin/sh
# Rulează la fiecare pornire a containerului, înainte de comanda principală.
set -e  # oprește-te la prima eroare

echo "→ Aplic migrațiile bazei de date..."
python manage.py migrate --noinput

echo "→ Adun fișierele statice (CSS, JS)..."
python manage.py collectstatic --noinput --verbosity 0

# Date demo la PRIMA pornire (DEMO_DATA=True în docker-compose.yml): evaluatorul are
# aplicația plină de date după o singură comandă. La pornirile următoare baza nu mai e
# goală și nu se întâmplă nimic: datele existente rămân neatinse.
if [ "$DEMO_DATA" = "True" ]; then
    echo "→ Date demo (doar la prima pornire, durează ~1 minut)..."
    python manage.py seed_demo --if-empty --password "$DEMO_PASSWORD"
fi

echo "→ Pornesc: $*"
exec "$@"
