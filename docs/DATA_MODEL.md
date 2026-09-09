# Datenmodell

PostgreSQL-Schema: `portmetrics` (Stand Release **0.2.0**).

Migrationen: `api/alembic/versions/` — lokal/Prod mit `alembic upgrade head`.

## Entity-Relationship (konzeptionell)

```
activities (1) ──→ (n) lots
activities [SELL] (1) ──→ (n) lot_consumptions ──→ (n) lots
paperless doc (1) ──→ (0..1) staging_imports ──→ (0..1) activities
activities / lots (n) ←── (n) document_links ──→ paperless doc
```

## Kern-Tabellen

### `activities`

Gespiegelte Transaktionen aus Ghostfolio.

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
| `price_snapshots` | Tageskurse aus Ghostfolio (`GET /api/v1/symbol/:ds/:symbol?includeHistoricalData=…`); `isin`-Spalte = Asset-Key (ISIN oder Symbol, wie FIFO/NAV) |
| `metrics_daily` | Vorberechnete KPIs (nav, invested, mtd_return, ytd_return, …) |
| `document_links` | Paperless-Dokument ↔ Activity/Lot |
| `staging_imports` | Review-Queue vor Ghostfolio-Import |
| `app_settings` | UI-Settings (z. B. Paperless Field-Map) |
| `sync_state` | Idempotenz, last_sync_at, cursor |

## FIFO-Algorithmus

```
on BUY:
  create lot(open_qty=qty, cost_basis=qty*price + fee, status=OPEN)

on SELL:
  remaining = sell_qty
  for lot in lots.where(isin, status in OPEN|PARTIAL).order_by(open_date ASC):
    take = min(remaining, lot.open_qty)
    gain = take * sell_price - take * (lot.cost_basis / lot.original_qty)
    insert lot_consumption(...)
    lot.open_qty -= take
    lot.status = CLOSED if open_qty=0 else PARTIAL
    remaining -= take
  assert remaining == 0
```

## Edge Cases (v1: manuell)

Teil-Verkäufe, Stock Splits, Depotüberträge, Währungswechsel und Thesaurierer werden in v1 über manuelle Korrektur-Activities abgebildet. Automatische Erkennung ist Future-Scope.
