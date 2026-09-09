# PortMetrics

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

Details: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Tech-Stack

| Schicht | Technologie |
|---------|-------------|
| Datenbank | PostgreSQL 18 (`portmetrics` / `portmetrics_test`, extern) |
| App | Python 3.12, FastAPI (API + SPA + Hintergrund-Jobs) |
| FIFO Engine | Python (deterministisch, unit-testbar) |
| Frontend | React, Vite, TanStack Table (Phase 4; Single Container) |
| Deployment | **Ein** Docker-Image (`ghcr.io/…/portmetrics`), gebaut auf `main` |

## Branches & CI

```
feature/* → PR → dev → PR → main
                 Tests        Tests + Image-Build
```

Details: [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)

Lokal (ohne Image-Build):

```powershell
cd api
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
pytest
```

## Roadmap

Die Umsetzung ist in Phasen gegliedert — siehe [GitHub Issues](https://github.com/MrMoep/PortMetrics/issues) und [docs/ROADMAP.md](docs/ROADMAP.md).

| Phase | Fokus |
|-------|-------|
| 0 | Ghostfolio → PostgreSQL Sync |
| 1 | FIFO Engine + Verkaufs-Simulator |
| 2 | Perioden-Metriken (30T, MTD, YTD, CAGR) |
| 3 | Paperless-Integration |
| 4 | Dashboard v1 |
| Future | IRR, Freibetrag-Tracker, Drawdown, … |

## Status

Scaffold + CI/CD-Workflows. Fachliche Phasen folgen über Feature-PRs nach `dev`.

## Lizenz

TBD
