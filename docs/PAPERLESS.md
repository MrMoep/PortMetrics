# Paperless-Integration

Paperless NGX ist **Belegarchiv + Staging**, nicht das Ledger. Extrahierte Felder landen in `staging_imports`, werden geprüft und erst dann nach Ghostfolio importiert.

## Custom Fields (einmalig in Paperless anlegen)

| Name | Typ (Empfehlung) | Pflicht | Beschreibung |
|------|------------------|---------|--------------|
| `wp_typ` | Text / Select | ja | `BUY`, `SELL`, `DIVIDEND`, `FEE`, `INTEREST` |
| `isin` | Text | ja* | ISIN |
| `symbol` | Text | nein | Ghostfolio-Symbol; Fallback = ISIN |
| `stueckzahl` | Float / Text | ja | Stückzahl |
| `kurs` | Float / Text | ja | Kurs pro Stück |
| `gebuehr` | Float / Text | nein | Gebühr (Default 0) |
| `handelsdatum` | Date / Text | ja | `YYYY-MM-DD` |
| `waehrung` | Text | nein | Default `EUR` |
| `gf_import_status` | Text | nein | `pending` → `imported` / `rejected` |
| `gf_activity_id` | Text | nein | UUID nach erfolgreichem Import |

\* Mindestens `isin` **oder** `symbol` muss gesetzt sein.

Optional: Tag (Env `PAPERLESS_TAG`) filtern, z. B. nur Dokumente mit Tag `wertpapier`.

## Workflow

```
PDF → P-GPT / manuelle Felder → POST /api/staging/sync
  → Review in Dashboard (Tab Staging)
  → Confirm → Ghostfolio POST /api/v1/import
  → gf_import_status=imported + document_links
  → Sync Ghostfolio → FIFO
```

## API

| Methode | Pfad | Zweck |
|---------|------|-------|
| `GET` | `/api/staging?status=pending` | Review-Queue |
| `POST` | `/api/staging/sync` | Paperless → Staging |
| `POST` | `/api/staging/{id}/confirm` | Import nach Ghostfolio |
| `POST` | `/api/staging/{id}/reject` | Ablehnen |

## Env

```env
PAPERLESS_URL=http://paperless:8000
PAPERLESS_TOKEN=
PAPERLESS_TAG=
GHOSTFOLIO_DEFAULT_ACCOUNT_ID=
GHOSTFOLIO_DATA_SOURCE=YAHOO
```
