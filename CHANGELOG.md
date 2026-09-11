# Changelog

## [Unreleased]

### Features
- Ghostfolio-Sync **Orphan-Prune**: lokal fehlende GF-Activities werden entfernt; Staging `imported` → `pending`; Statuszeile zeigt gelöschte Anzahl

### Changed
- Paperless-Mapping vereinfacht: Pflicht/Optional in der UI; Rollen `type`, `isin`, `wkn`, `quantity`, `unit_price`, `fee`
- Handelsdatum = Paperless-Dokumentdatum; Währung aus Monetary-Feldern; Symbol = ISIN
- Typ `OTHER` im Staging sichtbar, Confirm gesperrt; kein Paperless-Write-back für Import-Status/Activity-ID

## [0.2.0] — 2026-09-09

Paperless-UX und Homelab-Feinschliff über 0.1.0.

### Features
- Paperless Custom-Field-**Mapping** in der UI (Rollen → Feld-IDs in `app_settings`)
- Einstellungen-Tab: Tag, Ghostfolio-Account/Data-Source, Verbindungstest
- Paperless-**Webhook** (`POST /api/webhooks/paperless`) mit Shared Secret für Auto-Ingest
- Optionaler Paperless-**Scheduler**-Pull (`PAPERLESS_SYNC_INTERVAL_MINUTES`)
- CORS_ORIGINS für Reverse-Proxy-URLs

### Deployment
- Image: `ghcr.io/mrmoep/portmetrics:0.2.0` (auch `:latest` auf `main`)
- Migration `0002_app_settings` erforderlich (`alembic upgrade head`)
- Neue Env: `PAPERLESS_WEBHOOK_SECRET`, `PAPERLESS_SYNC_INTERVAL_MINUTES`, `CORS_ORIGINS`

### Hinweis
Steuerwerte sind **Schätzungen**, keine Steuerberatung.

## [0.1.0] — 2026-09-09

Erstes öffentliches Release (v1-Kern).

### Features
- Ghostfolio-Sync nach PostgreSQL (`activities`, `sync_state`)
- FIFO-Lots, Consumptions, Verkaufs-Simulator inkl. Steuer-Schätzung
- Perioden-Metriken (30T, MTD, YTD, …), CAGR, NAV-Serie, Positionen
- Paperless-Staging: Sync → Review → Ghostfolio-Import → `document_links`
- Dashboard SPA (Overview, Lots, Positionen, Staging, Simulator)
- Single Container: FastAPI + SPA + APScheduler (Sync/FIFO/Metrics)
- Health-/Version-Endpoint; Version-Link im Dashboard zum GitHub-Repo

### Deployment
- Image: `ghcr.io/mrmoep/portmetrics:0.1.0` (auch `:latest` auf `main`)
- PostgreSQL extern (`portmetrics` / `portmetrics_test`)

### Hinweis
Steuerwerte sind **Schätzungen**, keine Steuerberatung.
