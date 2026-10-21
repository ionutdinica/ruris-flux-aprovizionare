# 07 · Ghid de demonstrație

Un scenariu de ~10–15 minute pentru prezentarea aplicației, plus întrebările probabile și
răspunsurile lor. Numerele documentelor (CMD-…, FAC-…) depind de ziua în care au fost
generate datele demo, de aceea documentele sunt descrise mai jos după furnizor și situație.

## Pregătire (înainte de prezentare)

```bash
docker compose up --build
```

- Aplicația: http://localhost:8000 · emailurile trimise: http://localhost:8025 (Mailpit)
- Parola pentru toate conturile: `demo-ruris`
- Pentru o prezentare curată, pornește de la zero (date demo proaspete, relative la ziua de azi):
  `docker compose down -v` și apoi din nou `docker compose up --build`

| Cont | Rol | Ce arăți cu el |
|---|---|---|
| `maria.pop` | Achiziții | comenzi, carantină, punctualitatea furnizorilor |
| `ion.marin` | Depozit | livrări așteptate, recepție, stoc (fără prețuri) |
| `elena.dobre` | Contabilitate | facturi, potrivirea în 3 direcții, cursul BNR |
| `andrei.ionescu` | Administrator | starea sistemului, jurnalul de audit, emailurile |

Sfat: deschide fiecare rol într-o fereastră de browser separată (sau o fereastră privată),
ca să treci de la un om la altul fără deconectare.

## 1. Problema (30 de secunde)

> „Achizițiile, Depozitul și Contabilitatea lucrau în Excel-uri separate și pe email. Nimeni
> nu vedea complet ce s-a comandat, ce a sosit și ce s-a facturat, iar problemele (marfă
> întârziată, facturi greșite) se descopereau târziu. Aplicația pune cele trei echipe pe
> aceleași date: fiecare vede ce îl privește, iar aplicația îi spune singură ce e de rezolvat.”

## 2. Turul pe roluri

### Maria, Achiziții (~3 min)

1. **Panoul**: cifrele-cheie și lista „De rezolvat” (comanda întârziată de la Motoare Industriale, marfa în carantină, factura blocată pe comanda ei). *„Aceeași listă îi vine și pe email, dimineața.”*
2. Graficul **Livrări la timp, pe furnizor**: Motoare Industriale e cel mai puțin punctual. *„Un argument concret la următoarea negociere.”*
3. **Comenzi**: căutare fără diacritice, comenzile întârziate evidențiate, **Export Excel** cu filtrele curente (și **Import Excel**, cu previzualizare și validare completă).
4. **Discrepanțe** → marfa necomandată (mânere de la Plastic Injecție Dolj): Maria decide, o atașează la o comandă sau o returnează. *„Depozitul nu decide asta: el doar numără.”*
5. **Bugete**: plafonul anual pe furnizor. Plastic Injecție Dolj e consumat ~94% (alertă), Componente Electrice Banat e **depășit**: ultima comandă a plecat peste buget, cu justificarea vizibilă pe comandă. Creează o ciornă la Plastic Injecție Dolj (de ex. 20 × PLA-C1): pe pagina comenzii se vede efectul asupra bugetului, iar la *Trimite comanda* se cere justificarea. *„Nu blocăm producția, dar nicio depășire nu trece neobservată.”*

### Ion, Depozit (~2 min)

1. **Panoul**: livrările de azi și din următoarele 14 zile; nicio sumă de bani pe pagină.
2. **Recepții → Livrări așteptate** → comanda întârziată de la **Motoare Industriale** (filtrele de aer lipsă). Deschide-o, dar **încă nu recepționa**: o folosim la momentul cheie de mai jos.
3. **Stoc**: un produs → registrul de mișcări, cu soldul după fiecare mișcare (ca un extras de cont).

### Elena, Contabilitate (~4 min)

1. **Facturi → De rezolvat** → factura de la **Motoare Industriale, blocată**. Ecranul de potrivire: pe fiecare linie *comandat · recepționat · facturat*; rândul cu probleme e roșu: *„facturat 40 buc, recepționat doar 25: 15 buc nesosite”*.
2. **Momentul cheie** (factura se deblochează singură):
   - în fereastra lui **Ion**: *Recepționează* comanda Motoare Industriale, 15 filtre FIL-A20, *Confirmă*;
   - în fereastra **Elenei**: reîncarcă factura, care e acum **Potrivită**. În istoric: *„a devenit automat Potrivită după o modificare pe comanda …”*.
   - *„Contabila nu a făcut nimic: factura s-a deblocat în momentul în care a sosit marfa.”*
   - Variantă de rezervă, pornită de la zero (dacă situația din datele demo a fost deja
     folosită): ciclul complet din [README](../README.md#încearcă-un-ciclu-complet-10-minute),
     cu o comandă nouă, cele patru roluri și aceleași cifre oricând.
3. **Aprobă la plată** → **Marchează plătită**.
4. Factura **blocată pentru preț diferit** (Vopsele Industriale Craiova): *„preț 39,50 față de 38,00 în comandă (+3,9%)”*.
5. Factura **în EUR emisă sâmbăta** (Hydraulik Teile): *„se aplică cursul BNR de vineri, explicat pe factură”*. Arată și **Cursuri BNR** → „Ce curs se aplică unei facturi din data…” cu o sâmbătă.
6. Factura **forțată la plată** (Trasmissioni Italia): rămâne marcată, cu justificarea vizibilă pentru oricine.

### Andrei, Administrator (~2 min)

1. **Panoul**: **Starea sistemului** (cursul BNR, rezumatul zilnic, emailuri eșuate, echipe fără utilizatori activi) și problemele întregii firme.
2. **Administrare → Jurnal de activitate**: cine, ce, când; filtre pe utilizator și tip; modificările câmp cu câmp.
3. **Notificări trimise** → **Trimite acum** → în Mailpit (http://localhost:8025) apar rezumatele fiecărui om, doar cu problemele lui, cu marcajul **NOU**.

## 3. Arhitectura în 2 minute (dacă e întrebată)

Vezi [06-arhitectura.md](06-arhitectura.md). Ideile principale:
- regulile de business în servicii, separate de pagini; motorul de potrivire doar citește;
- registru de stoc nemodificabil: stocul și „recepționatul” nu se pot contrazice;
- semnale între module: recepția deblochează facturile fără ca depozitul să depindă de facturi;
- ~1.000 de teste, CI pe GitHub, PostgreSQL peste tot.

## 4. Întrebări probabile

**Cum sunt separate drepturile echipelor?**
O matrice de permisiuni în cod ([04-permisiuni.md](04-permisiuni.md)), verificată pe server la fiecare cerere. Un test parcurge automat fiecare pagină pentru fiecare rol; altul compară codul cu documentația. Depozitul nu vede prețuri, nici în istoricul documentelor.

**Cum funcționează potrivirea facturilor?**
Pentru fiecare linie: facturat ≤ recepționat, facturat ≤ comandat, preț = prețul din comandă (cu toleranță configurabilă), totalurile declarate = cele calculate (±0,05). Se raportează toate motivele deodată. Reverificarea e automată la recepții, retururi, modificări de comandă ([05-reguli-business.md](05-reguli-business.md), §1).

**Ce se întâmplă dacă aceeași marfă e facturată de două ori?**
A doua factură e blocată: „facturat” include facturile anterioare. Regula „primul venit, primul servit” garantează că două facturi nu pot fi potrivite simultan pe aceeași marfă, iar liniile de comandă sunt blocate în baza de date pe durata verificării (două validări în aceeași secundă nu trec amândouă).

**Ce curs se aplică pentru o factură de sâmbătă? Dar pentru una de azi, la ora 10?**
Sâmbăta: cursul de vineri (BNR nu publică în weekend și de sărbători). Azi, înainte de publicarea BNR (~13:00): factura rămâne „Curs în așteptare” și se finalizează singură după publicare. Dacă BNR nu răspunde, factura așteaptă; nu primește niciodată un curs inventat (I-25…I-28).

**Cum v-ați asigurat că emailurile nu devin spam intern?**
Un singur rezumat pe zi, pe persoană, doar cu problemele care o privesc; cine nu are nimic nu primește nimic; problemele noi sunt marcate NOU. Un email eșuat se reîncearcă de cel mult 3 ori pe zi; o eroare nu îi oprește pe ceilalți.

**Cum știți cine a făcut ce?**
Jurnal de audit dublu: modificările de câmpuri (automat) și evenimentele de business (trimitere, recepție, forțare cu justificare). Jurnalul nu se poate modifica sau șterge din aplicație.

**Cum ați testat?**
~1.000 de teste pe PostgreSQL (acoperire 97%), un test cap-coadă prin pagini cu trei oameni, CI la fiecare commit. Testele însele au fost verificate: regulile importante au fost stricate deliberat, iar testele trebuiau să pice.

**De ce Django și nu un frontend separat (React etc.)?**
E o aplicație internă cu formulare, tabele și reguli. Paginile randate pe server, cu HTMX pentru interactivitate, înseamnă un singur limbaj și o singură aplicație de întreținut, potrivit pentru o echipă mică.

**Cum ar rula în producție la RURIS?**
Aceeași imagine Docker, pe un server intern: PostgreSQL cu backup, HTTPS, serverul de email al firmei în `EMAIL_URL` (cu SPF/DKIM), planificatorul ca serviciu separat. Configurația se face doar prin variabile de mediu.

**Ce ați face mai departe?**
Vezi secțiunea din [README](../README.md#ce-aș-face-mai-departe): e-Factura ANAF, plăți, evaluarea stocului (FIFO/CMP), comenzi trimise automat furnizorilor, autentificare cu conturile firmei.
