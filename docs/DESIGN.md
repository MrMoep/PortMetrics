# Design System — Terminal / Ledger

PortMetrics UI folgt der Richtung **Terminal / Ledger** (Mockup #3): hartkantig, datendicht, industrial — bewusst weg vom generischen „KI-SaaS“-Look (keine Lila-Gradients, kein Inter/Roboto, keine weichen Pill-Cards, keine zentrierten Feature-Trios).

Referenz-Mockups (Chat-Assets): `portmetrics-mockup-terminal.png`.

## Prinzipien

1. **Dichte vor Dekoration** — Tabellen und Kennzahlen haben Vorrang; Flächen bleiben flach.
2. **Harte Geometrie** — `border-radius: 0`, 1px-Linien in Ink, Offset-Schatten ohne Blur.
3. **Mono für Daten** — alle Zahlen, IDs, Statuszeilen und Labels in Monospace.
4. **Asymmetrie** — Overview und Simulator als Split-Workspace; Nebenpanels dürfen leicht versetzt sein (`.pane-offset`).
5. **Ein Signal-Akzent** — Seafoam nur für Active/Primary/positiv; Brick nur für Fehler/negativ.
6. **Kein Soft-UI** — keine mehrstufigen Schatten, kein Glow, keine Emoji-Badges, keine Icon-Kreise.

## Typografie

| Rolle | Font | Verwendung |
|-------|------|------------|
| UI / Display | **Barlow** 400/600/700 | Wordmark, Nav, Buttons |
| Daten / Meta | **IBM Plex Mono** 400/500/600 | KPIs, Tabellenwerte, Panel-Labels, Forms, Status |

- Wordmark: Uppercase, `letter-spacing: 0.04em`, fett.
- Nav & Buttons: Uppercase, kompakt (`~0.75–0.82rem`).
- Panel-Labels: Mono, Uppercase, weite Tracking (`0.08em`), muted.

Laden: Google Fonts in `web/index.html`.

## Farbe (CSS-Variablen)

Definiert in `web/src/styles.css` unter `:root` / `prefers-color-scheme: dark`.

| Token | Light | Dark | Bedeutung |
|-------|-------|------|-----------|
| `--steel` | `#dce1e6` | `#1a1f24` | App-Hintergrund |
| `--steel-deep` | `#c5ccd4` | `#12161a` | Nav-/Panel-Kopf, Tabellenkopf |
| `--panel` | `#f4f6f8` | `#242a31` | Flächen / Inputs |
| `--ink` / `--line` | `#0e1114` | `#e8ecf0` | Text & harte Kanten |
| `--muted` | `#4a5560` | `#9aa3ad` | Sekundärtext |
| `--accent` / `--ok` | `#1fa39a` | `#2ec4b6` | Primary, aktiv, positiv-Signal |
| `--danger` / `--val-neg` | `#b83228` | `#e05a4f` | Fehler, negative Werte |
| `--val-pos` | `#147a74` | `#3dd6c6` | Positive Zahlen |
| `--bar` | `#0e1114` | `#0a0c0e` | Topbar |
| `--shadow` | `4px 4px 0 #0e1114` | `4px 4px 0 #000` | Hard-Offset (Primary) |

Hintergrund zusätzlich: **24px-Raster** über halbtransparente Linien (`--grid-line`).

## Layout-Bausteine

| Element | Klasse(n) | Beschreibung |
|---------|-----------|--------------|
| App-Rahmen | `.app` | max-width 1280px |
| Topbar | `.topbar` | Volle Breite, Ink-Band, Accent-Unterkante 3px |
| Brand | `.brand`, `.brand-meta` | Wordmark + Mono-Subline inkl. Version |
| Ops (Quick) | `.ops-icons`, `.icon-btn` | Kleine Icon-Buttons rechts in der Topbar (Sync/Rebuild) |
| Refresh | `.icon-btn-on-panel` in `.status-bar` | Ansicht neu laden — getrennt von Server-Jobs |
| Ops (Settings) | `.ops-list`, `.ops-row` | Dieselben Jobs mit Label + Hinweis unter Einstellungen |
| Navigation | `.nav` | Text-Tabs, Active = Accent-Underline (keine Pills) |
| Settings-Subnav | `.nav.subnav` | Sekundäre Tabs unter Einstellungen; Hash `#settings/<section>` |
| Status | `.status-bar` | Harte Box unter der Nav |
| Panel | `.panel`, `.panel-head`, `.panel-body`, `.panel-label` | Modul mit Mono-Kopfzeile |
| Workspace | `.workspace`, `.workspace-sim` | Split ab ~900px; Simulator enger links |
| Offset-Pane | `.pane-offset` | Leichter Versatz des Nebenpanels (Desktop) |
| KPI | `.stat`, `.stat-hero` | Harte Kacheln; Hero spannt volle Breite |
| Werte | `.val-pos`, `.val-neg` | Vorzeichenfarbe |
| Tabelle | `table`, `.table-wrap` | Sichtbare Zellgrenzen, Mono-Header |
| Formulare | `.form`, `.form-wide`, `.form-filters` | Mono-Labels Uppercase; Filter-Form breiter |
| Sync-Filter | `.filter-grid`, `.filter-col`, `.check-list-*` | Live-Suche; Ausgewählt / Verfügbar getrennt |
| Primary CTA | `.primary` | Accent-Fill + Hard-Shadow |

## Interaktion

- Hover auf Sekundärbuttons: Invert (Ink-Fill / Panel-Text) — **kein** weiches Fade als Markenzeichen.
- Primary Hover: Invert + Shadow wechselt auf Accent.
- Focus-visible: 2px Accent-Outline.
- Disabled: Opacity ~0.4, kein Shadow.

## Komponenten-Mapping (Features)

| Screen | Struktur |
|--------|----------|
| Overview | Workspace: Kennzahlen + Perioden (oben); Cashflow-Timeline + Jahres-Rendite (unten, Jahresreihe mit Abschluss / Bis heute) |
| FIFO Lots / Positionen / Staging | Einzelpanel + dichte Tabelle |
| Simulator | Split: Formular \| Ergebnispanel |
| Settings | Subnav (Wartung · Portfolio · Assets · Paperless · Ghostfolio) + ein Panel; Deep-Links `#settings/ops` usw. |
| Künftig: Charts / Allokation / Alerts | Als gerahmte Panels im gleichen Raster; Embeds mit Mono-Label „Quelle: …“ |

## Bewusst vermieden

- Inter, Roboto, System-UI als Display-Schrift
- Lila/Indigo-Gradients, Glow, Glassmorphism
- `rounded-2xl` / Pill-Badges / Lucide-in-Kreis
- Drei gleich große zentrierte Feature-Cards
- Warme Cream-Terracotta-Editorial-Klischees
- Weiche mehrlagige Drop-Shadows

## Dateien

| Pfad | Rolle |
|------|-------|
| `web/src/styles.css` | Tokens & alle UI-Regeln |
| `web/src/App.tsx` | Struktur (Panel, Workspace, signedClass) |
| `web/index.html` | Fonts, theme-color |
| `web/public/logo-*.svg`, `favicon.svg` | Marke: scharfe Ecken, Seafoam |
| `docs/DESIGN.md` | Diese Spezifikation |

Bei UI-Änderungen Tokens und Bausteine hier mitziehen, statt ad-hoc neue Optik einzuführen.
