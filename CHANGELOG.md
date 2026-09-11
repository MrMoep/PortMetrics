# Changelog

## [Unreleased]

### Features
- Kennungs-Tabelle ISIN/WKN/preferred Symbol (Einstellungen → Assets); Paperless-Confirm blockiert ohne Mapping; Historien-Vorschlag + Staging-Deep-Link (#57)
- Ghostfolio-Sync **Orphan-Prune**: lokal fehlende GF-Activities werden entfernt; Staging `imported` → `pending`; Statuszeile zeigt gelöschte Anzahl
- Optional `display_name` in Kennungs-Tabelle; Anzeige-Präferenz `name` (Fallback Symbol), Default bleibt `symbol`
- Nach Staging-**Confirm** läuft automatisch ein stiller Ghostfolio-Mirror (Activities → Preise → FIFO → Metrics), damit Lots/Overview ohne manuellen Sync aktuell sind
- Belege-Verknüpfen: unverknüpfte FIFO-Lots → gefilterte Paperless-Docs; Scope-Preview (Count/Warnung) auch für Full Sync; Staging wird bei Match auf `imported` gesetzt
- FIFO-Lots: Strich in Beleg-Spalte öffnet Maske für manuelle Doc-ID/URL-Verknüpfung

### Fixed
- Assets-Tabelle nutzt volle Panel-Breite; Staging→Tabelle übernimmt ISIN/WKN (und Symbol-Vorschlag) in den Entwurf
- Anzeige-Kennung (Name/WKN/ISIN) löst auch über Preferred Symbol auf, wenn Ghostfolio-Activities keine ISIN haben
- Lots/Positionen: Spaltenkopf fest „Asset“ (unabhängig von der Anzeige-Präferenz)
- Paperless-Sync: Skip-Gründe aggregiert (Log + Statuszeile); Select-Feld `Typ` und WKN-only Docs werden akzeptiert
- Paperless Select-`Typ`: Option-IDs (`SXXG…`) werden über Custom-Field-Definition auf Labels (`BUY`/…) gemappt

### Changed
- Paperless-Mapping vereinfacht: Pflicht/Optional in der UI; Rollen `type`, `isin`, `wkn`, `quantity`, `unit_price`, `fee`
- Handelsdatum = Paperless-Dokumentdatum; Währung aus Monetary-Feldern; Ghostfolio-Import-Symbol = preferred_symbol (nicht roh ISIN)
- Typ `OTHER` im Staging sichtbar, Confirm gesperrt; kein Paperless-Write-back für Import-Status/Activity-ID
- Price-Sync nutzt preferred_symbol aus der Kennungs-Tabelle, wenn gesetzt

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
