# Plan proiect – Flux de aprovizionare (RURIS)

> Aplicație web internă care leagă **Achizițiile**, **Depozitul** și **Contabilitatea** într-un singur flux:
> **Comandă → Recepție → Factură → Plată**, cu potrivire automată în 3 direcții (*three-way match*).

Legendă: `[ ]` de făcut · `[x]` gata · **(opțional)** = după ce obligatoriile sunt complete

---

## Decizii luate

| Subiect | Decizie | Motiv |
|---|---|---|
| Limbaj / framework | **Python 3 + Django 5.2 LTS** | Autentificare, permisiuni, ORM, migrații, formulare și admin incluse, deci timpul merge pe logica de business |
| Interfață | Șabloane Django + **HTMX** + **Bootstrap 5** | Fără pas de build pentru frontend; interfață dinamică fără SPA separat |
| Bază de date | **PostgreSQL** (producție / Docker), **SQLite** (rulare locală rapidă) | Pornire locală fără nicio instalare în plus |
| Audit | **django-auditlog** + evenimente de business explicite | Diff automat al câmpurilor (cine/ce/când) și acțiuni importante cu justificare |
| Excel | **openpyxl** | Import și export comenzi (.xlsx) |
| Curs valutar | **BNR** – XML zilnic + arhive anuale | Sursa oficială pentru cursul leului |
| Job-uri periodice | Comenzi Django (`fetch_bnr_rates`, `send_notifications`) declanșate de un scheduler | Aceeași logică rulează local, în Docker și online |
| Email | Local: **Mailpit** (SMTP de test cu interfață web) · Online: un SMTP real (de ales la deploy) | Evaluatorii pot vedea emailurile trimise |
| Teste | **pytest + pytest-django + factory_boy** | Standard, ușor de citit |
| Calitate cod | **ruff** (lint + format), **GitHub Actions** (CI) | |
| Limbă | Interfață, README, commit-uri: **română** · Cod (nume de variabile, clase): **engleză** | Codul în engleză evită diacriticele în identificatori și e convenția uzuală |
| Livrare | Repository public pe **github.com/ionutdinica**, rulare locală (cu și fără Docker) + **deploy online** pentru demo | Pot testa fără să instaleze nimic |

---

## Capitolul 0 – Analiză și design (fără cod)

- [x] **0.1 Glosar și ipoteze** → [docs/01-ipoteze.md](docs/01-ipoteze.md) (31 de ipoteze numerotate `I-xx` + ce e în afara proiectului)
- [x] **0.2 Modelul de date** → [docs/02-model-date.md](docs/02-model-date.md) (diagramă ER + câmpurile fiecărei entități)
- [x] **0.3 Fluxuri și mașini de stare** → [docs/03-fluxuri-si-stari.md](docs/03-fluxuri-si-stari.md) (comandă, recepție, discrepanță, factură)
- [x] **0.4 Matricea de permisiuni** → [docs/04-permisiuni.md](docs/04-permisiuni.md)
- [x] **0.5 Regulile de business** → [docs/05-reguli-business.md](docs/05-reguli-business.md) (potrivire cu coduri de motiv, curs, stoc, „întârziat”/„blocat”, notificări)
- [x] **0.6 Validarea design-ului** împreună (citire + ajustări) înainte de capitolul 1

**Rezultat:** documentele din `docs/` sunt gata și design-ul e validat înainte de prima linie de cod. Diagramele sunt în Mermaid și GitHub le afișează direct.

---

## Capitolul 1 – Fundația proiectului

- [x] 1.1 Repository Git local + repository pe GitHub, `.gitignore`, `README.md` inițial
- [x] 1.2 Proiect Django, structurat pe aplicații:
  `accounts`, `audit`, `catalog`, `purchasing`, `warehouse`, `invoicing`, `currency`, `notifications`, `dashboard`
- [ ] 1.3 Configurare prin variabile de mediu (`.env` + `.env.example`), setări separate dev/prod
- [ ] 1.4 Layout de bază: Bootstrap 5, HTMX, meniu în funcție de rol, mesaje flash
- [ ] 1.5 `ruff`, `pytest` configurate · primul test care trece
- [ ] 1.6 **Docker Compose**: `web` + `postgres` + `mailpit` + `scheduler`
- [ ] 1.7 **GitHub Actions**: lint + teste la fiecare push

**Rezultat:** aplicația pornește local cu `python manage.py runserver` și cu `docker compose up`, iar CI-ul trece.

---

## Capitolul 2 – Utilizatori, roluri, audit

- [ ] 2.1 Login / logout, schimbarea parolei, model `User` cu rol (grupuri Django)
- [ ] 2.2 Mixin-uri / decoratori de permisiuni + filtrarea datelor pe rol (ex.: Depozitul nu vede prețurile)
- [ ] 2.3 Audit automat pe toate modelele importante (django-auditlog: utilizator, acțiune, câmpuri vechi → noi, dată, IP)
- [ ] 2.4 Evenimente de business în audit (ex.: „Factură aprobată forțat – justificare: …”)
- [ ] 2.5 Pagina **Jurnal de activitate** (Admin), cu filtre după utilizator, tip document, perioadă
- [ ] 2.6 Istoric pe fiecare document (secțiunea „Istoric” pe pagina comenzii / facturii)
- [ ] 2.7 Teste: fiecare rol primește 403 pe ce nu are voie

---

## Capitolul 3 – Nomenclatoare

- [ ] 3.1 Furnizori: CRUD, CUI, email de contact, monedă implicită
- [ ] 3.2 Produse: CRUD, cod, denumire, unitate de măsură
- [ ] 3.3 Căutare și paginare pe liste (HTMX)

---

## Capitolul 4 – Achiziții: comenzi

- [ ] 4.1 Creare / editare comandă cu linii dinamice (HTMX): produs, cantitate, preț, monedă, dată estimată
- [ ] 4.2 Tranzițiile de status (Trimite, Anulează, Închide) cu validări
- [ ] 4.3 Status de recepție calculat automat din recepții; progres pe fiecare linie (comandat / recepționat / facturat)
- [ ] 4.4 Lista comenzilor cu filtre: status, furnizor, **întârziate**
- [ ] 4.5 **Import din Excel**: șablon descărcabil, validare rând cu rând, raport de erori, previzualizare înainte de salvare
- [ ] 4.6 **Export în Excel**: comenzile filtrate, cu cantitățile recepționate și facturate
- [ ] 4.7 Rezolvarea discrepanțelor primite de la Depozit (marfă necomandată → atașează la o comandă / marchează retur)

---

## Capitolul 5 – Depozit: recepții și stoc

- [ ] 5.1 Lista livrărilor așteptate (comenzi trimise, sortate după data estimată, fără prețuri)
- [ ] 5.2 Recepție pe o comandă: completare cantități primite; oricâte tranșe pe aceeași comandă
- [ ] 5.3 Confirmarea recepției generează mișcările de stoc (în tranzacție atomică)
- [ ] 5.4 Cazuri speciale:
  - livrare parțială (comanda rămâne deschisă)
  - livrare peste cantitatea comandată (generează discrepanță)
  - **marfă necomandată** (recepție fără comandă sau linie în plus, care generează discrepanță spre Achiziții)
- [ ] 5.5 Stoc curent pe produs, calculat din registrul de mișcări, cu istoricul mișcărilor
- [ ] 5.6 Ieșiri de stoc (consum, retur la furnizor) și ajustări de inventar, cu motiv; stocul nu poate deveni negativ

---

## Capitolul 6 – Curs valutar BNR

- [ ] 6.1 Client BNR: parsare XML zilnic (`nbrfxrates.xml`) și arhive anuale (`nbrfxratesYYYY.xml`), cu `defusedxml`
- [ ] 6.2 Salvarea cursurilor în baza de date (o singură descărcare pe zi, nu la fiecare factură)
- [ ] 6.3 `get_rate(currency, date)`: curs exact, sau ultimul curs anterior (weekend / sărbătoare); RON → 1
- [ ] 6.4 BNR indisponibil: factura intră în `Curs în așteptare`, iar job-ul reîncearcă și o deblochează automat
- [ ] 6.5 Comanda `fetch_bnr_rates` (zilnic) + popularea istoricului la prima rulare
- [ ] 6.6 Teste cu XML salvat local (fără apeluri reale de rețea în teste)

---

## Capitolul 7 – Contabilitate: facturi și potrivire

- [ ] 7.1 Înregistrare factură: furnizor, număr, dată, scadență, monedă, linii legate de comandă, TVA
- [ ] 7.2 Conversia automată în RON; cursul și data cursului se salvează pe factură și nu se mai schimbă
- [ ] 7.3 **Motorul de potrivire în 3 direcții** (serviciu separat, independent de interfață, testat exhaustiv)
- [ ] 7.4 Ecran de potrivire: tabel comandat / recepționat / facturat pe linie, cu motivele de blocare evidențiate
- [ ] 7.5 Reverificare automată: la confirmarea unei recepții noi, facturile blocate aferente se reverifică
- [ ] 7.6 Aprobare la plată / marcare plătită; **forțarea** unei facturi blocate doar cu justificare obligatorie (în audit)
- [ ] 7.7 Facturi duplicat respinse (același furnizor + același număr)

---

## Capitolul 8 – Notificări email

- [ ] 8.1 Regulile pe destinatar:
  - **Achiziții** (responsabilul comenzii): comenzile lui întârziate, discrepanțele deschise, facturile blocate pe comenzile lui
  - **Depozit**: livrări așteptate azi și întârziate
  - **Contabilitate**: facturi blocate, facturi aprobate cu scadență apropiată, facturi fără curs
- [ ] 8.2 Un **rezumat** per persoană (un singur email, pe secțiuni), în format HTML + text, cu link-uri în aplicație
- [ ] 8.3 Comanda `send_notifications` + scheduler (ora configurabilă; implicit zilnic la 08:00)
- [ ] 8.4 `NotificationLog`: ce s-a trimis, cui, când; fără emailuri goale, fără dubluri în aceeași zi
- [ ] 8.5 Pagina **Notificări trimise** + butonul „Trimite acum” (Admin, util la demo)

---

## Capitolul 9 – Dashboard pe rol

- [ ] 9.1 Pagina de start diferită pe rol, cu cardurile „ce necesită atenție” (întârziate, blocate, discrepanțe)
- [ ] 9.2 Indicatori: valoare facturi blocate (RON), comenzi întârziate, rata livrărilor la timp pe furnizor
- [ ] 9.3 Grafice (Chart.js): valoare facturi pe status, livrări la timp pe furnizor, evoluția comenzilor întârziate, stoc pe produs

---

## Capitolul 10 – Testare și date demo

- [ ] 10.1 Teste unitare: potrivire (toate regulile), curs (weekend, sărbători, indisponibil), stări, permisiuni
- [ ] 10.2 Teste de integrare: flux complet comandă → 2 tranșe recepție → factură → aprobare
- [ ] 10.3 Comanda `seed_demo`: utilizatori demo pe fiecare rol + scenarii care acoperă **fiecare situație din cerință**:
  - comandă livrată complet și facturată corect (potrivită, aprobată)
  - comandă livrată în 2 tranșe
  - livrare parțială + factură pe tot (blocată: *facturat dar nerecepționat*)
  - factură cu preț greșit (blocată: *preț diferit*)
  - marfă necomandată (discrepanță deschisă)
  - comandă întârziată
  - factură în EUR emisă într-o sâmbătă (curs din vineri)
- [ ] 10.4 Acoperirea testelor raportată în CI

---

## Capitolul 11 – Documentație și livrare

- [ ] 11.1 `README.md`: ce face aplicația, cum se pornește (local, Docker), conturi demo, scenariu de demo pas cu pas
- [ ] 11.2 `docs/`: ipoteze, arhitectură, diagrama de flux, diagrama ER, reguli de potrivire, matricea de permisiuni
- [ ] 11.3 Capturi de ecran în README
- [ ] 11.4 **Deploy online** (platformă de ales la momentul respectiv) + job-urile periodice programate online
- [ ] 11.5 Secțiunea „Ce aș face mai departe”: integrare e-Factura ANAF, plăți, evaluare stoc (FIFO/CMP), comenzi trimise automat furnizorilor
- [ ] 11.6 Verificare finală: clonare curată pe un folder nou și pornire urmând doar README-ul

---

## Reguli de lucru

- Lucrăm **capitol cu capitol**; fiecare capitol se încheie cu teste care trec și unul sau mai multe commit-uri.
- Commit-uri mici, în română, la imperativ (ex.: `Adaugă motorul de potrivire pentru facturi`).
- Banii și cantitățile se țin numai în `Decimal`, niciodată în `float`.
- Logica de business stă în **servicii** (`services.py`), nu în view-uri, ca să fie testabilă și refolosită de job-uri.
- Documentele confirmate (recepții, facturi aprobate) nu se editează; se corectează prin documente noi, vizibile în audit.
