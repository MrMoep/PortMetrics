# Roadmap

> Die kanonische Tracking-Quelle sind die [GitHub Issues](https://github.com/MrMoep/PortMetrics/issues). Dieses Dokument dient als Übersicht.

## Phasen (v1)

| Phase | Issue | Beschreibung | Priorität |
|-------|-------|--------------|-----------|
| 0 | [#1](https://github.com/MrMoep/PortMetrics/issues/1) | Ghostfolio → PostgreSQL Sync | P0 |
| 1 | [#2](https://github.com/MrMoep/PortMetrics/issues/2) | FIFO Engine + Verkaufs-Simulator | P0 |
| 2 | [#3](https://github.com/MrMoep/PortMetrics/issues/3) | Perioden-Metriken | P0 |
| 3 | [#4](https://github.com/MrMoep/PortMetrics/issues/4) | Paperless-Integration | P1 |
| 4 | [#5](https://github.com/MrMoep/PortMetrics/issues/5) | Dashboard v1 | P0 |

## Infrastruktur

| Issue | Beschreibung |
|-------|--------------|
| [#15](https://github.com/MrMoep/PortMetrics/issues/15) | Single Container + Projekt-Scaffolding |
| [#6](https://github.com/MrMoep/PortMetrics/issues/6) | PostgreSQL Schema + Migrationen |

Branching & lokale Tests: [DEVELOPMENT.md](DEVELOPMENT.md) (`dev` Sammler, Feature-PRs, Image nur auf `main`).

## Future / nth

| Issue | Beschreibung | Priorität |
|-------|--------------|-----------|
| [#7](https://github.com/MrMoep/PortMetrics/issues/7) | IRR / Geldgewichtete Rendite | P2 |
| [#8](https://github.com/MrMoep/PortMetrics/issues/8) | Steuer-Freibetrag Tracker | P2 |
| [#9](https://github.com/MrMoep/PortMetrics/issues/9) | Drawdown / Volatilität | P2 |
| [#10](https://github.com/MrMoep/PortMetrics/issues/10) | Sektor-Allokation (Ghostfolio einbetten) | P2 |
| [#11](https://github.com/MrMoep/PortMetrics/issues/11) | Edge Cases automatisieren (Splits, Überträge, Währung) | P2 |
| [#12](https://github.com/MrMoep/PortMetrics/issues/12) | Alerts & Benachrichtigungen | P3 |
| [#13](https://github.com/MrMoep/PortMetrics/issues/13) | Multi-User / Multi-Portfolio | P3 |
| [#14](https://github.com/MrMoep/PortMetrics/issues/14) | Export (CSV/PDF) für Steuerberater | P3 |

## v1 Must-Have Kennzahlen (P0)

1. FIFO-Lots (offen) — Restmenge, Einstand, unrealisierter Gewinn %
2. Paket-Rendite pro Lot
3. Realisierte Gewinne bei Verkäufen
4. Verkaufs-Simulator (What-If)
5. Einfache Rendite pro Position (nicht TWR)
6. Perioden-Rendite: 30T, MTD, YTD, letzter Monat, letztes Jahr

## Geschätzter Aufwand v1

Ca. 2–4 Wochen Teilzeit — abhängig von historischer Datenqualität in Ghostfolio.

## Hinweis

PortMetrics liefert **Steuer-Schätzungen**, keine Steuererklärung. Abweichungen zur Bank sind möglich.
