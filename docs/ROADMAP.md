# Roadmap

> Die kanonische Tracking-Quelle sind die [GitHub Issues](https://github.com/MrMoep/PortMetrics/issues). Dieses Dokument dient als Übersicht.

## Phasen (v1)

| Phase | Issue | Beschreibung | Priorität |
|-------|-------|--------------|-----------|
| 0 | #1 | Ghostfolio → PostgreSQL Sync | P0 |
| 1 | #2 | FIFO Engine + Verkaufs-Simulator | P0 |
| 2 | #3 | Perioden-Metriken | P0 |
| 3 | #4 | Paperless-Integration | P1 |
| 4 | #5 | Dashboard v1 | P0 |

## Infrastruktur

| Issue | Beschreibung |
|-------|--------------|
| #6 | Docker Compose + Projekt-Scaffolding |
| #7 | PostgreSQL Schema + Migrationen |

## Future / nth

| Issue | Beschreibung | Priorität |
|-------|--------------|-----------|
| #8 | IRR / Geldgewichtete Rendite | P2 |
| #9 | Steuer-Freibetrag Tracker | P2 |
| #10 | Drawdown / Volatilität | P2 |
| #11 | Sektor-Allokation (Ghostfolio einbetten) | P2 |
| #12 | Edge Cases automatisieren (Splits, Überträge, Währung) | P2 |
| #13 | Alerts & Benachrichtigungen | P3 |
| #14 | Multi-User / Multi-Portfolio | P3 |
| #15 | Export (CSV/PDF) für Steuerberater | P3 |

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
