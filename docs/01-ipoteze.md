# 01 · Ipoteze și glosar

Cerința este intenționat scurtă. Acest document consemnează **ce am presupus** acolo unde cerința nu spune explicit și **de ce**. Fiecare ipoteză este numerotată (`I-xx`) ca să poată fi referită din cod și din celelalte documente.

## Glosar

| Termen | Sens în aplicație |
|---|---|
| **Comandă** (PO – *purchase order*) | Ce a cerut Achizițiile de la un furnizor: produse, cantități, prețuri, date estimate de sosire. |
| **Recepție** (NIR – *notă de intrare-recepție*) | Ce a numărat efectiv Depozitul la sosirea unei livrări. O comandă poate avea mai multe recepții (tranșe). |
| **Factură** | Ce ne cere furnizorul să plătim. O factură poate acoperi una sau mai multe comenzi ale aceluiași furnizor. |
| **Potrivire în 3 direcții** (*three-way match*) | Verificarea automată că factura corespunde cu comanda (preț, produs) și cu recepția (cantitate). |
| **Discrepanță** | Marfă primită care nu e acoperită de o comandă (necomandată sau peste cantitatea comandată). Stă în carantină până decid Achizițiile. |
| **Carantină** | Marfă fizic în depozit, dar care **nu intră în stocul disponibil** până la rezolvarea discrepanței. |
| **Mișcare de stoc** | Orice intrare sau ieșire de marfă. Stocul curent = suma mișcărilor. |

## Organizare

- **I-01** O singură firmă, un singur depozit.
- **I-02** Fiecare utilizator are **exact un rol**: Achiziții, Depozit, Contabilitate sau Administrator. Conturile le creează Administratorul (nu există înregistrare liberă).
- **I-03** Vizibilitatea e la nivel de echipă: toți membrii Achizițiilor văd toate comenzile. Notificările însă merg la **responsabilul comenzii** (cel care a creat-o), ca fiecare să primească doar ce e al lui.
- **I-04** Comunicarea cu furnizorii rămâne în afara aplicației (email, telefon). Aplicația înregistrează ce s-a comandat; nu trimite comenzi către furnizori.

## Comenzi

- **I-05** O comandă are **un singur furnizor și o singură monedă** (RON sau EUR); toate liniile au aceeași monedă.
- **I-06** Fiecare linie are propria dată estimată de sosire (implicit: data din antetul comenzii). Furnizorii livrează adesea produse diferite la date diferite.
- **I-07** După trimitere, o comandă se mai poate modifica doar controlat: data estimată (furnizorul anunță o amânare) și adăugarea de linii / creșterea cantităților. Orice modificare rămâne în audit.
- **I-08** O comandă se poate anula doar dacă nu s-a recepționat nimic pe ea. Dacă s-a recepționat parțial și restul nu mai vine, se **închide cu rest nelivrat**, cu motiv obligatoriu.

## Recepții și stoc

- **I-09** Depozitul vede ce trebuie să vină (produse, cantități, date), dar **nu vede prețuri**. Nu are nevoie de ele ca să numere marfa.
- **I-10** O recepție se face pe **un furnizor**, de regulă cu referință la o comandă. Se poate face și **fără comandă** (a venit ceva ce nu a comandat nimeni).
- **I-11** Regula carantinei: din cantitatea primită pe o linie, partea acoperită de comandă intră în stocul disponibil; **partea neacoperită** (surplus sau marfă necomandată) intră în carantină și deschide o discrepanță pentru Achiziții.
- **I-12** O discrepanță se rezolvă de Achiziții în unul din două moduri:
  - **Atașare la o linie de comandă** (existentă sau adăugată special – „regularizare”): marfa intră în stocul disponibil și contează ca recepționată pe acea linie;
  - **Retur la furnizor**: marfa iese din carantină și nu intră niciodată în stoc.
- **I-13** O recepție confirmată nu se mai modifică. Greșelile se corectează prin documente noi (ajustare de inventar, retur), vizibile în audit.
- **I-14** Ieșirile de stoc sunt de trei tipuri: **consum** (marfa pleacă în producție/vânzare), **retur la furnizor** (marfă deja intrată în stoc, de ex. defectă) și **ajustare de inventar** (plus sau minus, la numărare). Stocul disponibil **nu poate deveni negativ**.
- **I-15** Un retur la furnizor legat de o linie de comandă **scade cantitatea recepționată netă** a liniei. Asta contează la potrivirea facturilor.
- **I-16** Nu se calculează valoarea stocului (FIFO, CMP): aplicația urmărește cantități. Valoarea stocului e o extensie posibilă.

## Facturi

- **I-17** Moneda facturii = moneda comenzii. O factură în altă monedă decât comanda e blocată la potrivire.
- **I-18** O comandă poate fi facturată în mai multe facturi (facturare parțială). O factură poate acoperi mai multe comenzi ale aceluiași furnizor.
- **I-19** Contabilitatea introduce manual factura (antet + linii + totalurile de pe documentul fizic). Totalurile declarate sunt comparate cu cele calculate, ca să prindem greșelile de pe factură sau de la introducere.
- **I-20** TVA se aplică pe linie. Cota implicită este **21%** (cota standard în România din 1 august 2025), modificabilă pe produs și pe linie (de ex. 11%).
- **I-21** Aceeași combinație **furnizor + număr factură** nu poate exista de două ori (protecție la dublă plată).
- **I-22** Toleranța de preț la potrivire este implicit **0%** (prețul facturat trebuie să fie exact prețul din comandă) și se poate configura. Toleranța la cantitate este 0. La totaluri se acceptă o diferență de rotunjire de **0,05** în moneda facturii.
- **I-23** O factură blocată poate fi **forțată la plată** de Contabilitate, doar cu justificare obligatorie, păstrată în audit. Situațiile reale o cer (de ex. un acord telefonic cu furnizorul).

## Curs valutar

- **I-24** Sursa este **Banca Națională a României** (fluxul XML public). Cursul se salvează pe factură în momentul validării și nu se mai schimbă ulterior.
- **I-25** Se folosește cursul BNR cu data = data facturii. Dacă BNR nu a publicat curs în acea zi (weekend, sărbătoare legală), se folosește **ultimul curs publicat anterior**. Se rețin atât valoarea cursului, cât și data lui efectivă.
- **I-26** Dacă data facturii este **azi** și BNR încă nu a publicat cursul zilei (BNR publică în jurul orei 13:00), factura rămâne în *Curs în așteptare* și este finalizată automat după publicare. Altfel s-ar folosi un curs care se schimbă după câteva ore. O zi lucrătoare e considerată **fără publicare** (sărbătoare legală) abia dacă BNR, interogat cu succes **după ora 14:00**, tot nu are curs pentru ea; ora de marjă acoperă publicările întârziate. Sâmbăta și duminica sunt zile fără publicare de la sine.
- **I-27** Nu se acceptă facturi cu dată în viitor.
- **I-28** Dacă BNR nu răspunde (rețea, mentenanță), factura rămâne în *Curs în așteptare*, iar un job reîncearcă periodic. Nicio factură nu primește un curs inventat sau implicit. Nici un curs „prea vechi”: dacă ultimul curs salvat e cu peste 7 zile înaintea datei facturii (cea mai lungă pauză reală a BNR e de ~5 zile, la sărbătorile de iarnă), înseamnă că lipsește istoricul, iar factura așteaptă încărcarea lui.

> Notă: în practica fiscală românească există și interpretarea „cursul comunicat de BNR în ziua anterioară”. Cerința spune explicit **„cursul din ziua facturii”**, așa că am urmat-o. Regula e izolată într-o singură funcție, deci poate fi schimbată ușor.

## Notificări

- **I-29** Notificările se trimit ca **un singur rezumat zilnic pe persoană** (zile lucrătoare, ora configurabilă, implicit 08:00), nu câte un email pe problemă. Altfel oamenii încep să le ignore.
- **I-30** Rezumatul conține **toate problemele încă deschise** care privesc persoana, nu doar pe cele noi: o problemă nerezolvată trebuie reamintită. Problemele apărute de la rezumatul anterior sunt marcate **NOU**.
- **I-31** Dacă o persoană nu are nimic de rezolvat, nu primește email.

## În afara proiectului (consemnate deliberat)

- Integrarea cu **e-Factura (ANAF SPV)** pentru preluarea automată a facturilor.
- Efectuarea plăților (integrare bancară).
- Valoarea stocului (FIFO / CMP) și contabilitatea de gestiune.
- Trimiterea automată a comenzilor către furnizori și confirmările lor.
- Mai multe depozite, mai multe firme.
