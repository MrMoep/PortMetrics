# Architektur

## Komponenten

| Komponente | Rolle |
|------------|-------|
| **Ghostfolio** | Kanonische Transaktionshistorie, Marktdaten, Portfolio-Übersicht |
| **Paperless NGX** | Belegarchiv, Extraktion via Paperless GPT (Staging) |
| **PostgreSQL** | Analytics Layer (Schema `portmetrics`) |
| **PortMetrics API** | REST API für Dashboard und Webhooks |
| **PortMetrics Worker** | Sync, FIFO-Rebuild, Metrics-Jobs |
| **PortMetrics Web** | Custom Dashboard (React SPA) |

## Datenfluss

1. Wertpapier-PDF landet in Paperless → P-GPT extrahiert Felder (ISIN, Stückzahl, Kurs, Gebühr, …)
2. Staging-Eintrag wird manuell oder halbautomatisch geprüft
3. Nach Bestätigung: Import nach Ghostfolio via `POST /api/v1/import`
4. Sync-Service zieht Activities und Kurse aus Ghostfolio nach PostgreSQL
5. FIFO-Engine berechnet Lots, Consumptions und Kennzahlen
6. Dashboard liest aus PostgreSQL (und optional Ghostfolio für Allokation)

## Docker Services (geplant)

```yaml
services:
  portmetrics-api:      # Port 8080 — REST API
  portmetrics-worker:   # Hintergrund-Jobs (Sync, FIFO, Metrics)
  portmetrics-web:      # Port 3000 — Dashboard SPA
```

PostgreSQL läuft extern (bestehende Unraid-Instanz). Zugriff via `host.docker.internal` oder LAN-IP.

## Source of Truth

| Datentyp | Quelle |
|----------|--------|
| Transaktionen | Ghostfolio |
| Belege | Paperless |
| FIFO-Lots, Perioden-KPIs | PostgreSQL (abgeleitet) |
| Tageskurse | Ghostfolio → gespiegelt in `price_snapshots` |

Paperless ist **nicht** das Ledger — Extraktionsfehler werden im Staging abgefangen, bevor sie Ghostfolio erreichen.

## Authentifizierung

Finanzdaten nicht öffentlich exponieren. Empfohlen: Reverse Proxy (NPM/Traefik) mit Authentik oder Basic Auth vor `portmetrics-web` und `portmetrics-api`.

## Idempotenz

- `gf_activity_id` als Unique Key für Activities
- `paperless_document_id` als Unique Key für Staging-Imports
- `sync_state` Tabelle für Cursor und Checksums pro Quelle
