# Paperless-Integration

Paperless NGX ist **Belegarchiv + Staging**, nicht das Ledger. Extrahierte Felder landen in `staging_imports`, werden geprüft und erst dann nach Ghostfolio importiert.

Teil von **PortMetrics 0.2.0**. Verwandt: [API.md](API.md), [DATA_MODEL.md](DATA_MODEL.md).

## Custom Fields

Felder werden **in Paperless** angelegt (beliebige Namen). In PortMetrics unter **Einstellungen** den Rollen zuordnen (gespeicherte Feld-**IDs**).

| Rolle | Pflicht | Beschreibung |
|-------|---------|--------------|
| `type` | ja | `BUY`, `SELL`, `DIVIDEND`, `FEE`, `INTEREST` |
| `isin` | ja* | ISIN |
| `symbol` | nein | Ghostfolio-Symbol; Fallback = ISIN |
| `quantity` | ja | Stückzahl |
| `unit_price` | ja | Kurs pro Stück |
| `fee` | nein | Gebühr (Default 0) |
| `trade_date` | ja | `YYYY-MM-DD` |
| `currency` | nein | Default `EUR` |
| `import_status` | nein | `pending` → `imported` |
| `activity_id` | nein | UUID nach erfolgreichem Import |

\* Mindestens `isin` **oder** `symbol` muss gemappt und gesetzt sein.

Ohne gespeichertes Mapping fällt PortMetrics auf die Legacy-Namen zurück (`wp_typ`, `isin`, `stueckzahl`, `kurs`, `gebuehr`, `handelsdatum`, `waehrung`, `gf_import_status`, `gf_activity_id`).

Optional: Tag in den Einstellungen (oder Env `PAPERLESS_TAG`) — nur Dokumente mit diesem Tag.

## Workflow

```
PDF → P-GPT / Felder
  → Webhook (document updated) oder Sync/Scheduler
  → staging_imports
  → Review (Confirm/Reject) im Dashboard
  → Ghostfolio Import → document_links
  → Sync Ghostfolio → FIFO
```

### Webhook (empfohlen)

1. `PAPERLESS_WEBHOOK_SECRET` in PortMetrics setzen.
2. In Paperless einen Workflow anlegen:
   - Trigger: **Document updated** (nicht nur added — Custom Fields oft erst später)
   - Filter: optional Tag (z. B. `wertpapier`)
   - Action: Webhook `POST` auf `https://<portmetrics>/api/webhooks/paperless`
   - Header: `X-PortMetrics-Secret: <secret>` (oder Query `?secret=`)
   - Body JSON z. B. `{ "doc_url": "{doc_url}" }` oder `{ "document_id": "<id>" }`
3. Confirm/Reject weiterhin nur im Staging-Tab.

Unvollständige Felder werden übersprungen (`action=skipped`); manueller Sync bleibt als Fallback.

### Scheduler (optional Catch-up)

`PAPERLESS_SYNC_INTERVAL_MINUTES>0` aktiviert einen periodischen Full-Pull (Hybrid zu Webhook). `0` = aus.

## API

| Methode | Pfad | Zweck |
|---------|------|-------|
| `GET` | `/api/staging?status=pending` | Review-Queue |
| `POST` | `/api/staging/sync` | Paperless → Staging (manuell) |
| `POST` | `/api/webhooks/paperless` | Auto-Ingest eines Docs |
| `POST` | `/api/staging/{id}/confirm` | Import nach Ghostfolio |
| `POST` | `/api/staging/{id}/reject` | Ablehnen |
| `GET` | `/api/settings/paperless` | Mapping + Tag + GF-Defaults |
| `PUT` | `/api/settings/paperless` | Mapping speichern |
| `GET` | `/api/settings/paperless/custom-fields` | Felder aus Paperless |
| `POST` | `/api/settings/paperless/test` | Verbindungstest |

## Env

```env
PAPERLESS_URL=http://paperless:8000
PAPERLESS_TOKEN=
PAPERLESS_TAG=
PAPERLESS_WEBHOOK_SECRET=
PAPERLESS_SYNC_INTERVAL_MINUTES=0
GHOSTFOLIO_DEFAULT_ACCOUNT_ID=
GHOSTFOLIO_DATA_SOURCE=YAHOO
```

`PAPERLESS_URL` / `PAPERLESS_TOKEN` / `PAPERLESS_WEBHOOK_SECRET` bleiben Env. Tag, Field-Map und Ghostfolio-Defaults können in der UI überschrieben und in `app_settings` persistiert werden.
