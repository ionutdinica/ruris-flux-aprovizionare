# Flux de aprovizionare – RURIS

[![CI](https://github.com/ionutdinica/ruris-flux-aprovizionare/actions/workflows/ci.yml/badge.svg)](https://github.com/ionutdinica/ruris-flux-aprovizionare/actions/workflows/ci.yml)

Aplicație web internă care leagă **Achizițiile**, **Depozitul** și **Contabilitatea** într-un singur flux:

**Comandă → Recepție → Factură → Plată**

cu potrivire automată în 3 direcții (*three-way match*): o factură ajunge la plată doar dacă se potrivește cu ce s-a comandat **și** cu ce a ajuns efectiv în depozit.

> 🚧 Proiect în lucru. Progresul pe capitole este urmărit în [PLAN.md](PLAN.md).

## Pornire cu Docker (recomandat)

Cerințe: [Docker Desktop](https://www.docker.com/products/docker-desktop/).

```bash
docker compose up --build
```

| Serviciu | Adresă | Rol |
|---|---|---|
| Aplicația | http://localhost:8000 | Django + Gunicorn |
| Mailpit | http://localhost:8025 | căsuța de email de test: aici apar emailurile trimise de aplicație |
| PostgreSQL | (intern) | baza de date |
| Planificator | (fără pagină) | job-urile periodice: cursurile BNR, rezumatul zilnic pe email |

Crearea unui cont de administrator:

```bash
docker compose exec web python manage.py createsuperuser
```

Oprire: `docker compose down` (datele rămân) sau `docker compose down -v` (șterge și baza de date).

## Pornire pentru dezvoltare (aplicația din Python, baza de date din Docker)

Cerințe: Python 3.12+ și Docker (doar pentru PostgreSQL, aceeași versiune ca la livrare).
Fără Docker: orice PostgreSQL 17+ instalat local, cu adresa lui în `DATABASE_URL` din `.env`.

```bash
docker compose up -d db mailpit   # PostgreSQL (portul 5433) + Mailpit (emailuri: http://localhost:8025)
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env            # apoi completează SECRET_KEY în .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Aplicația pornește la http://127.0.0.1:8000.

Job-urile periodice (cursurile BNR, emailurile) rulează într-un al doilea terminal:

```bash
python manage.py run_scheduler        # sau o singură dată: python manage.py fetch_bnr_rates
```

## Date demo

O comandă generează ~4 luni de activitate a unei firme (8 furnizori, ~65 de comenzi, ~55 de
facturi), cu fiecare situație din cerință: livrare în tranșe, factură pe marfă nesosită, preț
diferit, marfă necomandată, comandă întârziată, factură în EUR emisă sâmbăta etc.

```bash
python manage.py seed_demo --password ParolaDemo1   # doar pe o bază de date goală
```

Conturile create (aceeași parolă): `andrei.ionescu` (Admin), `maria.pop` și `radu.vasile`
(Achiziții), `ion.marin` (Depozit), `elena.dobre` (Contabilitate). Fără `--password`, parola
se generează și se afișează o singură dată. Cursurile BNR se descarcă de la BNR (e nevoie de
internet); fără ele, facturile în EUR sunt sărite. `--reset` șterge tot și regenerează, doar
unde `DEMO_RESET_ALLOWED=True`.

## Teste și calitatea codului

```bash
pytest                 # rulează testele
pytest --cov           # + raport de acoperire a codului
ruff check .           # verifică greșeli și stil
ruff format .          # formatează codul uniform
```

## Documentație de analiză și design

| Document | Conținut |
|---|---|
| [Ipoteze și glosar](docs/01-ipoteze.md) | Deciziile luate acolo unde cerința nu e explicită |
| [Modelul de date](docs/02-model-date.md) | Entitățile, relațiile și câmpurile |
| [Fluxuri și stări](docs/03-fluxuri-si-stari.md) | Fluxul între echipe și ciclul de viață al documentelor |
| [Roluri și permisiuni](docs/04-permisiuni.md) | Cine ce vede și ce poate face |
| [Reguli de business](docs/05-reguli-business.md) | Potrivirea facturilor, cursul BNR, întârzieri, blocaje, notificări |
