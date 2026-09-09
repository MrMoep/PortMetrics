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

## Tech-Stack (geplant)

| Schicht | Technologie |
|---------|-------------|
| Datenbank | PostgreSQL 18 (Schema `portmetrics`, extern) |
| App | Python 3.12, FastAPI (API + SPA + Hintergrund-Jobs) |
| FIFO Engine | Python (deterministisch, unit-testbar) |
| Frontend | React, Vite, TanStack Table (aus demselben Container) |
| Deployment | **Ein** Docker-Container auf Unraid |

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

**Frühe Planungsphase** — Repository und Dokumentation. Implementierung folgt phasenweise.

## Lizenz

TBD
