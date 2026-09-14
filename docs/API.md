# API-Übersicht (v0.2.0)

Basis-URL im Container: `http://host:8080`

| Methode | Pfad | Beschreibung |
|---------|------|--------------|
| `GET` | `/health` | Status, `env`, `version` |
| `GET` | `/api/health` | Alias |
| `GET` | `/api/version` | `version` + `repository` |
| `GET` | `/api/sync/status` | Ghostfolio-Sync-Stand (Activities, Prices, Accounts) |
| `POST` | `/api/sync/ghostfolio` | Sync Accounts + Activities + Orphan-Prune + FIFO + Metrics |
| `GET` | `/api/accounts` | Gespiegelte Ghostfolio-Konten (Depots) |
| `GET`/`POST`/`DELETE` | `/api/transfers` | Interne Depotüberträge (FIFO-Lot-Migration ohne realisierten Gewinn) |
| `POST` | `/api/fifo/rebuild` | FIFO neu berechnen |
| `GET` | `/api/lots` | Offene Lots (`?isin=` / `?account_id=`) |
| `POST` | `/api/simulate/sell` | What-If Verkauf (`account_id` bei multi-Depot nötig) |
| `GET` | `/api/metrics/overview` | Dashboard-Kennzahlen inkl. Perioden + Jahres-Renditen (`?account_id=` für Depot-Scope; Freibetrag immer gesamt) |
| `GET` | `/api/metrics/periods` | Perioden + CAGR |
| `GET` | `/api/metrics/nav` | NAV-Serie (`?start=&end=`) |
| `POST` | `/api/metrics/rebuild` | `metrics_daily` neu |
| `GET` | `/api/positions` | Einfache Positionsrendite (`?isin=` / `?account_id=`) |
| `GET` | `/api/staging` | Paperless-Review-Queue |
| `POST` | `/api/staging/sync` | Paperless → Staging (`skip_reasons` bei skips) |
| `POST` | `/api/staging/match-activities` | Unverknüpfte Lots → Paperless-Docs |
| `GET` | `/api/paperless/link-preview` | Scope-Preview (Doc-Count, unverknüpfte Lots) |
| `POST` | `/api/lots/{id}/link-document` | Manuell Beleg (ID/URL) an Lot |
| `POST` | `/api/staging/{id}/confirm` | Import nach Ghostfolio + stiller Mirror (best-effort) |
| `POST` | `/api/staging/{id}/reject` | Staging ablehnen |
| `POST` | `/api/webhooks/paperless` | Paperless Auto-Ingest (Shared Secret) |
| `GET`/`PUT` | `/api/settings/portfolio` | Steuer-Freibetrag, Risikofrei-Zins, Anzeige-Kennung |
| `GET`/`PUT` | `/api/settings/overview` | Overview-KPI-Layout (`kpi_ids`, `hero_id`) |
| `GET`/`PUT` | `/api/settings/assets` | Kennungs-Tabelle ISIN/WKN/preferred_symbol/display_name |
| `POST` | `/api/settings/assets/apply-suggestion` | Historien-Vorschlag in Tabelle übernehmen |
| `GET`/`PUT` | `/api/settings/paperless` | Paperless-Mapping / Tag / GF-Defaults |
| `GET` | `/api/settings/paperless/custom-fields` | Custom Fields aus Paperless |
| `POST` | `/api/settings/paperless/test` | Paperless-Verbindungstest |

OpenAPI: `/docs` (FastAPI Swagger), wenn nicht abgeschaltet.
