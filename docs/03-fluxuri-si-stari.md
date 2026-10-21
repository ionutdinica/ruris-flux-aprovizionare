# 03 · Fluxuri și stări

## Fluxul general

```mermaid
flowchart LR
    subgraph ACH[Achiziții]
        A1[Creează comanda] --> A2[Trimite comanda]
        A5[Rezolvă discrepanța]
    end
    subgraph DEP[Depozit]
        D1[Recepționează livrarea] --> D2{Totul e acoperit<br/>de comandă?}
        D2 -- da --> D3[Intră în stoc]
        D2 -- nu --> D4[Partea în plus intră<br/>în carantină]
    end
    subgraph CON[Contabilitate]
        C1[Înregistrează factura] --> C2[Curs BNR automat]
        C2 --> C3{Potrivire<br/>comandă–recepție–factură}
        C3 -- ok --> C4[Aprobată la plată] --> C5[Plătită]
        C3 -- diferențe --> C6[Blocată]
        C6 -- forțare cu justificare --> C4
    end

    A2 --> D1
    D4 --> A5
    A5 -- atașare la comandă --> D3
    D3 -. recepție nouă: reverificare .-> C3
    A2 -. comandă referită .-> C1
```

Linia punctată de la recepție la potrivire este esențială: o factură blocată pentru că marfa „nu a sosit încă” se **deblochează singură** în momentul în care Depozitul confirmă recepția.

## Comanda (`PurchaseOrder.status`)

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> SENT: Trimite
    DRAFT --> CANCELLED: Anulează
    SENT --> PARTIALLY_RECEIVED: recepție parțială (automat)
    SENT --> RECEIVED: recepție completă (automat)
    PARTIALLY_RECEIVED --> RECEIVED: restul recepționat (automat)
    SENT --> CANCELLED: Anulează (nimic recepționat)
    PARTIALLY_RECEIVED --> CLOSED: Închide cu rest nelivrat (motiv obligatoriu)
    RECEIVED --> PARTIALLY_RECEIVED: retur / linie nouă (automat)
    CANCELLED --> [*]
    CLOSED --> [*]
```

| Status | Etichetă | Se poate edita | Poate fi întârziată |
|---|---|---|---|
| `DRAFT` | Ciornă | tot | nu |
| `SENT` | Trimisă | data estimată, linii noi, cantități mai mari | da |
| `PARTIALLY_RECEIVED` | Parțial recepționată | idem | da |
| `RECEIVED` | Recepționată | linii noi, cantități mai mari (regularizarea unui surplus) | nu |
| `CLOSED` | Închisă | nu | nu |
| `CANCELLED` | Anulată | nu | nu |

Tranzițiile automate se recalculează după fiecare eveniment care schimbă cantitățile recepționate: confirmare de recepție, rezolvare de discrepanță, retur, linie adăugată.

## Recepția (`GoodsReceipt.status`)

```mermaid
stateDiagram-v2
    [*] --> DRAFT
    DRAFT --> CONFIRMED: Confirmă
    DRAFT --> [*]: Șterge ciorna
    CONFIRMED --> [*]
```

Numărul `REC-…` se dă la confirmare. La **confirmare**, într-o singură tranzacție:
1. pentru fiecare linie: `accepted = min(primit, rest de recepționat pe linia de comandă)`, `quarantined = primit − accepted`;
2. se creează mișcarea de stoc `RECEIPT` pentru `accepted`;
3. dacă `quarantined > 0`, se creează o `Discrepancy` (`OVER_DELIVERY` sau `UNORDERED`);
4. se recalculează statusul comenzii;
5. se reverifică facturile blocate legate de comanda respectivă.

## Discrepanța (`Discrepancy.status`)

```mermaid
stateDiagram-v2
    [*] --> OPEN: recepție cu marfă neacoperită
    OPEN --> RESOLVED: Atașează la linie de comandă<br/>(intră în stoc)
    OPEN --> RESOLVED: Retur la furnizor<br/>(nu intră în stoc)
    RESOLVED --> [*]
```

## Factura (`Invoice.status`)

```mermaid
stateDiagram-v2
    [*] --> REGISTERED: Înregistrare
    REGISTERED --> RATE_PENDING: Validează (curs indisponibil)
    REGISTERED --> MATCHED: Validează (potrivire ok)
    REGISTERED --> BLOCKED: Validează (diferențe)
    RATE_PENDING --> MATCHED: curs preluat + potrivire ok (automat)
    RATE_PENDING --> BLOCKED: curs preluat + diferențe (automat)
    BLOCKED --> MATCHED: reverificare ok (automat sau manual)
    BLOCKED --> REGISTERED: Corectează datele introduse
    BLOCKED --> APPROVED: Forțează (justificare obligatorie)
    MATCHED --> APPROVED: Aprobă la plată
    MATCHED --> BLOCKED: reverificare cu diferențe (ex. retur)
    APPROVED --> PAID: Marchează plătită
    REGISTERED --> REJECTED: Respinge
    RATE_PENDING --> REJECTED: Respinge
    RATE_PENDING --> REGISTERED: Corectează datele introduse
    BLOCKED --> REJECTED: Respinge (contestată)
    PAID --> [*]
    REJECTED --> [*]
```

| Status | Etichetă | Sens |
|---|---|---|
| `REGISTERED` | Înregistrată | introdusă, încă nevalidată; se poate edita |
| `RATE_PENDING` | Curs în așteptare | lipsește cursul BNR pentru data facturii |
| `MATCHED` | Potrivită | comandă, recepție și factură corespund |
| `BLOCKED` | Blocată | există cel puțin un motiv de blocare (vezi [05-reguli-business.md](05-reguli-business.md)) |
| `APPROVED` | Aprobată la plată | poate fi plătită |
| `PAID` | Plătită | final |
| `REJECTED` | Respinsă | contestată la furnizor; nu mai contează la cantitățile facturate |

Facturile `APPROVED` și `PAID` **nu se mai reverifică automat**: decizia de plată a fost luată și e consemnată.
