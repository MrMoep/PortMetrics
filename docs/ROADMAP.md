# Roadmap

> Tracking: [GitHub Issues](https://github.com/MrMoep/PortMetrics/issues). Release-Historie: [CHANGELOG.md](../CHANGELOG.md).

## v0.2.0 (released)

| Issue | Beschreibung | Stand |
|-------|--------------|-------|
| [#29](https://github.com/MrMoep/PortMetrics/issues/29) | Settings: Paperless Field-Mapping UI | ✅ |
| [#30](https://github.com/MrMoep/PortMetrics/issues/30) | Paperless Auto-Ingest (Webhook/Scheduler) | ✅ |
| — | CORS_ORIGINS für Reverse Proxy | ✅ |

## v0.1.0 (released)

Alle v1-Phasen und die Single-Container-Infrastruktur sind umgesetzt.

| Phase | Issue | Beschreibung | Stand |
|-------|-------|--------------|-------|
| 0 | [#1](https://github.com/MrMoep/PortMetrics/issues/1) | Ghostfolio → PostgreSQL Sync | ✅ |
| 1 | [#2](https://github.com/MrMoep/PortMetrics/issues/2) | FIFO Engine + Verkaufs-Simulator | ✅ |
| 2 | [#3](https://github.com/MrMoep/PortMetrics/issues/3) | Perioden-Metriken | ✅ |
| 3 | [#4](https://github.com/MrMoep/PortMetrics/issues/4) | Paperless-Integration | ✅ |
| 4 | [#5](https://github.com/MrMoep/PortMetrics/issues/5) | Dashboard v1 | ✅ |

### Infrastruktur

| Issue | Beschreibung | Stand |
|-------|--------------|-------|
| [#15](https://github.com/MrMoep/PortMetrics/issues/15) | Single Container + Scaffolding | ✅ |
| [#6](https://github.com/MrMoep/PortMetrics/issues/6) | PostgreSQL Schema + Migrationen | ✅ |

## Future / nach 0.2

| Issue | Beschreibung | Priorität |
|-------|--------------|-----------|
| [#7](https://github.com/MrMoep/PortMetrics/issues/7) | IRR / Geldgewichtete Rendite | P2 |
| [#8](https://github.com/MrMoep/PortMetrics/issues/8) | Steuer-Freibetrag Tracker | P2 |
| [#9](https://github.com/MrMoep/PortMetrics/issues/9) | Drawdown / Volatilität | P2 |
| [#10](https://github.com/MrMoep/PortMetrics/issues/10) | Sektor-Allokation (Ghostfolio einbetten) | P2 |
| [#11](https://github.com/MrMoep/PortMetrics/issues/11) | Edge Cases (Splits, Überträge, Währung) | P2 |
| [#12](https://github.com/MrMoep/PortMetrics/issues/12) | Alerts & Benachrichtigungen | P3 |
| [#13](https://github.com/MrMoep/PortMetrics/issues/13) | Multi-User / Multi-Portfolio | P3 |
| [#14](https://github.com/MrMoep/PortMetrics/issues/14) | Export (CSV/PDF) für Steuerberater | P3 |

## v0.1 Must-Have Kennzahlen

1. FIFO-Lots (offen) — Restmenge, Einstand, unrealisierter Gewinn %
2. Paket-Rendite pro Lot
3. Realisierte Gewinne bei Verkäufen
4. Verkaufs-Simulator (What-If)
5. Einfache Rendite pro Position (nicht TWR)
6. Perioden-Rendite: 30T, MTD, YTD, letzter Monat, letztes Jahr

## Hinweis

PortMetrics liefert **Steuer-Schätzungen**, keine Steuererklärung. Abweichungen zur Bank sind möglich.
