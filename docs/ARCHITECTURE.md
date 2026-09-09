# Architektur

## Komponenten

| Komponente | Rolle |
|------------|-------|
| **Ghostfolio** | Kanonische Transaktionshistorie, Marktdaten, Portfolio-Übersicht |
| **Paperless NGX** | Belegarchiv, Extraktion via Paperless GPT (Staging) |
| **PostgreSQL** | Analytics Layer (Schema `portmetrics`) — läuft **extern** |
| **PortMetrics** | Ein Container: API + SPA + Hintergrund-Jobs |

## Datenfluss

1. Wertpapier-PDF landet in Paperless → P-GPT extrahiert Felder (ISIN, Stückzahl, Kurs, Gebühr, …)
2. Staging-Eintrag wird manuell oder halbautomatisch geprüft
3. Nach Bestätigung: Import nach Ghostfolio via `POST /api/v1/import`
4. PortMetrics zieht Activities und Kurse aus Ghostfolio nach PostgreSQL
5. FIFO-Engine berechnet Lots, Consumptions und Kennzahlen
6. Dashboard liest aus PostgreSQL (und optional Ghostfolio für Allokation)

## Deployment: Single Container (v1)

Für Homelab/Unraid reicht **ein** Container. API, Frontend und Worker laufen im gleichen Image:

| Pfad / Prozess | Aufgabe |
|----------------|---------|
| `/` | React SPA (statisch ausgeliefert von FastAPI) |
| `/api/...` | REST API |
| `/health` | Health-Check |
| Background (APScheduler) | Sync → FIFO-Rebuild → Metrics (Intervalle per Env) |
| `/app/logs` | Rotierende App-Logs (Volume / Unraid Appdata) |

```yaml
services:
  portmetrics:
    image: ghcr.io/<owner>/portmetrics:latest   # gebaut bei Push auf main
    ports:
      - "8080:8080"
    env_file: .env
    # PostgreSQL bleibt extern (bestehende Unraid-Instanz)
```

Zugriff auf PostgreSQL via `host.docker.internal` oder LAN-IP.

### Datenbanken

| DB | Zweck |
|----|-------|
| `portmetrics` | Produktiv |
| `portmetrics_test` | Tests + lokale Entwicklung |

Entwicklung und CI nutzen die Test-DB (`TEST_DATABASE_URL`). Branching/CI: [docs/DEVELOPMENT.md](DEVELOPMENT.md).

### Warum nicht 3 Container?

Die Trennung API / Worker / Web wäre sauber skalierbar, ist für einen Nutzer und überschaubares Portfolio unnötig. Später kann der Worker bei Bedarf ausgelagert werden; v1 bleibt bewusst einfach.

## Source of Truth

| Datentyp | Quelle |
|----------|--------|
| Transaktionen | Ghostfolio |
| Belege | Paperless |
| FIFO-Lots, Perioden-KPIs | PostgreSQL (abgeleitet) |
| Tageskurse | Ghostfolio → gespiegelt in `price_snapshots` |

Paperless ist **nicht** das Ledger — Extraktionsfehler werden im Staging abgefangen, bevor sie Ghostfolio erreichen. Setup der Custom Fields: [PAPERLESS.md](PAPERLESS.md).

## Authentifizierung

Finanzdaten nicht öffentlich exponieren. Empfohlen: Reverse Proxy (NPM/Traefik) mit Authentik oder Basic Auth vor PortMetrics (Port 8080).

## Idempotenz

- `gf_activity_id` als Unique Key für Activities
- `paperless_document_id` als Unique Key für Staging-Imports
- `sync_state` Tabelle für Cursor und Checksums pro Quelle
