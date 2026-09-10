import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";
import {
  api,
  Lot,
  Overview,
  PaperlessField,
  PaperlessIdName,
  PaperlessSettings,
  PortfolioSettings,
  StagingItem,
  VersionInfo,
} from "./api";

type Tab = "overview" | "lots" | "positions" | "simulator" | "staging" | "settings";
type SettingsSection = "ops" | "portfolio" | "paperless" | "ghostfolio";
type SortDir = "asc" | "desc";
type SortState = { key: string; dir: SortDir };

const SETTINGS_SECTIONS: { id: SettingsSection; label: string }[] = [
  { id: "ops", label: "Wartung" },
  { id: "portfolio", label: "Portfolio" },
  { id: "paperless", label: "Paperless" },
  { id: "ghostfolio", label: "Ghostfolio" },
];

const SETTINGS_SECTION_IDS = new Set<string>(SETTINGS_SECTIONS.map((s) => s.id));

function parseSettingsHash(hash: string): SettingsSection | null {
  const match = hash.match(/^#settings\/([a-z]+)$/i);
  if (!match) return null;
  const id = match[1].toLowerCase();
  return SETTINGS_SECTION_IDS.has(id) ? (id as SettingsSection) : null;
}

function settingsHash(section: SettingsSection): string {
  return `#settings/${section}`;
}

function sameIdNameList(a: PaperlessIdName[], b: PaperlessIdName[]): boolean {
  if (a.length !== b.length) return false;
  const ids = new Set(a.map((row) => row.id));
  return b.every((row) => ids.has(row.id));
}

function SyncFilterPicker({
  label,
  items,
  selected,
  onChange,
  emptyHint,
}: {
  label: string;
  items: PaperlessIdName[];
  selected: PaperlessIdName[];
  onChange: (next: PaperlessIdName[]) => void;
  emptyHint: string;
}) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const selectedIds = new Set(selected.map((row) => row.id));
  const matches = (item: PaperlessIdName) =>
    !q ||
    item.name.toLowerCase().includes(q) ||
    String(item.id).includes(q);

  const selectedVisible = selected.filter(matches);
  const available = items.filter((item) => !selectedIds.has(item.id) && matches(item));

  function add(item: PaperlessIdName) {
    if (selectedIds.has(item.id)) return;
    onChange([...selected, { id: item.id, name: item.name }]);
  }

  function remove(item: PaperlessIdName) {
    onChange(selected.filter((row) => row.id !== item.id));
  }

  return (
    <div className="filter-col">
      <strong className="mono">{label}</strong>
      <label className="filter-search">
        <span className="visually-hidden">Filter {label}</span>
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Filtern…"
        />
      </label>
      {items.length === 0 && <p className="muted">{emptyHint}</p>}
      <div className="filter-bucket">
        <div className="filter-bucket-head mono">
          Ausgewählt ({selectedVisible.length}
          {q && selected.length !== selectedVisible.length ? `/${selected.length}` : ""})
        </div>
        <div className="check-list check-list-selected">
          {selectedVisible.length === 0 ? (
            <p className="muted">{q ? "Keine Treffer." : "Keine Auswahl."}</p>
          ) : (
            selectedVisible.map((item) => (
              <label key={item.id} className="check-row">
                <input type="checkbox" checked onChange={() => remove(item)} />
                <span>
                  {item.name} <span className="muted mono">#{item.id}</span>
                </span>
              </label>
            ))
          )}
        </div>
      </div>
      <div className="filter-bucket">
        <div className="filter-bucket-head mono">
          Verfügbar ({available.length}
          {!q ? `/${items.length - selected.length}` : ""})
        </div>
        <div className="check-list check-list-available">
          {items.length > 0 && available.length === 0 ? (
            <p className="muted">{q ? "Keine Treffer." : "Alles ausgewählt."}</p>
          ) : (
            available.map((item) => (
              <label key={item.id} className="check-row">
                <input type="checkbox" checked={false} onChange={() => add(item)} />
                <span>
                  {item.name} <span className="muted mono">#{item.id}</span>
                </span>
              </label>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

const FALLBACK_VERSION: VersionInfo = {
  name: "PortMetrics",
  version: "0.2.0",
  repository: "https://github.com/MrMoep/PortMetrics",
};

const FALLBACK_ROLE_META: Array<{
  role: string;
  required: boolean;
  label: string;
  hint?: string;
}> = [
  {
    role: "type",
    required: true,
    label: "Typ (BUY/SELL/DIVIDEND/FEE/INTEREST/OTHER)",
  },
  { role: "isin", required: true, label: "ISIN" },
  { role: "wkn", required: false, label: "WKN (optional)" },
  { role: "quantity", required: true, label: "Stückzahl / Nennwert" },
  { role: "unit_price", required: true, label: "Kurs (Stückkurs)" },
  { role: "fee", required: false, label: "Entgelte / Gebühr (optional)" },
];

const METRIC_HINTS: Record<string, string> = {
  nav: "Nettoinventarwert — aktueller Marktwert aller offenen Positionen.",
  invested: "Summe der Einstandswerte (offene Lots × Stückkosten).",
  unrealized: "Buchgewinn/-verlust: Marktwert minus Investiert.",
  cagr: "Jährlich annualisierte Rendite über die gesamte Haltedauer.",
  irr: "Geldgewichtete interne Verzinsung (IRR/MWR) der Cashflows inkl. End-NAV.",
  simple: "Einfache Gesamtrendite: (Endwert − Kapitaleinsatz) / Kapitaleinsatz.",
  maxdd: "Größter Kursrückgang vom Zwischenhoch zum folgenden Tief.",
  vol: "Annualisierte Schwankungsbreite der Periodenrenditen.",
  sharpe: "Überrendite je Einheit Risiko (vs. risikofreiem Zinssatz).",
  tax: "Verbleibender steuerlicher Freibetrag im laufenden Jahr.",
  dividends: "Summe erhaltener Dividenden über den betrachteten Zeitraum.",
};

function pct(value: string | null | undefined, hide = false): string {
  if (value == null) return "—";
  if (hide) return "0,00 %";
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return `${(n * 100).toFixed(2)} %`;
}

function money(value: string | null | undefined, hide = false): string {
  if (value == null) return "—";
  if (hide) return "0,00";
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Percent points already scaled (e.g. API `12.34` → `12.34 %`). */
function pctPoints(value: string | number | null | undefined, hide = false): string {
  if (value == null || value === "") return "—";
  if (hide) return "0,00 %";
  return `${value} %`;
}

function qty(value: string | number | null | undefined, hide = false): string {
  if (value == null || value === "") return "—";
  if (hide) return "0";
  return String(value);
}

function ratio(value: string | number | null | undefined, hide = false): string {
  if (value == null || value === "") return "—";
  if (hide) return "0.00";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toFixed(2);
}

function signedClass(value: string | number | null | undefined, hide = false): string {
  if (hide) return "";
  if (value == null || value === "") return "";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n) || n === 0) return "";
  return n > 0 ? "val-pos" : "val-neg";
}

function toggleSort(prev: SortState, key: string, defaultDir: SortDir = "desc"): SortState {
  if (prev.key === key) {
    return { key, dir: prev.dir === "asc" ? "desc" : "asc" };
  }
  return { key, dir: defaultDir };
}

function cmpScalar(a: unknown, b: unknown): number {
  if (a == null && b == null) return 0;
  if (a == null || a === "") return 1;
  if (b == null || b === "") return -1;
  const sa = String(a);
  const sb = String(b);
  const na = Number(sa);
  const nb = Number(sb);
  if (!Number.isNaN(na) && !Number.isNaN(nb) && sa.trim() !== "" && sb.trim() !== "") {
    return na - nb;
  }
  return sa.localeCompare(sb, "de", { numeric: true });
}

function sortRows<T>(rows: T[], sort: SortState): T[] {
  return [...rows].sort((ra, rb) => {
    const recA = ra as Record<string, unknown>;
    const recB = rb as Record<string, unknown>;
    const c = cmpScalar(recA[sort.key], recB[sort.key]);
    return sort.dir === "asc" ? c : -c;
  });
}

function SortHeader({
  label,
  column,
  sort,
  onSort,
}: {
  label: string;
  column: string;
  sort: SortState;
  onSort: (column: string) => void;
}) {
  const active = sort.key === column;
  return (
    <th aria-sort={active ? (sort.dir === "asc" ? "ascending" : "descending") : "none"}>
      <button type="button" className="th-sort" onClick={() => onSort(column)}>
        {label}
        {active ? (
          <span className="th-sort-ind" aria-hidden>
            {sort.dir === "asc" ? " ▲" : " ▼"}
          </span>
        ) : null}
      </button>
    </th>
  );
}

function assetIdColumnLabel(pref: string | null | undefined): string {
  if (pref === "wkn") return "WKN";
  if (pref === "isin") return "ISIN";
  return "Symbol";
}

function Panel({
  label,
  meta,
  children,
  className = "",
  offset = false,
}: {
  label: string;
  meta?: string;
  children: ReactNode;
  className?: string;
  offset?: boolean;
}) {
  return (
    <section className={`panel ${offset ? "pane-offset" : ""} ${className}`.trim()}>
      <div className="panel-head">
        <p className="panel-label">{label}</p>
        {meta ? <p className="panel-label">{meta}</p> : null}
      </div>
      <div className="panel-body">{children}</div>
    </section>
  );
}

type IconName = "sync" | "fifo" | "metrics" | "paperless" | "refresh" | "eye" | "eye-off";

function Icon({ name }: { name: IconName }) {
  const common = {
    width: 16,
    height: 16,
    viewBox: "0 0 16 16",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.6,
    strokeLinecap: "square" as const,
    strokeLinejoin: "miter" as const,
    "aria-hidden": true as const,
  };
  switch (name) {
    case "sync":
      return (
        <svg {...common}>
          <path d="M2.5 8a5.5 5.5 0 0 1 9.2-4.1" />
          <path d="M13.5 8a5.5 5.5 0 0 1-9.2 4.1" />
          <path d="M11 2.5v3h3" />
          <path d="M5 13.5v-3H2" />
        </svg>
      );
    case "fifo":
      return (
        <svg {...common}>
          <path d="M2 4h12" />
          <path d="M2 8h12" />
          <path d="M2 12h12" />
          <path d="M4 2v4" />
          <path d="M8 6v4" />
          <path d="M12 10v4" />
        </svg>
      );
    case "metrics":
      return (
        <svg {...common}>
          <path d="M2 13h12" />
          <path d="M4 13V7" />
          <path d="M8 13V4" />
          <path d="M12 13V9" />
        </svg>
      );
    case "paperless":
      return (
        <svg {...common}>
          <path d="M4 2h6l3 3v9H4V2z" />
          <path d="M10 2v3h3" />
          <path d="M6 8h4" />
          <path d="M6 11h4" />
        </svg>
      );
    case "refresh":
      return (
        <svg {...common}>
          <path d="M3 8a5 5 0 0 1 8.5-3.5" />
          <path d="M13 8a5 5 0 0 1-8.5 3.5" />
          <path d="M11.5 2v3.5H15" />
        </svg>
      );
    case "eye":
      return (
        <svg {...common}>
          <path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8z" />
          <circle cx="8" cy="8" r="2" />
        </svg>
      );
    case "eye-off":
      return (
        <svg {...common}>
          <path d="M1.5 8s2.5-4.5 6.5-4.5S14.5 8 14.5 8s-2.5 4.5-6.5 4.5S1.5 8 1.5 8z" />
          <circle cx="8" cy="8" r="2" />
          <path d="M3 13.5 13 2.5" />
        </svg>
      );
  }
}

const OPS_ACTIONS: {
  id: string;
  label: string;
  hint: string;
  icon: IconName;
  run: () => Promise<unknown>;
}[] = [
  {
    id: "sync",
    label: "Sync Ghostfolio",
    hint: "Activities & Kurse aus Ghostfolio nach PostgreSQL ziehen.",
    icon: "sync",
    run: () => api.sync(),
  },
  {
    id: "fifo",
    label: "Rebuild FIFO",
    hint: "Lots neu berechnen (nach Sync oder Korrekturen).",
    icon: "fifo",
    run: () => api.rebuildFifo(),
  },
  {
    id: "metrics",
    label: "Rebuild Metrics",
    hint: "Perioden-Kennzahlen aus Lots/Positionen neu ableiten.",
    icon: "metrics",
    run: () => api.rebuildMetrics(),
  },
  {
    id: "paperless",
    label: "Teilsync Paperless",
    hint: "Neueste ≤100 Belege pullen (Catch-up; Filter optional).",
    icon: "paperless",
    run: () => api.stagingSync("partial"),
  },
];

export default function App() {
  const initialSettingsSection = parseSettingsHash(
    typeof window !== "undefined" ? window.location.hash : "",
  );
  const [tab, setTab] = useState<Tab>(initialSettingsSection ? "settings" : "overview");
  const [settingsSection, setSettingsSection] = useState<SettingsSection>(
    initialSettingsSection ?? "ops",
  );
  const [overview, setOverview] = useState<Overview | null>(null);
  const [lots, setLots] = useState<Lot[]>([]);
  const [staging, setStaging] = useState<StagingItem[]>([]);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [simResult, setSimResult] = useState<Record<string, unknown> | null>(null);
  const [version, setVersion] = useState<VersionInfo>(FALLBACK_VERSION);
  const [paperlessSettings, setPaperlessSettings] = useState<PaperlessSettings | null>(null);
  const [portfolioSettings, setPortfolioSettings] = useState<PortfolioSettings | null>(null);
  const [customFields, setCustomFields] = useState<PaperlessField[]>([]);
  const [paperlessTags, setPaperlessTags] = useState<PaperlessIdName[]>([]);
  const [paperlessDocTypes, setPaperlessDocTypes] = useState<PaperlessIdName[]>([]);
  const [fieldMapDraft, setFieldMapDraft] = useState<Record<string, string>>({});
  const [syncTagsDraft, setSyncTagsDraft] = useState<PaperlessIdName[]>([]);
  const [syncDocTypesDraft, setSyncDocTypesDraft] = useState<PaperlessIdName[]>([]);
  const [accountDraft, setAccountDraft] = useState("");
  const [dataSourceDraft, setDataSourceDraft] = useState("YAHOO");
  const [publicUrlDraft, setPublicUrlDraft] = useState("");
  const [allowanceDraft, setAllowanceDraft] = useState("1000");
  const [warnPctDraft, setWarnPctDraft] = useState("0.85");
  const [riskFreeDraft, setRiskFreeDraft] = useState("0");
  const [assetIdPrefDraft, setAssetIdPrefDraft] = useState<"symbol" | "wkn" | "isin">("symbol");
  const [cashflowSort, setCashflowSort] = useState<SortState>({ key: "date", dir: "desc" });
  const [lotsSort, setLotsSort] = useState<SortState>({ key: "open_date", dir: "desc" });
  const [positionsSort, setPositionsSort] = useState<SortState>({ key: "invested", dir: "desc" });
  /** Presentation mode: zero displayed money/pct/qty (display-only, data still loaded). */
  const [showMode, setShowMode] = useState(false);

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [ov, lotData, stagingData, versionInfo, portfolio, paperless] = await Promise.all([
        api.overview(),
        api.lots(),
        api.staging(),
        api.version().catch(() => FALLBACK_VERSION),
        api.portfolioSettings().catch(() => null),
        api.paperlessSettings().catch(() => null),
      ]);
      setOverview(ov);
      setLots(lotData.lots);
      setStaging(stagingData.items);
      setVersion(versionInfo);
      if (portfolio) {
        setPortfolioSettings(portfolio);
        setAssetIdPrefDraft(portfolio.asset_id_preference || "symbol");
      }
      if (paperless) {
        setPaperlessSettings(paperless);
      }
      setStatus(`Stand ${ov.as_of}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  const loadSettings = useCallback(async () => {
    setError("");
    try {
      const [cfg, portfolio] = await Promise.all([
        api.paperlessSettings(),
        api.portfolioSettings(),
      ]);
      setPaperlessSettings(cfg);
      setPortfolioSettings(portfolio);
      const draft: Record<string, string> = {};
      for (const role of cfg.roles) {
        draft[role] = cfg.field_map[role] != null ? String(cfg.field_map[role]) : "";
      }
      setFieldMapDraft(draft);
      setSyncTagsDraft(cfg.sync_tags ?? []);
      setSyncDocTypesDraft(cfg.sync_document_types ?? []);
      setAccountDraft(cfg.ghostfolio_default_account_id ?? "");
      setDataSourceDraft(cfg.ghostfolio_data_source || "YAHOO");
      setPublicUrlDraft(cfg.public_url ?? "");
      setAllowanceDraft(portfolio.tax_allowance_eur);
      setWarnPctDraft(portfolio.tax_warn_pct);
      setRiskFreeDraft(portfolio.risk_free_rate);
      setAssetIdPrefDraft(portfolio.asset_id_preference || "symbol");
      if (cfg.paperless_configured) {
        try {
          const [fields, tags, types] = await Promise.all([
            api.paperlessCustomFields(),
            api.paperlessTags(),
            api.paperlessDocumentTypes(),
          ]);
          setCustomFields(fields.fields);
          setPaperlessTags(tags.tags);
          setPaperlessDocTypes(types.document_types);
        } catch {
          setCustomFields([]);
          setPaperlessTags([]);
          setPaperlessDocTypes([]);
        }
      } else {
        setCustomFields([]);
        setPaperlessTags([]);
        setPaperlessDocTypes([]);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    if (tab === "settings") {
      void loadSettings();
    }
  }, [tab, loadSettings]);

  function applyPortfolioDrafts(portfolio: PortfolioSettings) {
    setAllowanceDraft(portfolio.tax_allowance_eur);
    setWarnPctDraft(portfolio.tax_warn_pct);
    setRiskFreeDraft(portfolio.risk_free_rate);
    setAssetIdPrefDraft(portfolio.asset_id_preference || "symbol");
  }

  function applyPaperlessDrafts(cfg: PaperlessSettings) {
    const draft: Record<string, string> = {};
    for (const role of cfg.roles) {
      draft[role] = cfg.field_map[role] != null ? String(cfg.field_map[role]) : "";
    }
    setFieldMapDraft(draft);
    setSyncTagsDraft(cfg.sync_tags ?? []);
    setSyncDocTypesDraft(cfg.sync_document_types ?? []);
    setAccountDraft(cfg.ghostfolio_default_account_id ?? "");
    setDataSourceDraft(cfg.ghostfolio_data_source || "YAHOO");
    setPublicUrlDraft(cfg.public_url ?? "");
  }

  function isPortfolioDirty(): boolean {
    if (!portfolioSettings) return false;
    return (
      allowanceDraft.trim() !== portfolioSettings.tax_allowance_eur ||
      warnPctDraft.trim() !== portfolioSettings.tax_warn_pct ||
      riskFreeDraft.trim() !== portfolioSettings.risk_free_rate ||
      assetIdPrefDraft !== (portfolioSettings.asset_id_preference || "symbol")
    );
  }

  function isPaperlessDirty(): boolean {
    if (!paperlessSettings) return false;
    for (const role of paperlessSettings.roles) {
      const saved =
        paperlessSettings.field_map[role] != null
          ? String(paperlessSettings.field_map[role])
          : "";
      if ((fieldMapDraft[role] ?? "") !== saved) return true;
    }
    if (!sameIdNameList(syncTagsDraft, paperlessSettings.sync_tags ?? [])) return true;
    if (!sameIdNameList(syncDocTypesDraft, paperlessSettings.sync_document_types ?? [])) {
      return true;
    }
    return (publicUrlDraft.trim() || "") !== (paperlessSettings.public_url ?? "");
  }

  function isGhostfolioDirty(): boolean {
    if (!paperlessSettings) return false;
    const savedAccount = paperlessSettings.ghostfolio_default_account_id ?? "";
    const savedSource = paperlessSettings.ghostfolio_data_source || "YAHOO";
    return (
      accountDraft.trim() !== savedAccount ||
      (dataSourceDraft.trim() || "YAHOO") !== savedSource
    );
  }

  function isSectionDirty(section: SettingsSection): boolean {
    if (section === "portfolio") return isPortfolioDirty();
    if (section === "paperless") return isPaperlessDirty();
    if (section === "ghostfolio") return isGhostfolioDirty();
    return false;
  }

  function discardSectionDrafts(section: SettingsSection) {
    if (section === "portfolio" && portfolioSettings) {
      applyPortfolioDrafts(portfolioSettings);
    }
    if ((section === "paperless" || section === "ghostfolio") && paperlessSettings) {
      applyPaperlessDrafts(paperlessSettings);
    }
  }

  function confirmDiscard(section: SettingsSection): boolean {
    if (!isSectionDirty(section)) return true;
    const ok = window.confirm("Ungespeicherte Änderungen verwerfen und fortfahren?");
    if (ok) discardSectionDrafts(section);
    return ok;
  }

  function writeSettingsHash(section: SettingsSection) {
    const next = settingsHash(section);
    if (window.location.hash !== next) {
      history.replaceState(
        null,
        "",
        `${window.location.pathname}${window.location.search}${next}`,
      );
    }
  }

  function clearSettingsHash() {
    if (window.location.hash.startsWith("#settings")) {
      history.replaceState(null, "", `${window.location.pathname}${window.location.search}`);
    }
  }

  function requestTabChange(next: Tab) {
    if (next === tab) return;
    if (tab === "settings" && next !== "settings") {
      if (!confirmDiscard(settingsSection)) return;
      clearSettingsHash();
    }
    if (next === "settings") {
      setSettingsSection("ops");
      writeSettingsHash("ops");
    }
    setTab(next);
  }

  function requestSettingsSection(next: SettingsSection) {
    if (next === settingsSection) return;
    if (!confirmDiscard(settingsSection)) return;
    setSettingsSection(next);
    writeSettingsHash(next);
  }

  const settingsNavRef = useRef({
    tab,
    settingsSection,
    confirmDiscard,
    writeSettingsHash,
  });
  settingsNavRef.current = {
    tab,
    settingsSection,
    confirmDiscard,
    writeSettingsHash,
  };

  useEffect(() => {
    const onHashChange = () => {
      const section = parseSettingsHash(window.location.hash);
      if (!section) return;
      const nav = settingsNavRef.current;
      if (nav.tab !== "settings") {
        setTab("settings");
        setSettingsSection(section);
        return;
      }
      if (section === nav.settingsSection) return;
      if (!nav.confirmDiscard(nav.settingsSection)) {
        nav.writeSettingsHash(nav.settingsSection);
        return;
      }
      setSettingsSection(section);
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  async function runAction(label: string, fn: () => Promise<unknown>) {
    setError("");
    setStatus(`${label}…`);
    try {
      await fn();
      await refresh();
      setStatus(`${label} OK`);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus("");
    }
  }

  async function onSimulate(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setError("");
    try {
      const result = await api.simulateSell({
        isin: String(form.get("isin") ?? ""),
        quantity: String(form.get("quantity") ?? ""),
        unit_price: String(form.get("unit_price") || "") || undefined,
        fee: String(form.get("fee") || "0"),
      });
      setSimResult(result);
      setStatus("Simulation OK");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  }

  async function onSavePortfolio(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setStatus("Portfolio speichern…");
    try {
      const portfolio = await api.savePortfolioSettings({
        tax_allowance_eur: allowanceDraft.trim() || "1000",
        tax_warn_pct: warnPctDraft.trim() || "0.85",
        risk_free_rate: riskFreeDraft.trim() || "0",
        asset_id_preference: assetIdPrefDraft,
      });
      setPortfolioSettings(portfolio);
      applyPortfolioDrafts(portfolio);
      setStatus("Portfolio gespeichert");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus("");
    }
  }

  async function onSavePaperless(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setStatus("Paperless speichern…");
    try {
      const field_map: Record<string, number | null> = {};
      for (const [role, raw] of Object.entries(fieldMapDraft)) {
        field_map[role] = raw.trim() === "" ? null : Number(raw);
      }
      const saved = await api.savePaperlessSettings({
        field_map,
        sync_tags: syncTagsDraft,
        sync_document_types: syncDocTypesDraft,
        public_url: publicUrlDraft.trim() || null,
      });
      setPaperlessSettings(saved);
      applyPaperlessDrafts(saved);
      setStatus("Paperless gespeichert");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus("");
    }
  }

  async function onSaveGhostfolio(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setStatus("Ghostfolio-Defaults speichern…");
    try {
      const saved = await api.savePaperlessSettings({
        ghostfolio_default_account_id: accountDraft.trim() || null,
        ghostfolio_data_source: dataSourceDraft.trim() || "YAHOO",
      });
      setPaperlessSettings(saved);
      applyPaperlessDrafts(saved);
      setStatus("Ghostfolio-Defaults gespeichert");
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus("");
    }
  }

  async function onTestPaperless() {
    setError("");
    setStatus("Paperless testen…");
    try {
      const result = await api.testPaperless();
      const [fields, tags, types] = await Promise.all([
        api.paperlessCustomFields(),
        api.paperlessTags(),
        api.paperlessDocumentTypes(),
      ]);
      setCustomFields(fields.fields);
      setPaperlessTags(tags.tags);
      setPaperlessDocTypes(types.document_types);
      setStatus(
        `Paperless OK (${result.custom_field_count} Fields, ${result.tag_count ?? tags.tags.length} Tags, ${result.document_type_count ?? types.document_types.length} Typen)`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus("");
    }
  }

  async function onMatchActivities() {
    setError("");
    setStatus("Belege verknüpfen…");
    try {
      const result = await api.stagingMatchActivities();
      await refresh();
      setStatus(
        `Verknüpft ${result.matched}/${result.scanned} · mehrdeutig ${result.ambiguous}, ohne Treffer ${result.unmatched}, übersprungen ${result.skipped}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus("");
    }
  }

  async function runPaperlessSync(mode: "partial" | "full") {
    const hasFilters =
      syncTagsDraft.length > 0 ||
      syncDocTypesDraft.length > 0 ||
      (paperlessSettings?.sync_tags?.length ?? 0) > 0 ||
      (paperlessSettings?.sync_document_types?.length ?? 0) > 0 ||
      Boolean(paperlessSettings?.tag);
    if (mode === "full" && !hasFilters) {
      const ok = window.confirm(
        "Full Sync ohne Tag-/Dokumententyp-Filter. Bei großen Archiven (1000+ Docs) kann das mehrere Minuten dauern. Fortfahren?",
      );
      if (!ok) return;
    }
    setError("");
    setStatus(mode === "full" ? "Full Sync Paperless…" : "Teilsync Paperless…");
    try {
      const done = await api.stagingSync(mode, (event) => {
        if (event.event === "start" && event.warning) {
          setStatus(event.warning);
        } else if (event.event === "page") {
          setStatus(
            `Full Sync… Seite ${event.pages_scanned ?? "?"} · ${event.docs_seen ?? 0} Docs`,
          );
        } else if (event.event === "ingest") {
          setStatus(
            `Importiere Staging… ${event.processed ?? 0}/${event.total ?? "?"} (neu ${event.upserted ?? 0}, skip ${event.skipped ?? 0})`,
          );
        }
      });
      await refresh();
      setStatus(
        `${mode === "full" ? "Full Sync" : "Teilsync"} OK · scanned ${done.scanned ?? 0}, upserted ${done.upserted ?? 0}, skipped ${done.skipped ?? 0}`,
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setStatus("");
    }
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <div className="brand-row">
            <picture>
              <source srcSet="/logo-dark.svg" media="(prefers-color-scheme: dark)" />
              <img
                className="brand-mark"
                src="/logo-light.svg"
                width={36}
                height={36}
                alt=""
              />
            </picture>
            <h1>PortMetrics</h1>
          </div>
          <p className="brand-meta">
            FIFO · PERIODEN · SIMULATOR
            {" · "}
            <a
              className="version-link"
              href={version.repository}
              target="_blank"
              rel="noreferrer"
              title={
                version.built_at || version.git_sha
                  ? [
                      version.built_at ? `Build ${version.built_at}` : null,
                      version.git_sha ? `git ${version.git_sha}` : null,
                      "GitHub Repository",
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  : "GitHub Repository"
              }
            >
              v{version.version}
            </a>
          </p>
        </div>
        <div className="topbar-end">
          <div className="topbar-status" role="status">
            {status && <p className={`status ${error ? "" : "ok"}`}>{status}</p>}
            {error && <p className="status error">{error}</p>}
            {!status && !error && <p className="status">Bereit</p>}
          </div>
          <div className="ops-icons" role="toolbar" aria-label="Wartungsaktionen">
            <button
              type="button"
              className="icon-btn"
              title="Ansicht aktualisieren"
              aria-label="Ansicht aktualisieren"
              onClick={() => void refresh()}
            >
              <Icon name="refresh" />
            </button>
            <button
              type="button"
              className={`icon-btn${showMode ? " active" : ""}`}
              title={showMode ? "Show-Modus aus (Beträge sichtbar)" : "Show-Modus an (Beträge auf 0)"}
              aria-label={showMode ? "Show-Modus deaktivieren" : "Show-Modus aktivieren"}
              aria-pressed={showMode}
              onClick={() => setShowMode((v) => !v)}
            >
              <Icon name={showMode ? "eye-off" : "eye"} />
            </button>
            {OPS_ACTIONS.map((action) => (
              <button
                key={action.id}
                type="button"
                className="icon-btn"
                title={action.label}
                aria-label={action.label}
                onClick={() => void runAction(action.label, action.run)}
              >
                <Icon name={action.icon} />
              </button>
            ))}
          </div>
        </div>
      </header>

      <nav className="nav" aria-label="Hauptnavigation">
        {(
          [
            ["overview", "Overview"],
            ["lots", "FIFO Lots"],
            ["positions", "Positionen"],
            ["staging", "Staging"],
            ["simulator", "Simulator"],
            ["settings", "Einstellungen"],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={tab === id ? "active" : ""}
            onClick={() => requestTabChange(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      {tab === "overview" && overview && (
        <div className="workspace">
          <Panel label="Kennzahlen" meta={`AS OF ${overview.as_of}`}>
            <div className="grid">
              <div className="stat stat-hero" title={METRIC_HINTS.nav}>
                <span>NAV</span>
                <strong className="mono">{money(overview.nav, showMode)}</strong>
              </div>
              <div className="stat" title={METRIC_HINTS.invested}>
                <span>Investiert</span>
                <strong className="mono">{money(overview.invested, showMode)}</strong>
              </div>
              <div className="stat" title={METRIC_HINTS.unrealized}>
                <span>Unrealisiert</span>
                <strong className={`mono ${signedClass(overview.unrealized_gain, showMode)}`}>
                  {money(overview.unrealized_gain, showMode)}
                </strong>
              </div>
              <div className="stat" title={METRIC_HINTS.cagr}>
                <span>CAGR</span>
                <strong className={`mono ${signedClass(overview.cagr.cagr, showMode)}`}>
                  {pct(overview.cagr.cagr, showMode)}
                </strong>
              </div>
              <div className="stat" title={METRIC_HINTS.irr}>
                <span>IRR (MWR)</span>
                <strong className={`mono ${signedClass(overview.mwr?.irr, showMode)}`}>
                  {pct(overview.mwr?.irr, showMode)}
                </strong>
              </div>
              <div className="stat" title={METRIC_HINTS.simple}>
                <span>Einfache Rendite</span>
                <strong className={`mono ${signedClass(overview.mwr?.simple_return, showMode)}`}>
                  {pct(overview.mwr?.simple_return, showMode)}
                </strong>
              </div>
              <div className="stat" title={METRIC_HINTS.maxdd}>
                <span>Max Drawdown</span>
                <strong className={`mono ${signedClass(overview.risk?.max_drawdown, showMode)}`}>
                  {pct(overview.risk?.max_drawdown, showMode)}
                </strong>
              </div>
              <div className="stat" title={METRIC_HINTS.vol}>
                <span>Volatilität</span>
                <strong className="mono">{pct(overview.risk?.volatility, showMode)}</strong>
              </div>
              <div className="stat" title={METRIC_HINTS.sharpe}>
                <span>Sharpe</span>
                <strong className={`mono ${signedClass(overview.risk?.sharpe, showMode)}`}>
                  {ratio(overview.risk?.sharpe, showMode)}
                </strong>
              </div>
              <div className="stat" title={METRIC_HINTS.tax}>
                <span>Freibetrag rest ({overview.tax_allowance?.year ?? "—"})</span>
                <strong
                  className={`mono ${showMode ? "" : overview.tax_allowance?.warn ? "val-neg" : signedClass(overview.tax_allowance?.remaining)}`}
                >
                  {money(overview.tax_allowance?.remaining, showMode)}
                </strong>
              </div>
              <div className="stat" title={METRIC_HINTS.dividends}>
                <span>Dividenden</span>
                <strong className="mono">{money(overview.dividends.total, showMode)}</strong>
              </div>
            </div>
            {overview.tax_allowance?.warn ? (
              <p className="status error" style={{ marginTop: "0.75rem" }}>
                Freibetrag zu {pct(overview.tax_allowance.used_pct, showMode)} ausgeschöpft (Warnschwelle{" "}
                {pct(overview.tax_allowance.warn_pct, showMode)}) — realisiert YTD{" "}
                {money(overview.tax_allowance.realized_ytd, showMode)} /{" "}
                {money(overview.tax_allowance.allowance, showMode)}.
              </p>
            ) : null}
          </Panel>
          <Panel label="Perioden-Rendite">
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Periode</th>
                    <th>Von</th>
                    <th>Bis</th>
                    <th>Rendite</th>
                  </tr>
                </thead>
                <tbody>
                  {overview.periods.map((p) => (
                    <tr key={p.label}>
                      <td>{p.label}</td>
                      <td className="mono">{p.start_date}</td>
                      <td className="mono">{p.end_date}</td>
                      <td className={`mono ${signedClass(p.period_return, showMode)}`}>
                        {pct(p.period_return, showMode)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>
          {overview.cashflows && overview.cashflows.length > 0 ? (
            <Panel label="Cashflow-Timeline" meta={`${overview.cashflows.length} FLOWS`} offset>
              <div className="table-wrap">
                <table>
                  <thead>
                    <tr>
                      <SortHeader
                        label="Datum"
                        column="date"
                        sort={cashflowSort}
                        onSort={(column) => setCashflowSort((s) => toggleSort(s, column))}
                      />
                      <SortHeader
                        label="Betrag"
                        column="amount"
                        sort={cashflowSort}
                        onSort={(column) => setCashflowSort((s) => toggleSort(s, column))}
                      />
                    </tr>
                  </thead>
                  <tbody>
                    {sortRows(overview.cashflows, cashflowSort).map((cf, idx) => (
                      <tr key={`${cf.date}-${idx}`}>
                        <td className="mono">{cf.date}</td>
                        <td className={`mono ${signedClass(cf.amount, showMode)}`}>
                          {money(cf.amount, showMode)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          ) : null}
        </div>
      )}

      {tab === "lots" && (
        <Panel label="FIFO Lots" meta={`${lots.length} ZEILEN`}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <SortHeader
                    label={assetIdColumnLabel(portfolioSettings?.asset_id_preference)}
                    column="display_id"
                    sort={lotsSort}
                    onSort={(column) => setLotsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="Datum"
                    column="open_date"
                    sort={lotsSort}
                    onSort={(column) => setLotsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="Status"
                    column="status"
                    sort={lotsSort}
                    onSort={(column) => setLotsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="Menge"
                    column="open_qty"
                    sort={lotsSort}
                    onSort={(column) => setLotsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="Einstand"
                    column="unit_cost"
                    sort={lotsSort}
                    onSort={(column) => setLotsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="Marktkurs"
                    column="mark_price"
                    sort={lotsSort}
                    onSort={(column) => setLotsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="u. Gewinn"
                    column="unrealized_gain"
                    sort={lotsSort}
                    onSort={(column) => setLotsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="u. %"
                    column="unrealized_gain_pct"
                    sort={lotsSort}
                    onSort={(column) => setLotsSort((s) => toggleSort(s, column))}
                  />
                  <th>Beleg</th>
                </tr>
              </thead>
              <tbody>
                {sortRows(lots, lotsSort).map((lot) => (
                  <tr key={lot.id}>
                    <td className="mono">{lot.display_id ?? lot.isin}</td>
                    <td className="mono">{lot.open_date}</td>
                    <td>{lot.status}</td>
                    <td className="mono">{qty(lot.open_qty, showMode)}</td>
                    <td className="mono">{money(lot.unit_cost, showMode)}</td>
                    <td className="mono">{money(lot.mark_price, showMode)}</td>
                    <td className={`mono ${signedClass(lot.unrealized_gain, showMode)}`}>
                      {money(lot.unrealized_gain, showMode)}
                    </td>
                    <td className={`mono ${signedClass(lot.unrealized_gain_pct, showMode)}`}>
                      {pctPoints(lot.unrealized_gain_pct, showMode)}
                    </td>
                    <td>
                      {lot.paperless_doc_id != null ? (
                        <div className="doc-cell">
                          <span className="mono">{lot.paperless_doc_id}</span>
                          {paperlessSettings?.document_base_url ? (
                            <a
                              className="doc-link"
                              href={`${paperlessSettings.document_base_url}/documents/${lot.paperless_doc_id}`}
                              target="_blank"
                              rel="noreferrer"
                              title={`Paperless Dokument #${lot.paperless_doc_id}`}
                              aria-label={`Paperless Dokument ${lot.paperless_doc_id} öffnen`}
                            >
                              <Icon name="paperless" />
                            </a>
                          ) : null}
                        </div>
                      ) : (
                        <span className="muted">—</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {tab === "positions" && overview && (
        <Panel label="Positionen" meta={`${overview.positions.length} ZEILEN`}>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <SortHeader
                    label={assetIdColumnLabel(portfolioSettings?.asset_id_preference)}
                    column="display_id"
                    sort={positionsSort}
                    onSort={(column) => setPositionsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="Menge"
                    column="open_qty"
                    sort={positionsSort}
                    onSort={(column) => setPositionsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="Investiert"
                    column="invested"
                    sort={positionsSort}
                    onSort={(column) => setPositionsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="Marktwert"
                    column="market_value"
                    sort={positionsSort}
                    onSort={(column) => setPositionsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="Einfache Rendite"
                    column="simple_return"
                    sort={positionsSort}
                    onSort={(column) => setPositionsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="IRR"
                    column="irr"
                    sort={positionsSort}
                    onSort={(column) => setPositionsSort((s) => toggleSort(s, column))}
                  />
                  <SortHeader
                    label="Max DD"
                    column="max_drawdown"
                    sort={positionsSort}
                    onSort={(column) => setPositionsSort((s) => toggleSort(s, column))}
                  />
                </tr>
              </thead>
              <tbody>
                {sortRows(overview.positions, positionsSort).map((p) => (
                  <tr key={p.isin}>
                    <td className="mono">{p.display_id ?? p.isin}</td>
                    <td className="mono">{qty(p.open_qty, showMode)}</td>
                    <td className="mono">{money(p.invested, showMode)}</td>
                    <td className="mono">{money(p.market_value, showMode)}</td>
                    <td className={`mono ${signedClass(p.simple_return, showMode)}`}>
                      {pct(p.simple_return, showMode)}
                    </td>
                    <td className={`mono ${signedClass(p.irr, showMode)}`}>
                      {pct(p.irr, showMode)}
                    </td>
                    <td className={`mono ${signedClass(p.max_drawdown, showMode)}`}>
                      {pct(p.max_drawdown, showMode)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {tab === "staging" && (
        <Panel label="Staging Queue" meta={`${staging.length} OFFEN`}>
            <p className="muted">
              Offene Review-Queue aus Paperless. Confirm importiert nach Ghostfolio; danach Sync
              ausführen. Erledigte Einträge (confirm/reject) erscheinen nicht mehr — auch nicht bei
              erneutem Webhook. Typ OTHER ist sichtbar, aber nicht importierbar.
            </p>
            <div className="settings-actions" style={{ marginBottom: "0.75rem" }}>
              <button type="button" onClick={() => void runPaperlessSync("partial")}>
                Teilsync (≤100)
              </button>
              <button type="button" onClick={() => void runPaperlessSync("full")}>
                Full Sync
              </button>
            </div>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Doc</th>
                  <th>Status</th>
                  <th>Typ</th>
                  <th>ISIN</th>
                  <th>Menge</th>
                  <th>Kurs</th>
                  <th>Datum</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {staging.map((item) => {
                  const importable =
                    item.payload.importable !== false && item.payload.wp_typ !== "OTHER";
                  return (
                  <tr key={item.id}>
                    <td className="mono">{item.id}</td>
                    <td>
                      <div className="doc-cell">
                        <span className="mono">{item.paperless_doc_id}</span>
                        {paperlessSettings?.document_base_url ? (
                          <a
                            className="doc-link"
                            href={`${paperlessSettings.document_base_url}/documents/${item.paperless_doc_id}`}
                            target="_blank"
                            rel="noreferrer"
                            title={`Paperless Dokument #${item.paperless_doc_id}`}
                            aria-label={`Paperless Dokument ${item.paperless_doc_id} öffnen`}
                          >
                            <Icon name="paperless" />
                          </a>
                        ) : null}
                      </div>
                    </td>
                    <td>{item.status}</td>
                    <td>{item.payload.wp_typ ?? "—"}</td>
                    <td className="mono">{item.payload.isin ?? item.payload.symbol ?? "—"}</td>
                    <td className="mono">{qty(item.payload.quantity, showMode)}</td>
                    <td className="mono">{money(item.payload.unit_price, showMode)}</td>
                    <td className="mono">{item.payload.trade_date ?? "—"}</td>
                    <td className="row-actions">
                      <button
                        type="button"
                        className="primary"
                        disabled={item.status === "imported" || !importable}
                        title={
                          importable
                            ? undefined
                            : "Typ OTHER / nicht importierbar — in Paperless korrigieren"
                        }
                        onClick={() =>
                          void runAction(`Confirm #${item.id}`, () => api.stagingConfirm(item.id))
                        }
                      >
                        Confirm
                      </button>
                      <button
                        type="button"
                        disabled={item.status === "imported" || item.status === "rejected"}
                        onClick={() =>
                          void runAction(`Reject #${item.id}`, () => api.stagingReject(item.id))
                        }
                      >
                        Reject
                      </button>
                    </td>
                  </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          {staging.length === 0 && <p className="muted">Keine offenen Staging-Einträge.</p>}
        </Panel>
      )}

      {tab === "simulator" && (
        <div className="workspace workspace-sim">
          <Panel label="What-If Verkauf">
            <form className="form" onSubmit={onSimulate}>
              <label>
                ISIN / Asset-Key
                <input name="isin" required placeholder="IE00BK5BQT80" />
              </label>
              <label>
                Stückzahl
                <input name="quantity" required placeholder="10" />
              </label>
              <label>
                Kurs (optional)
                <input name="unit_price" placeholder="aktueller Marktkurs" />
              </label>
              <label>
                Gebühr
                <input name="fee" defaultValue="0" />
              </label>
              <button className="primary" type="submit">
                Simulieren
              </button>
            </form>
          </Panel>
          <Panel label="Ergebnis" offset>
            {simResult ? (
              <div className="sim-result">
                <p>
                  Realisierter Gewinn:{" "}
                  <strong className={`mono ${signedClass(String(simResult.realized_gain), showMode)}`}>
                    {money(String(simResult.realized_gain), showMode)}
                  </strong>
                </p>
                <p>
                  Geschätzte Steuer:{" "}
                  <strong className="mono">
                    {money(String(simResult.estimated_tax), showMode)}
                  </strong>
                </p>
                <p>
                  Nach Steuer:{" "}
                  <strong className={`mono ${signedClass(String(simResult.net_after_tax), showMode)}`}>
                    {money(String(simResult.net_after_tax), showMode)}
                  </strong>
                </p>
                <pre className="mono">
                  {showMode
                    ? "[Show-Modus aktiv — Lot-Details ausgeblendet]"
                    : JSON.stringify(simResult.lots, null, 2)}
                </pre>
              </div>
            ) : (
              <p className="muted">Noch keine Simulation — Parameter links ausfüllen.</p>
            )}
          </Panel>
        </div>
      )}

      {tab === "settings" && (
        <div className="settings-workspace">
          <nav className="nav subnav" aria-label="Einstellungen">
            {SETTINGS_SECTIONS.map((section) => (
              <button
                key={section.id}
                type="button"
                className={settingsSection === section.id ? "active" : ""}
                onClick={() => requestSettingsSection(section.id)}
              >
                {section.label}
              </button>
            ))}
          </nav>

          {settingsSection === "ops" && (
            <Panel label="Wartung / Ops">
              <p className="muted">
                Server-Jobs zum Nachziehen und Neuaufbauen. Dieselben Aktionen liegen als kleine Icons
                rechts in der Topbar — hier mit Labels und Kurzhinweisen. Full Sync Paperless bleibt
                unter Staging (alle Seiten); hier nur Teilsync.
              </p>
              <div className="ops-list">
                {OPS_ACTIONS.map((action) => (
                  <div key={action.id} className="ops-row">
                    <div className="ops-copy">
                      <strong>{action.label}</strong>
                      <span className="muted">{action.hint}</span>
                    </div>
                    <button
                      type="button"
                      onClick={() => void runAction(action.label, action.run)}
                    >
                      Ausführen
                    </button>
                  </div>
                ))}
              </div>
              <p className="muted" style={{ marginTop: "0.75rem" }}>
                Full Sync inkl. Fortschritt:{" "}
                <button
                  type="button"
                  className="linkish"
                  onClick={() => requestTabChange("staging")}
                >
                  Staging öffnen
                </button>
                .
              </p>
            </Panel>
          )}

          {settingsSection === "portfolio" && (
            <Panel label="Portfolio / Steuer & Risiko">
              <p className="muted">
                Freibetrag, risikofreier Zins für Sharpe und Anzeige-Kennung (Symbol/WKN/ISIN) für Lots
                und Positionen. Werte sind Schätzungen — keine Steuerberatung
                {portfolioSettings
                  ? ` (aktuell Freibetrag ${showMode ? "0,00" : portfolioSettings.tax_allowance_eur} EUR).`
                  : "."}
              </p>
              <form className="form form-wide" onSubmit={(e) => void onSavePortfolio(e)}>
                <label>
                  Steuer-Freibetrag (EUR / Jahr)
                  <input
                    value={allowanceDraft}
                    onChange={(e) => setAllowanceDraft(e.target.value)}
                    placeholder="1000"
                  />
                </label>
                <label>
                  Warnschwelle (0–1, z.B. 0.85 = 85%)
                  <input
                    value={warnPctDraft}
                    onChange={(e) => setWarnPctDraft(e.target.value)}
                    placeholder="0.85"
                  />
                </label>
                <label>
                  Risikofreier Zins (annualisiert, z.B. 0.02)
                  <input
                    value={riskFreeDraft}
                    onChange={(e) => setRiskFreeDraft(e.target.value)}
                    placeholder="0"
                  />
                </label>
                <label>
                  Kennung in Lots / Positionen
                  <select
                    value={assetIdPrefDraft}
                    onChange={(e) =>
                      setAssetIdPrefDraft(e.target.value as "symbol" | "wkn" | "isin")
                    }
                  >
                    <option value="symbol">Symbol (Ghostfolio-Standard)</option>
                    <option value="wkn">WKN (aus Paperless-Mapping)</option>
                    <option value="isin">ISIN</option>
                  </select>
                  <span className="muted">
                    Fallback-Kette: gewählte Kennung → Symbol/ISIN/WKN → Asset-Key. WKN wird gelernt,
                    sobald ein Paperless-Beleg ISIN und WKN enthält.
                  </span>
                </label>
                <button className="primary" type="submit">
                  Speichern
                </button>
              </form>
            </Panel>
          )}

          {settingsSection === "paperless" && (
            <Panel label="Paperless">
              <p className="muted">
                Custom-Fields den PortMetrics-Rollen zuordnen. API-URL/Token/Webhook-Secret bleiben in
                der Env; Mapping, Sync-Filter und öffentliche Web-URL speichern in der Datenbank.
                Handelsdatum = Dokumentdatum in Paperless; Währung kommt aus den Monetary-Feldern.
              </p>
              {paperlessSettings && (
                <p className="muted">
                  Webhook: <span className="mono">{paperlessSettings.webhook_path}</span>
                  {" · "}
                  Secret:{" "}
                  {paperlessSettings.webhook_secret_configured ? "konfiguriert" : "fehlt (Env)"}
                  {" · "}
                  Scheduler-Pull:{" "}
                  {paperlessSettings.paperless_sync_interval_minutes > 0
                    ? `alle ${paperlessSettings.paperless_sync_interval_minutes} Min`
                    : "aus"}
                </p>
              )}
              {paperlessSettings && !paperlessSettings.paperless_configured && (
                <p className="status error">
                  PAPERLESS_URL / PAPERLESS_TOKEN sind nicht konfiguriert — Custom Fields können nicht
                  geladen werden.
                </p>
              )}
              <form className="form form-filters" onSubmit={(e) => void onSavePaperless(e)}>
                <div className="settings-actions">
                  <button type="button" onClick={() => void onTestPaperless()}>
                    Verbindung testen
                  </button>
                  <button type="button" onClick={() => void loadSettings()}>
                    Neu laden
                  </button>
                  <button type="button" onClick={() => void onMatchActivities()}>
                    Belege mit Ghostfolio verknüpfen
                  </button>
                </div>
                <p className="muted">
                  Verknüpfen ist manuell: offene Staging-Einträge werden per Typ + ISIN + Datum +
                  Stückzahl an bestehende Activities gematcht (Kurs nur als Tie-Breaker). Kein
                  erneuter Ghostfolio-Import. Mehrdeutige bleiben in der Queue.
                </p>
                {(paperlessSettings?.role_meta ?? FALLBACK_ROLE_META).map((meta) => (
                  <label key={meta.role}>
                    {meta.label}
                    <span className="muted">
                      {" "}
                      — {meta.required ? "Pflicht" : "Optional"}
                      {meta.hint ? ` · ${meta.hint}` : ""}
                    </span>
                    <select
                      value={fieldMapDraft[meta.role] ?? ""}
                      onChange={(e) =>
                        setFieldMapDraft((prev) => ({ ...prev, [meta.role]: e.target.value }))
                      }
                    >
                      <option value="">— nicht zugeordnet —</option>
                      {customFields.map((field) => (
                        <option key={field.id} value={String(field.id)}>
                          {field.name ?? `Field #${field.id}`} (#{field.id})
                        </option>
                      ))}
                    </select>
                  </label>
                ))}
                {paperlessSettings?.notes && (
                  <p className="muted">{Object.values(paperlessSettings.notes).join(" · ")}</p>
                )}
                <label>
                  Paperless Web-URL (Browser)
                  <input
                    value={publicUrlDraft}
                    onChange={(e) => setPublicUrlDraft(e.target.value)}
                    placeholder="https://paperless.example.com"
                  />
                  <span className="muted">
                    Für Doc-Links in Staging und FIFO-Lots. Fallback: PAPERLESS_URL aus Env
                    {paperlessSettings?.document_base_url
                      ? ` (aktuell ${paperlessSettings.document_base_url})`
                      : ""}
                    .
                  </span>
                </label>
                <fieldset className="filter-fieldset">
                  <legend>Sync-Filter (Tags / Dokumententypen)</legend>
                  <p className="muted">
                    Mehrere Tags = ODER, mehrere Dokumententypen = ODER; Tags und Typen zusammen =
                    UND. Speicherung als ID (+ Name zur Anzeige). Teilsync: neueste ≤100 (auch ohne
                    Filter). Full Sync: alle Seiten — ohne Filter erscheint eine Warnung. Webhook
                    nutzt diesen Filter nicht, prüft aber weiterhin Pflichtfelder.
                  </p>
                  {paperlessSettings?.tag ? (
                    <p className="muted">
                      Legacy-Tag aus Env/Altbestand:{" "}
                      <span className="mono">{paperlessSettings.tag}</span> (wird beim Speichern der
                      ID-Filter abgelöst).
                    </p>
                  ) : null}
                  <div className="filter-grid">
                    <SyncFilterPicker
                      label="Tags"
                      items={paperlessTags}
                      selected={syncTagsDraft}
                      onChange={setSyncTagsDraft}
                      emptyHint="Keine Tags geladen — Verbindung testen."
                    />
                    <SyncFilterPicker
                      label="Dokumententypen"
                      items={paperlessDocTypes}
                      selected={syncDocTypesDraft}
                      onChange={setSyncDocTypesDraft}
                      emptyHint="Keine Typen geladen — Verbindung testen."
                    />
                  </div>
                </fieldset>
                <button className="primary" type="submit">
                  Speichern
                </button>
              </form>
            </Panel>
          )}

          {settingsSection === "ghostfolio" && (
            <Panel label="Ghostfolio">
              <p className="muted">
                Defaults für den Paperless→Ghostfolio-Import (Account und Kursquelle). Speichern
                schreibt weiterhin in die Paperless-Settings (kein eigener Backend-Key).
              </p>
              <form className="form form-wide" onSubmit={(e) => void onSaveGhostfolio(e)}>
                <label>
                  Ghostfolio Default Account-ID
                  <input
                    value={accountDraft}
                    onChange={(e) => setAccountDraft(e.target.value)}
                    placeholder="UUID"
                  />
                </label>
                <label>
                  Ghostfolio Data Source
                  <input
                    value={dataSourceDraft}
                    onChange={(e) => setDataSourceDraft(e.target.value)}
                    placeholder="YAHOO"
                  />
                </label>
                <button className="primary" type="submit">
                  Speichern
                </button>
              </form>
            </Panel>
          )}
        </div>
      )}
    </div>
  );
}
