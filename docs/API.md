# API-Übersicht (v0.1.0)

Basis-URL im Container: `http://host:8080`

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/health` | Status, `env`, `version` |
| `GET` | `/api/health` | Alias |
| `GET` | `/api/version` | `version` + `repository` |
| `GET` | `/api/sync/status` | Ghostfolio-Sync-Stand |
| `POST` | `/api/sync/ghostfolio` | Sync + FIFO + Metrics |
| `POST` | `/api/fifo/rebuild` | FIFO neu berechnen |
| `GET` | `/api/lots` | Offene Lots (`?isin=`) |
| `POST` | `/api/simulate/sell` | What-If Verkauf |
| `GET` | `/api/metrics/overview` | Dashboard-Kennzahlen |
| `GET` | `/api/metrics/periods` | Perioden + CAGR |
| `GET` | `/api/metrics/nav` | NAV-Serie (`?start=&end=`) |
| `POST` | `/api/metrics/rebuild` | `metrics_daily` neu |
| `GET` | `/api/positions` | Einfache Positionsrendite |
| `GET` | `/api/staging` | Paperless-Review-Queue |
| `POST` | `/api/staging/sync` | Paperless → Staging |
| `POST` | `/api/staging/{id}/confirm` | Import nach Ghostfolio |
| `POST` | `/api/staging/{id}/reject` | Staging ablehnen |
| `POST` | `/api/webhooks/paperless` | Paperless Auto-Ingest (Shared Secret) |
| `GET` | `/api/settings/paperless` | Paperless-Mapping / Tag / GF-Defaults |
| `PUT` | `/api/settings/paperless` | Settings speichern |
| `GET` | `/api/settings/paperless/custom-fields` | Custom Fields aus Paperless |
| `POST` | `/api/settings/paperless/test` | Paperless-Verbindungstest |

OpenAPI: `/docs` (FastAPI Swagger), wenn nicht abgeschaltet.
