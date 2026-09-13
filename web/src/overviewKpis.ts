import type { Overview } from "./api";

export type KpiFormat = "money" | "pct" | "ratio";

export type OverviewKpiId =
  | "nav"
  | "invested"
  | "unrealized_gain"
  | "cagr"
  | "irr_mwr"
  | "simple_return"
  | "max_drawdown"
  | "volatility"
  | "sharpe"
  | "tax_allowance_remaining"
  | "dividends_ytd"
  | "interest_ytd"
  | "dividends_total";

export type OverviewKpiDef = {
  id: OverviewKpiId;
  label: string;
  hint: string;
  format: KpiFormat;
  signed?: boolean;
  /** Dynamic label suffix (e.g. year). */
  labelExtra?: (overview: Overview) => string;
  value: (overview: Overview) => string | null | undefined;
  /** Tax remaining uses warn coloring when not in show-mode. */
  warnNeg?: (overview: Overview) => boolean;
};

/** Default visible order = today's hard-coded Overview layout. */
export const DEFAULT_KPI_IDS: OverviewKpiId[] = [
  "nav",
  "invested",
  "unrealized_gain",
  "cagr",
  "irr_mwr",
  "simple_return",
  "max_drawdown",
  "volatility",
  "sharpe",
  "tax_allowance_remaining",
  "dividends_ytd",
  "interest_ytd",
  "dividends_total",
];

export const DEFAULT_HERO_ID: OverviewKpiId = "nav";

export const OVERVIEW_KPIS: OverviewKpiDef[] = [
  {
    id: "nav",
    label: "NAV",
    hint: "Nettoinventarwert — aktueller Marktwert aller offenen Positionen.",
    format: "money",
    value: (o) => o.nav,
  },
  {
    id: "invested",
    label: "Investiert",
    hint: "Summe der Einstandswerte (offene Lots × Stückkosten).",
    format: "money",
    value: (o) => o.invested,
  },
  {
    id: "unrealized_gain",
    label: "Unrealisiert",
    hint: "Buchgewinn/-verlust: Marktwert minus Investiert.",
    format: "money",
    signed: true,
    value: (o) => o.unrealized_gain,
  },
  {
    id: "cagr",
    label: "CAGR",
    hint: "Jährlich annualisierte Rendite über die gesamte Haltedauer.",
    format: "pct",
    signed: true,
    value: (o) => o.cagr.cagr,
  },
  {
    id: "irr_mwr",
    label: "IRR (MWR)",
    hint: "Geldgewichtete interne Verzinsung (IRR/MWR) inkl. Trades, Dividenden, Zinsen und End-NAV.",
    format: "pct",
    signed: true,
    value: (o) => o.mwr?.irr,
  },
  {
    id: "simple_return",
    label: "Einfache Rendite",
    hint: "Einfache Gesamtrendite: (Endwert − Kapitaleinsatz) / Kapitaleinsatz.",
    format: "pct",
    signed: true,
    value: (o) => o.mwr?.simple_return,
  },
  {
    id: "max_drawdown",
    label: "Max Drawdown",
    hint: "Größter Kursrückgang vom Zwischenhoch zum folgenden Tief.",
    format: "pct",
    signed: true,
    value: (o) => o.risk?.max_drawdown,
  },
  {
    id: "volatility",
    label: "Volatilität",
    hint: "Annualisierte Schwankungsbreite der Periodenrenditen.",
    format: "pct",
    value: (o) => o.risk?.volatility,
  },
  {
    id: "sharpe",
    label: "Sharpe",
    hint: "Überrendite je Einheit Risiko (vs. risikofreiem Zinssatz).",
    format: "ratio",
    signed: true,
    value: (o) => o.risk?.sharpe,
  },
  {
    id: "tax_allowance_remaining",
    label: "Freibetrag rest",
    hint:
      "Verbleibender steuerlicher Freibetrag im laufenden Jahr (nach realisierten Gewinnen, Dividenden und Zinsen).",
    format: "money",
    signed: true,
    labelExtra: (o) => (o.tax_allowance?.year != null ? ` (${o.tax_allowance.year})` : " (—)"),
    value: (o) => o.tax_allowance?.remaining,
    warnNeg: (o) => Boolean(o.tax_allowance?.warn),
  },
  {
    id: "dividends_ytd",
    label: "Dividenden YTD",
    hint: "Brutto-Dividenden im laufenden Kalenderjahr.",
    format: "money",
    labelExtra: (o) => {
      const year = o.dividends.year ?? o.tax_allowance?.year;
      return year != null ? ` (${year})` : " (—)";
    },
    value: (o) => o.dividends.ytd ?? "0",
  },
  {
    id: "interest_ytd",
    label: "Zinsen YTD",
    hint: "Brutto-Zinsen (INTEREST) im laufenden Kalenderjahr.",
    format: "money",
    value: (o) => o.dividends.interest_ytd ?? "0",
  },
  {
    id: "dividends_total",
    label: "Dividenden gesamt",
    hint: "Summe aller erhaltenen Dividenden (gesamter Zeitraum).",
    format: "money",
    value: (o) => o.dividends.total,
  },
];

export const KPI_BY_ID: Record<OverviewKpiId, OverviewKpiDef> = Object.fromEntries(
  OVERVIEW_KPIS.map((k) => [k.id, k]),
) as Record<OverviewKpiId, OverviewKpiDef>;

export type OverviewLayout = {
  kpi_ids: OverviewKpiId[];
  hero_id: OverviewKpiId;
};

export function defaultOverviewLayout(): OverviewLayout {
  return { kpi_ids: [...DEFAULT_KPI_IDS], hero_id: DEFAULT_HERO_ID };
}

/** Drop unknown IDs; ensure ≥1 visible; hero must be among visible. */
export function normalizeOverviewLayout(raw: {
  kpi_ids?: string[] | null;
  hero_id?: string | null;
} | null | undefined): OverviewLayout {
  const known = new Set<string>(DEFAULT_KPI_IDS);
  const seen = new Set<string>();
  const kpi_ids: OverviewKpiId[] = [];
  for (const item of raw?.kpi_ids ?? DEFAULT_KPI_IDS) {
    const id = String(item || "").trim();
    if (known.has(id) && !seen.has(id)) {
      seen.add(id);
      kpi_ids.push(id as OverviewKpiId);
    }
  }
  if (kpi_ids.length === 0) {
    return defaultOverviewLayout();
  }
  const heroRaw = String(raw?.hero_id || "").trim();
  const hero_id = kpi_ids.includes(heroRaw as OverviewKpiId)
    ? (heroRaw as OverviewKpiId)
    : kpi_ids[0];
  return { kpi_ids, hero_id };
}

/** Full catalog order for the editor: saved visible order, then hidden catalog leftovers. */
export function editorOrder(layout: OverviewLayout): OverviewKpiId[] {
  const visible = new Set(layout.kpi_ids);
  const rest = DEFAULT_KPI_IDS.filter((id) => !visible.has(id));
  return [...layout.kpi_ids, ...rest];
}
