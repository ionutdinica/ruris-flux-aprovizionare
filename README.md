# Flux de aprovizionare – RURIS

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

Crearea unui cont de administrator:

```bash
docker compose exec web python manage.py createsuperuser
```

Oprire: `docker compose down` (datele rămân) sau `docker compose down -v` (șterge și baza de date).

## Pornire locală (fără Docker)

Cerințe: Python 3.12+.

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env            # apoi completează SECRET_KEY în .env
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Aplicația pornește la http://127.0.0.1:8000.

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
