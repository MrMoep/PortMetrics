# Datenmodell

PostgreSQL-Schema: `portmetrics` (Stand Release **1.0.0**).

Migrationen: `api/alembic/versions/` — im Docker-Image beim Start automatisch (`alembic upgrade head`); lokal ohne Container ggf. manuell.

## Entity-Relationship (konzeptionell)

```
activities (1) ──→ (n) lots
activities [SELL] (1) ──→ (n) lot_consumptions ──→ (n) lots
paperless doc (1) ──→ (0..1) staging_imports ──→ (0..1) activities
activities / lots (n) ←── (n) document_links ──→ paperless doc
```

## Kern-Tabellen

### `activities`

Gespiegelte Transaktionen aus Ghostfolio. Der Sync upsertet und entfernt Orphans (Activities, deren `gf_activity_id` in Ghostfolio nicht mehr vorkommt).

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `id` | BIGSERIAL | PK |
| `gf_activity_id` | UUID | Unique Key aus Ghostfolio |
| `account_id` | TEXT | Depot/Konto |
| `isin` | TEXT | ISIN (nullable bei Crypto o.Ä.) |
| `symbol` | TEXT | Ghostfolio-Symbol |
| `type` | TEXT | BUY, SELL, DIVIDEND, FEE, INTEREST |
| `quantity` | NUMERIC(18,8) | Stückzahl |
| `unit_price` | NUMERIC(18,8) | Kurs pro Stück |
| `fee` | NUMERIC(18,8) | Gebühr |
| `currency` | CHAR(3) | z.B. EUR |
| `trade_date` | DATE | Handelsdatum |
| `synced_at` | TIMESTAMPTZ | Letzter Sync |

### `lots`

FIFO-Kauf-Pakete.

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `id` | BIGSERIAL | PK |
| `activity_id` | BIGINT | FK → activities (Kauf-Activity) |
| `account_id` | TEXT | Depot (denormalisiert vom Buy; FIFO-Scope) |
| `isin` | TEXT | Asset |
| `open_qty` | NUMERIC(18,8) | Restmenge |
| `original_qty` | NUMERIC(18,8) | Ursprüngliche Menge |
| `cost_basis` | NUMERIC(18,8) | Einstand inkl. anteiliger Gebühren |
| `open_date` | DATE | Kaufdatum |
| `status` | TEXT | OPEN, PARTIAL, CLOSED |
| `closed_at` | DATE | Optional |

### `lot_consumptions`

Verkauf → verbrauchte Lots.

| Spalte | Typ | Beschreibung |
|--------|-----|--------------|
| `sell_activity_id` | BIGINT | FK → activities (Verkauf) |
| `lot_id` | BIGINT | FK → lots |
| `qty_consumed` | NUMERIC(18,8) | Verbrauchte Menge |
| `proceeds` | NUMERIC(18,8) | Erlösanteil |
| `realized_gain` | NUMERIC(18,8) | Realisierter Gewinn/Verlust |

### Weitere Tabellen

| Tabelle | Zweck |
|---------|-------|
| `accounts` | Gespiegelte Ghostfolio-Konten (`GET /api/v1/account`): id, Name, Währung, Balance, Platform |
| `depot_transfers` | Interne Depotüberträge (nicht aus Ghostfolio); FIFO wandert Lots mit Einstand/Kaufdatum |
| `price_snapshots` | Tageskurse aus Ghostfolio (`GET /api/v1/symbol/:ds/:symbol?includeHistoricalData=…`); `isin`-Spalte = Asset-Key (ISIN oder Symbol, wie FIFO/NAV) |
| `metrics_daily` | Vorberechnete KPIs (nav, invested, mtd_return, ytd_return, …) |
| `document_links` | Paperless-Dokument ↔ Activity/Lot |
| `staging_imports` | Review-Queue vor Ghostfolio-Import |
| `asset_identifiers` | ISIN → WKN / preferred_symbol / display_name (Tabelle SoT; WKN gelernt wenn leer; Name nur manuell) |
| `app_settings` | UI-Settings (z. B. Paperless Field-Map, Anzeige-Kennung) |
| `sync_state` | Idempotenz, last_sync_at, cursor |

## FIFO-Algorithmus

FIFO ist **account-scoped**: Partition = `(account_id, asset_key)`.
Activities ohne `account_id` landen im Pseudo-Depot `__unassigned__`.

```
on BUY:
  create lot(account_id, open_qty=qty, cost_basis=qty*price + fee, status=OPEN)

on SELL:
  remaining = sell_qty
  for lot in lots.where(account_id, isin, status in OPEN|PARTIAL).order_by(open_date ASC):
    take = min(remaining, lot.open_qty)
    gain = take * sell_price - take * (lot.cost_basis / lot.original_qty)
    insert lot_consumption(...)
    lot.open_qty -= take
    lot.status = CLOSED if open_qty=0 else PARTIAL
    remaining -= take
  assert remaining == 0
```

Portfolio-KPIs (NAV, YTD, …) aggregieren weiterhin über alle Accounts; nur Lot-Verbrauch und Realisierung sind depotgetrennt.

## Edge Cases (v1: manuell)

Teil-Verkäufe, Stock Splits, Währungswechsel und Thesaurierer werden in v1 über manuelle Korrektur-Activities abgebildet. **Depotüberträge** laufen intern über `depot_transfers` (Lot-Migration mit Einstand und Kaufdatum, kein realisierter Gewinn) — nicht als Ghostfolio SELL+BUY.
