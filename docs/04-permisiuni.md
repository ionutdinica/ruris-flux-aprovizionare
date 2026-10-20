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
| **Notificări trimise** | doar ale lui | doar ale lui | doar ale lui | toate + „Trimite acum” |
| **Jurnal de audit** (global) | — | — | — | C |
| **Istoric pe document** | pe documentele pe care le vede | idem | idem | toate |
| **Utilizatori** | — | — | — | S |

## Justificări

- **Depozitul nu vede prețuri și facturi.** Nu are nevoie de ele ca să numere marfa. Principiul minimului necesar reduce și riscul de scurgere a informațiilor comerciale.
- **Achizițiile văd statusul facturilor.** Când o factură e blocată pe o comandă a lor, ei sunt cei care vorbesc cu furnizorul. Fără această vizibilitate am fi din nou la „întrebat pe email”.
- **Contabilitatea vede comenzile și recepțiile în citire.** Exact informația care îi lipsea în cerință („ce s-a comandat și ce a ajuns efectiv”).
- **Doar Achizițiile rezolvă discrepanțele.** Doar ei știu dacă marfa necomandată trebuie păstrată (și pe ce comandă) sau returnată.
- **Admin** are acces complet pentru administrare și suport, dar și acțiunile lui apar în audit.

## Implementare (pe scurt)

- rolul e câmp pe `User`; câte un mixin pe view (`RoleRequiredMixin(roles=[...])`) și verificări în servicii pentru acțiuni;
- formularele și șabloanele primesc rolul și omit câmpurile financiare pentru Depozit;
- teste automate pentru **fiecare celulă „—”** din matrice: utilizatorul primește 403.
