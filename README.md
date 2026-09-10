# PortMetrics

**Version 0.2.0** · [Changelog](CHANGELOG.md) · [GitHub](https://github.com/MrMoep/PortMetrics)

Self-hosted Portfolio-Analytics für Homelab-Umgebungen. PortMetrics erweitert [Ghostfolio](https://ghostfol.io) um FIFO-Lot-Tracking, Perioden-Renditen und steuerrelevante Auswertungen — mit optionaler Anbindung an [Paperless NGX](https://docs.paperless-ngx.com/) für Wertpapierbelege.

## Warum PortMetrics?

Ghostfolio eignet sich gut als Portfolio-Übersicht und Transaktions-Hub, hat aber Einschränkungen für fortgeschrittene Auswertungen:

- Kein **FIFO-Lot-Tracking** auf Paket-Ebene
- **Time-Weighted Return (TWR)** statt einfacher Kostenbasis-Rendite — bei DCA oft unintuitiv
- Keine **Perioden-Kennzahlen** (30T, MTD, YTD, …) in der gewünschten Granularität
- Keine **Steuer-Schätzung** bei simulierten Verkäufen

PortMetrics füllt diese Lücke als Analytics-Schicht über Ghostfolio.

## Architektur (Kurzüberblick)

```
Paperless (Belege) → Staging/Review → Ghostfolio (Transaktionen)
                                           ↓
                                    Sync Service
                                           ↓
                              PostgreSQL (portmetrics)
                                           ↓
                                    FIFO Engine
                                           ↓
                                   Custom Dashboard
```

**Source of Truth:** Ghostfolio = kanonische Transaktionshistorie. PostgreSQL = abgeleitete Analytics. Paperless = Belegarchiv + Import-Staging.

| Dokument | Inhalt |
|----------|--------|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Komponenten, Datenfluss, Single Container |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | PostgreSQL-Schema, FIFO |
| [docs/API.md](docs/API.md) | REST-Endpunkte |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Unraid / Docker / Image-Tags |
| [docs/PAPERLESS.md](docs/PAPERLESS.md) | Custom Fields, Mapping, Webhook |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Branches, lokal testen, CI |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phasen & Future |
| [docs/DESIGN.md](docs/DESIGN.md) | UI Design System (Terminal / Ledger) |

## Tech-Stack

| Schicht | Technologie |
|---------|-------------|
| Datenbank | PostgreSQL 18 (`portmetrics` / `portmetrics_test`, extern) |
| App | Python 3.12, FastAPI (API + SPA + APScheduler) |
| FIFO Engine | Python (deterministisch, unit-testbar) |
| Frontend | React 19, Vite |
| Deployment | Ein Docker-Image `ghcr.io/mrmoep/portmetrics` |

## Quick Start (Produktion)

```yaml
services:
  portmetrics:
    image: ghcr.io/mrmoep/portmetrics:0.2.0
    ports:
      - "8080:8080"
    env_file: .env
    volumes:
      - /mnt/user/appdata/portmetrics/logs:/app/logs
    restart: unless-stopped
```

Vorher: DB anlegen, `.env` aus [`.env.example`](.env.example). Schema-Migrationen laufen beim Container-Start automatisch. Details: [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## Lokal entwickeln

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
uvicorn portmetrics.main:app --reload --port 8080
```

Branches & CI: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

```
feature/* → PR → dev → PR → main → Image (GHCR) + Release-Tags
```

## Status (0.2.0)

| Phase | Fokus | Stand |
|-------|-------|-------|
| 0–4 | Ghostfolio Sync, FIFO, Metriken, Paperless Staging, Dashboard | ✅ (0.1.0) |
| 0.2 | Field-Mapping UI, Webhook-Ingest, CORS | ✅ |
| Future | IRR, Freibetrag, Drawdown, … | offen (#7–#14) |

Im Dashboard erscheint **v0.2.0** unter dem Titel; Klick öffnet das GitHub-Repo.

## Hinweis

PortMetrics liefert **Steuer-Schätzungen**, keine Steuererklärung.

## Lizenz

TBD
