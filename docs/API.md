# API-Übersicht (v0.2.0)

Basis-URL im Container: `http://host:8080`

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/health` | Status, `env`, `version` |
| `GET` | `/api/health` | Alias |
| `GET` | `/api/version` | `version` + `repository` |
| `GET` | `/api/sync/status` | Ghostfolio-Sync-Stand |
| `POST` | `/api/sync/ghostfolio` | Sync + Orphan-Prune + FIFO + Metrics (`deleted`, `prune_skipped` in Response) |
| `POST` | `/api/fifo/rebuild` | FIFO neu berechnen |
| `GET` | `/api/lots` | Offene Lots (`?isin=`) |
| `POST` | `/api/simulate/sell` | What-If Verkauf |
| `GET` | `/api/metrics/overview` | Dashboard-Kennzahlen inkl. Perioden + Jahres-Renditen |
| `GET` | `/api/metrics/periods` | Perioden + CAGR |
| `GET` | `/api/metrics/nav` | NAV-Serie (`?start=&end=`) |
| `POST` | `/api/metrics/rebuild` | `metrics_daily` neu |
| `GET` | `/api/positions` | Einfache Positionsrendite |
| `GET` | `/api/staging` | Paperless-Review-Queue |
| `POST` | `/api/staging/sync` | Paperless → Staging (`skip_reasons` bei skips) |
| `POST` | `/api/staging/{id}/confirm` | Import nach Ghostfolio + stiller Mirror (best-effort) |
| `POST` | `/api/staging/{id}/reject` | Staging ablehnen |
| `POST` | `/api/webhooks/paperless` | Paperless Auto-Ingest (Shared Secret) |
| `GET`/`PUT` | `/api/settings/assets` | Kennungs-Tabelle ISIN/WKN/preferred_symbol/display_name |
| `POST` | `/api/settings/assets/apply-suggestion` | Historien-Vorschlag in Tabelle übernehmen |
| `GET`/`PUT` | `/api/settings/paperless` | Paperless-Mapping / Tag / GF-Defaults |
| `GET` | `/api/settings/paperless/custom-fields` | Custom Fields aus Paperless |
| `POST` | `/api/settings/paperless/test` | Paperless-Verbindungstest |

OpenAPI: `/docs` (FastAPI Swagger), wenn nicht abgeschaltet.
