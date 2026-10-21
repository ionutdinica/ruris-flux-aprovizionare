# 05 · Reguli de business

Regulile de aici sunt **sursa de adevăr** pentru implementare și teste. Fiecare regulă are un cod, folosit în cod, în mesajele afișate și în teste.

## 1. Potrivirea în 3 direcții (factură ↔ comandă ↔ recepție)

Se rulează la **validarea** facturii și automat la orice eveniment care poate schimba rezultatul: recepție confirmată, discrepanță rezolvată, retur la furnizor, modificare de comandă. Nu se rulează pentru facturi `APPROVED`, `PAID` sau `REJECTED`.

Rezultatul este o **listă de motive**: dacă e goală, factura devine `MATCHED`, altfel `BLOCKED`. Toate motivele se afișează simultan, nu doar primul găsit.

### Verificări la nivel de antet

| Cod | Regulă | Mesaj afișat |
|---|---|---|
| `SUPPLIER_MISMATCH` | Fiecare linie trebuie să refere o comandă a **aceluiași furnizor** ca factura | „Linia X aparține comenzii CMD-… a altui furnizor” |
| `CURRENCY_MISMATCH` | Moneda facturii = moneda fiecărei comenzi referite (I-17) | „Factura este în EUR, comanda CMD-… este în RON” |
| `TOTAL_MISMATCH` | \|total declarat − total calculat\| ≤ 0,05 (net, TVA, total) (I-19, I-22) | „Totalul declarat 1.250,00 diferă de totalul calculat 1.190,00” |
| `ORDER_NOT_OPEN` | Comanda referită nu e `CANCELLED` sau `DRAFT` | „Comanda CMD-… este anulată” |

### Verificări pe fiecare linie de comandă facturată

Notații, pentru o linie de comandă `L`:
- `comandat(L)` = cantitatea comandată;
- `recepționat(L)` = cantitatea recepționată netă (recepții acceptate + discrepanțe atașate − retururi);
- `facturat(L)` = Σ cantități pe **toate** facturile nerespinse care conțin `L`, **inclusiv** factura curentă.

| Cod | Regulă | Mesaj afișat |
|---|---|---|
| `NOT_RECEIVED` | `facturat(L)` ≤ `recepționat(L)` | „Produs P: facturat 100, recepționat doar 60 — **40 nesosite**” |
| `OVER_ORDERED` | `facturat(L)` ≤ `comandat(L)` | „Produs P: facturat 120, comandat 100” |
| `PRICE_MISMATCH` | \|preț facturat − preț comandă\| ≤ preț comandă × toleranță (I-22) | „Produs P: preț 10,50 EUR față de 10,00 EUR în comandă (+5%)” |
| `DUPLICATE_LINE` | O linie de comandă apare o singură dată pe aceeași factură | „Linia de comandă X apare de 2 ori” |

Faptul că `facturat(L)` include facturile anterioare este esențial: altfel aceeași marfă ar putea fi facturată (și plătită) de două ori pe facturi diferite, fiecare părând corectă separat.

### Validări care împiedică salvarea (nu blochează, ci resping)

Acestea sunt erori de introducere, nu diferențe față de furnizor:
- furnizor + număr factură deja existent (I-21);
- data facturii în viitor (I-27); scadența înaintea datei facturii;
- cantități sau prețuri ≤ 0; factură fără linii.

## 2. Curs valutar

```
get_rate(moneda, data_factura):                    # apps/currency/services.py
    dacă moneda == RON                                  → 1, data_factura
    dacă data_factura > azi                             → eroare (I-27)
    dacă nu știm sigur cursul zilei (vezi mai jos):
        data_factura == azi și ora < 14:00              → ÎN AȘTEPTARE (I-26)
        altfel (BNR nu a răspuns)                       → ÎN AȘTEPTARE (I-28)
    curs = cel mai recent curs BNR cu data ≤ data_factura
    dacă nu există sau e cu peste 7 zile mai vechi      → ÎN AȘTEPTARE (istoric lipsă)
    altfel                                              → curs.valoare, curs.data
```

**„Știm sigur cursul zilei Z?”** Lipsa cursului pentru Z are două explicații foarte diferite: BNR nu l-a publicat *încă* sau nu îl publică *deloc* (sărbătoare). Răspunsul e „da” dacă:
1. avem un curs din Z sau de după Z; sau
2. între ultimul curs salvat și Z sunt doar zile de sâmbătă și duminică; sau
3. BNR a fost interogat cu succes după ora 14:00 a zilei Z și nu avea curs pentru Z (o zi fără publicare). De aceea fiecare interogare se salvează (`RateSync`).

Exemplu real: pentru o factură din 01.01.2026 se aplică cursul din 31.12.2025 (5,0985), iar pentru 07.01.2026 (Sf. Ioan), cel din 05.01.2026.

- Cursul și data efectivă a cursului se salvează pe factură; afișare: „Curs BNR 5,3368 din 16.10.2026 (factura e din 17.10.2026, sâmbătă)”.
- `total_ron = total_declarat × curs / multiplicator`, rotunjit la 2 zecimale (rotunjire comercială `ROUND_HALF_UP`, ca în contabilitate).
- **Sursa:** `https://curs.bnr.ro` (setarea `BNR_BASE_URL`): fișierul cu ultimele 10 zile (`nbrfxrates10days.xml`) și arhivele anuale (`files/xml/years/nbrfxratesAAAA.xml`). Un răspuns care nu e exact formatul BNR (ex. o pagină HTML după o mutare a site-ului) e tratat ca eroare, nu ca „niciun curs nou”.
- **Job-ul `fetch_bnr_rates`** e pornit de planificator (`run_scheduler`) la fiecare 10 minute, dar descarcă doar când lipsește ceva: de regulă o dată pe zi, după 13:00; în weekend deloc. La prima rulare încarcă istoricul anului curent și al celui anterior; după o pauză mai lungă de 10 zile completează golul din arhivele anuale. După fiecare actualizare reușită trimite semnalul `rates_synced`, la care facturile `RATE_PENDING` se reiau (capitolul 7).
- Contabilitatea și Adminul pot cere actualizarea imediată din pagina *Cursuri BNR* („Actualizează acum”).

## 3. Recepție și stoc

- La confirmarea recepției: `acceptat = min(primit, comandat − recepționat până acum)`; restul merge în carantină (I-11).
- Linie de recepție fără linie de comandă → integral în carantină, discrepanță `UNORDERED`.
- Ieșirile (consum, retur, ajustare negativă) sunt refuzate dacă ar duce stocul disponibil sub zero (I-14).
- Rezolvare discrepanță prin **atașare**: linia aleasă trebuie să fie a aceluiași furnizor și produs și să aibă rest de recepționat ≥ cantitatea din carantină. Dacă nu are, Achizițiile adaugă mai întâi o linie sau măresc cantitatea în comandă (regularizare), apoi atașează.
- Scurtătură pentru **surplus** (`OVER_DELIVERY`): „Acceptă surplusul” mărește cantitatea comandată pe linie cu surplusul (vizibil în istoricul comenzii) și îl atașează, într-un singur pas. Nu e posibil pe o comandă închisă sau anulată.
- La recepție, Depozitul introduce cantitatea **numărată**; cantitatea așteptată e afișată alături, dar câmpul nu e precompletat (altfel recepția ar deveni un click fără numărare).
- Recepțiile pe aceeași comandă și ieșirile pe același produs sunt serializate (blocare în baza de date), ca operațiile simultane să nu producă stocuri sau cantități greșite.

## 4. Ce înseamnă „întârziat” și „blocat”

Sunt definițiile folosite de dashboard și de notificări.

### Întârziat
| Cod | Condiție | Cine trebuie să afle |
|---|---|---|
| `ORDER_LATE` | linie de comandă cu `expected_date` < azi, rest de recepționat > 0, comandă `SENT` / `PARTIALLY_RECEIVED` | responsabilul comenzii (Achiziții) + Depozitul |
| `INVOICE_DUE_SOON` | factură `APPROVED`, scadență în ≤ 3 zile | Contabilitatea |
| `INVOICE_OVERDUE` | factură `APPROVED`, scadență depășită, neplătită | Contabilitatea |

### Blocat
| Cod | Condiție | Cine trebuie să afle |
|---|---|---|
| `INVOICE_BLOCKED` | factură `BLOCKED` | Contabilitatea + responsabilii comenzilor implicate |
| `INVOICE_RATE_PENDING` | factură `RATE_PENDING` de mai mult de 1 zi lucrătoare | Contabilitatea |
| `DISCREPANCY_OPEN` | discrepanță `OPEN` (marfă în carantină) | responsabilul comenzii; dacă nu există comandă, toți utilizatorii Achiziții |
| `INVOICE_MATCHED_WAITING` | factură `MATCHED` neaprobată de > 3 zile lucrătoare | Contabilitatea |

### Informativ (doar Depozit)
| Cod | Condiție |
|---|---|
| `DELIVERY_EXPECTED_TODAY` | linii de comandă cu `expected_date` = azi și rest de recepționat > 0 |

## 5. Notificări

- Job-ul `send_notifications` rulează în zilele lucrătoare la ora configurată (implicit 08:00).
- Pentru fiecare utilizator activ se adună toate elementele din secțiunea 4 care îl privesc; dacă lista e goală, nu se trimite nimic (I-31).
- Email = un rezumat pe secțiuni (*Întârzieri*, *Blocaje*, *Azi*), fiecare element cu link direct în aplicație; elementele care nu apăreau în rezumatul anterior sunt marcate **NOU** (I-30).
- Același utilizator nu primește două rezumate automate în aceeași zi; „Trimite acum” (Admin) ignoră această limită și e consemnat în audit.
- Erorile de trimitere se înregistrează în `NotificationLog` cu statusul `FAILED`, fără să oprească trimiterea către ceilalți.

## 6. Numerotare și rotunjiri

- Numere interne pe an, fără goluri, generate în tranzacție: `CMD-2026-0001`, `REC-2026-0001`, `FAC-2026-0001`.
- Valoare linie = `round(cantitate × preț, 2)`; TVA linie = `round(valoare × cotă, 2)`; totalul = suma liniilor rotunjite (așa calculează și programele de facturare).
