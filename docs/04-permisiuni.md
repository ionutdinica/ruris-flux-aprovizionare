# 04 · Roluri și permisiuni

Principiul: **fiecare echipă vede ce are nevoie ca să-și facă treaba și modifică doar documentele pe care le deține.** Restricțiile se aplică pe două niveluri:

1. **acces la pagini și acțiuni**: o pagină sau o acțiune nepermisă întoarce `403 Interzis`, iar meniul nici nu o afișează;
2. **filtrarea datelor**: aceeași pagină arată câmpuri diferite în funcție de rol (de ex. Depozitul vede comenzile fără prețuri și valori).

Permisiunile se verifică **pe server**, la fiecare cerere. Ascunderea butoanelor din interfață e doar confort, nu protecție.

## Matricea de permisiuni

Legendă: **S** = creează / modifică · **C** = doar citește · **—** = fără acces

| Resursă / acțiune | Achiziții | Depozit | Contabilitate | Admin |
|---|---|---|---|---|
| **Furnizori** | S | C | C | S |
| **Produse** | S | C | C | S |
| **Comenzi** – vizualizare | C (cu prețuri) | C (**fără prețuri**) | C (cu prețuri) | C |
| **Comenzi** – creare, editare, trimitere, anulare, închidere | S | — | — | S |
| **Comenzi** – import / export Excel | S | — | export | S |
| **Recepții** – vizualizare | C | C | C | C |
| **Recepții** – creare, confirmare | — | S | — | S |
| **Discrepanțe** – vizualizare | C | C | C | C |
| **Discrepanțe** – rezolvare (atașare / retur) | S | — | — | S |
| **Stoc** – vizualizare | C | C | C | C |
| **Stoc** – consum, retur, ajustare inventar | — | S | — | S |
| **Facturi** – vizualizare | C (status și motive, fără detalii de plată) | — | C | C |
| **Facturi** – înregistrare, validare, aprobare, forțare, plată, respingere | — | — | S | S |
| **Cursuri BNR** – vizualizare | C | — | C | C |
| **Cursuri BNR** – „Actualizează acum” (altfel automat) | — | — | S | S |
| **Notificări trimise** | doar ale lui | doar ale lui | doar ale lui | toate + „Trimite acum” |
| **Jurnal de audit** (global) | — | — | — | C |
| **Istoric pe document** | pe documentele pe care le vede, fără detaliile plății | idem | idem | toate |
| **Utilizatori** | — | — | — | S |

## Justificări

- **Ciornele de comandă sunt interne Achizițiilor.** Depozitul și Contabilitatea văd o comandă abia după trimitere, când devine angajament față de furnizor.
- **Depozitul nu vede prețuri și facturi.** Nu are nevoie de ele ca să numere marfa. Principiul minimului necesar reduce și riscul de scurgere a informațiilor comerciale.
- **Achizițiile văd statusul facturilor.** Când o factură e blocată pe o comandă a lor, ei sunt cei care vorbesc cu furnizorul. Fără această vizibilitate am fi din nou la „întrebat pe email”.
- **Contabilitatea vede comenzile și recepțiile în citire.** Exact informația care îi lipsea în cerință („ce s-a comandat și ce a ajuns efectiv”).
- **Doar Achizițiile rezolvă discrepanțele.** Doar ei știu dacă marfa necomandată trebuie păstrată (și pe ce comandă) sau returnată.
- **Admin** are acces complet pentru administrare și suport, dar și acțiunile lui apar în audit.

## Implementare

- Rolul e un câmp pe `User` (un utilizator are exact un rol, I-02).
- Matricea de mai sus este transcrisă **o singură dată** în cod, în [`apps/accounts/permissions.py`](../apps/accounts/permissions.py), ca dicționar `cheie de permisiune → roluri`: `"orders.edit": {Achiziții, Admin}`.
- Restul aplicației verifică doar permisiuni, niciodată roluri direct:
  - view-uri: `class OrderCreateView(PermissionMixin, CreateView): permission = "orders.edit"` → 403 fără permisiune;
  - cod Python: `user.can("orders.edit")`;
  - șabloane: `{% if user|can:"orders.view_prices" %}` (ex. Depozitul nu vede coloana de prețuri);
  - meniul: fiecare element declară permisiunea necesară.
- O cheie de permisiune scrisă greșit ridică eroare (nu întoarce în tăcere „fără acces”).
- **Istoricul respectă aceleași reguli ca pagina.** Un model își declară informațiile sensibile (`AUDIT_RESTRICTED`, ex. pe `Invoice`: data și referința plății, vizibile doar cu `invoices.view_payment`), iar istoricul documentului le ascunde celor fără permisiune. Altfel istoricul ar fi dezvăluit exact ce pagina ascunde (problemă prinsă de teste).
- Testul [`test_permissions.py`](../apps/accounts/tests/test_permissions.py) conține matricea rescrisă independent și o compară cu codul, pentru fiecare permisiune × fiecare rol.
