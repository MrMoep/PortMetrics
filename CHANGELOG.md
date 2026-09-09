# Changelog

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
