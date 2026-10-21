# Flux de aprovizionare · RURIS

[![CI](https://github.com/ionutdinica/ruris-flux-aprovizionare/actions/workflows/ci.yml/badge.svg)](https://github.com/ionutdinica/ruris-flux-aprovizionare/actions/workflows/ci.yml)

Aplicație web internă care leagă **Achizițiile**, **Depozitul** și **Contabilitatea** într-un singur flux:

**Comandă → Recepție → Factură → Plată**

Fiecare echipă vede ce o privește, iar aplicația spune singură ce întârzie și ce e blocat. O
factură ajunge la plată doar dacă se potrivește cu ce s-a comandat **și** cu ce a sosit efectiv
în depozit (potrivire în 3 direcții, *three-way match*).

## Cerințele și cum sunt rezolvate

| Cerința | Rezolvare |
|---|---|
| **Conturi pe echipă, fiecare vede doar ce o privește; audit** (cine, ce, când) | 4 roluri, o matrice de permisiuni verificată pe server la fiecare cerere (Depozitul nu vede prețuri); jurnal de audit cu modificările câmp cu câmp și evenimentele de business; istoricul fiecărui document |
| **Emailuri periodice despre ce întârzie și ce e blocat** | un rezumat zilnic pe persoană, doar cu problemele ei (comenzi întârziate, facturi blocate, marfă în carantină, scadențe), cu marcajul **NOU**; nimic de rezolvat → niciun email |
| **Facturi în RON / EUR, convertite la cursul din ziua facturii, preluat automat** | cursul BNR descărcat zilnic; factura de sâmbătă primește cursul de vineri; o factură de azi, înainte de publicarea BNR, așteaptă și se finalizează singură; niciun curs inventat |
| **Livrare într-un repository Git** | acest repository: cod, ~1.000 de teste, CI pe GitHub, documentație, pornire cu o singură comandă |

Plus: potrivirea comandă–recepție–factură (o factură blocată **se deblochează singură** când sosește
marfa), registru de stoc, carantină pentru marfa necomandată, **bugete anuale pe furnizor** (o
comandă peste buget pleacă doar cu justificare), import / export Excel, panou pe rol cu grafice.

## Capturi de ecran

**Panoul Achizițiilor**: ce e de rezolvat și cât de punctuali sunt furnizorii
![Panoul Achizițiilor](docs/img/panou-achizitii.jpg)

**Potrivirea unei facturi**: comandat · recepționat · facturat, pe fiecare linie
![Ecranul de potrivire al facturii](docs/img/potrivire-factura.jpg)

**Panoul Contabilității**: facturi blocate, scadențe, sume de plată
![Panoul Contabilității](docs/img/panou-contabilitate.jpg)
![Graficele Contabilității](docs/img/grafice-contabilitate.jpg)

**Bugetele pe furnizor**: plafonul anual, cât s-a angajat și cât a rămas
![Bugetele pe furnizor](docs/img/bugete.jpg)

**Rezumatul zilnic pe email** (în Mailpit, căsuța de test): fiecare primește doar problemele lui
![Emailul zilnic](docs/img/email-rezumat.jpg)

**Jurnalul de audit**: cine, ce și când, cu modificările câmp cu câmp
![Jurnalul de audit](docs/img/jurnal-audit.jpg)

## Pornire (o singură comandă)

Cerință: [Docker Desktop](https://www.docker.com/products/docker-desktop/) (gratuit; Windows, macOS, Linux).

```bash
git clone https://github.com/ionutdinica/ruris-flux-aprovizionare.git
cd ruris-flux-aprovizionare
docker compose up --build
```

Prima pornire durează câteva minute: Docker descarcă imaginile (Python, PostgreSQL), apoi se
generează automat **date demo**: ~4 luni de activitate, 8 furnizori, ~65 de comenzi, ~55 de
facturi, cu fiecare situație din cerință (e nevoie de internet, pentru cursurile BNR). Aplicația
e gata când în terminal apare `Pornesc: gunicorn`. Apoi:

| Ce | Unde |
|---|---|
| Aplicația | http://localhost:8000 |
| Emailurile trimise (Mailpit) | http://localhost:8025 |

Parola pentru toate conturile: **`demo-ruris`** (aplicația rulează doar pe calculatorul tău, cu date inventate).

| Cont | Rol |
|---|---|
| `maria.pop`, `radu.vasile` | Achiziții (fiecare își vede comenzile lui) |
| `ion.marin` | Depozit |
| `elena.dobre` | Contabilitate |
| `andrei.ionescu` | Administrator |

Oprire: `docker compose down` (datele rămân) · de la zero, cu date demo proaspete:
`docker compose down -v` și din nou `docker compose up --build`.

## Încearcă un ciclu complet (~10 minute)

Un flux întreg, de la comandă la plată, prin toate cele patru roluri. Pornește de la o comandă
nouă, deci merge la fel pe orice date demo. Sfat: deschide fiecare cont într-o fereastră privată
separată, ca să treci de la un om la altul fără deconectare.

**Povestea:** Maria comandă rulmenți și curele. Furnizorul livrează curelele în două tranșe, dar
le facturează pe toate de la început. Factura se blochează, apoi **se deblochează singură** când
sosește restul mărfii, și ajunge la plată.

| # | Cine | Ce face | Ce trebuie să vezi |
|---|---|---|---|
| 1 | **`maria.pop`** (Achiziții) | *Comenzi → Comandă nouă*: furnizor **Rulmenți Oltenia**, termen peste 7 zile; liniile **RUL-6204 × 100 la 18,90** și **CUR-A42 × 50 la 18,50** → *Salvează* → *Trimite comanda* | comanda e **Trimisă** |
| 2 | **`ion.marin`** (Depozit) | *Recepții → Livrări așteptate* → comanda → *Recepționează*: **100** rulmenți, **30** de curele → *Salvează ciorna* → *Confirmă recepția* | comanda e **Parțial recepționată**, iar stocul a crescut |
| 3 | **`elena.dobre`** (Contabilitate) | pe pagina comenzii → *Înregistrează factura*: liniile vin completate cu ce a sosit (100 și 30). Corectează curelele la **50**, cum le-a facturat furnizorul; nr. factură furnizor **TEST-1**, data de azi, scadența peste 30 de zile; totalurile de pe factură **2.815,00 / 591,15 / 3.406,15** → *Salvează și validează* | factura e **Blocată**: *„facturat 50 buc, recepționat doar 30 buc: 20 buc nesosite”* |
| 4 | **`andrei.ionescu`** (Admin) | *Administrare → Notificări trimise → Trimite acum*, apoi Mailpit (http://localhost:8025) | emailul Mariei conține factura blocată, marcată **NOU** |
| 5 | **`ion.marin`** | recepționează restul: **20** de curele → *Confirmă recepția* | comanda e **Recepționată** |
| 6 | **`elena.dobre`** | reîncarcă factura | e **Potrivită**, fără ca Elena să facă ceva; în istoric: *„a devenit automat «Potrivită»”* |
| 7 | **`elena.dobre`** | *Aprobă la plată* → *Marchează plătită* | factura e **Plătită** |
| 8 | **`andrei.ionescu`** | pagina comenzii sau a facturii → *Istoricul complet* (sau *Administrare → Jurnal de activitate*) | toată povestea, cu cine și când: trimitere, două recepții, factura blocată, deblocarea automată (declanșată de recepția lui Ion), aprobare, plată |

Ciclul e verificat automat, cu exact aceste cifre și mesaje, de testul
[tests/test_readme_cycle.py](tests/test_readme_cycle.py). Pentru un tur mai larg al aplicației,
pe roluri (carantină, cursul BNR pe o factură de sâmbătă, grafice), vezi ghidul
[docs/07-ghid-demonstratie.md](docs/07-ghid-demonstratie.md).

## Documentație

| Document | Conținut |
|---|---|
| [Ipoteze](docs/01-ipoteze.md) | deciziile luate acolo unde cerința nu e explicită |
| [Modelul de date](docs/02-model-date.md) | entitățile, relațiile și câmpurile |
| [Fluxuri și stări](docs/03-fluxuri-si-stari.md) | fluxul între echipe și ciclul de viață al documentelor |
| [Roluri și permisiuni](docs/04-permisiuni.md) | cine ce vede și ce poate face |
| [Reguli de business](docs/05-reguli-business.md) | potrivirea facturilor, cursul BNR, întârzieri, blocaje, notificări, indicatori |
| [Arhitectura](docs/06-arhitectura.md) | cum e construită aplicația și de ce |
| [Ghid de demonstrație](docs/07-ghid-demonstratie.md) | scenariul de prezentare și întrebările probabile |

## Tehnologii

Python 3.13 · **Django 5.2** · **PostgreSQL 17** · HTMX · Bootstrap 5 · Chart.js · django-auditlog ·
openpyxl (Excel) · Docker · pytest · ruff · GitHub Actions.

## Teste și calitate

- **~1.000 de teste** automate, pe PostgreSQL: regulile de business, paginile, permisiunile (fiecare
  pagină × fiecare rol, verificat automat) și un test cap-coadă al fluxului complet.
- **Acoperire 97%**, cu prag minim de 95%.
- **CI** la fiecare modificare: stilul codului, testele, pasul de producție pentru fișierele
  statice, migrațiile uitate, imaginea Docker.

## Pentru dezvoltatori

Aplicația din Python, cu baza de date și Mailpit din Docker (Python 3.12+):

```bash
docker compose up -d db mailpit   # PostgreSQL (portul 5433) + Mailpit (http://localhost:8025)
python -m venv .venv
.venv\Scripts\activate            # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -r requirements-dev.txt
copy .env.example .env            # apoi completează SECRET_KEY în .env (Linux/macOS: cp)
python manage.py migrate
python manage.py seed_demo --if-empty --password demo-ruris   # date demo, dacă baza e goală
python manage.py runserver
```

Alte comenzi:

```bash
python manage.py run_scheduler    # job-urile periodice: cursul BNR, rezumatul zilnic pe email
pytest                            # testele (pytest --cov: cu raport de acoperire)
ruff check . && ruff format .     # stilul codului
```

Structura: fiecare zonă a afacerii e un modul în `apps/` (`purchasing`, `warehouse`,
`invoicing`, `currency`, `notifications`, `dashboard`, `audit` etc.), cu regulile de business în
`services.py`, separate de pagini. Detalii în [Arhitectura](docs/06-arhitectura.md).

## Ce aș face mai departe

- **e-Factura (ANAF SPV):** preluarea automată a facturilor primite, în locul introducerii manuale.
- **Plăți:** exportul ordinelor de plată pentru bancă (sau integrare directă) pentru facturile aprobate.
- **Valoarea stocului:** evaluare FIFO / cost mediu ponderat, pe lângă cantități.
- **Comenzi trimise automat furnizorilor** (email cu PDF-ul comenzii) și confirmarea lor.
- **Autentificare cu conturile firmei** (Microsoft 365 / Active Directory), fără parole separate.
- **Producție:** server intern cu backup automat al bazei de date, HTTPS și serverul de email al firmei.
