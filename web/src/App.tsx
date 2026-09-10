import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import {
  api,
  Lot,
  Overview,
  PaperlessField,
  PaperlessSettings,
  PortfolioSettings,
  StagingItem,
  VersionInfo,
} from "./api";

type Tab = "overview" | "lots" | "positions" | "simulator" | "staging" | "settings";

const FALLBACK_VERSION: VersionInfo = {
  name: "PortMetrics",
  version: "0.2.0",
  repository: "https://github.com/MrMoep/PortMetrics",
};

const ROLE_LABELS: Record<string, string> = {
  type: "Typ (BUY/SELL/…)",
  isin: "ISIN",
  symbol: "Symbol",
  quantity: "Stückzahl",
  unit_price: "Kurs",
  fee: "Gebühr",
  trade_date: "Handelsdatum",
  currency: "Währung",
  import_status: "Import-Status",
  activity_id: "Ghostfolio Activity-ID",
};

function pct(value: string | null | undefined): string {
  if (value == null) return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return `${(n * 100).toFixed(2)} %`;
}

function money(value: string | null | undefined): string {
  if (value == null) return "—";
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function signedClass(value: string | number | null | undefined): string {
  if (value == null || value === "") return "";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n) || n === 0) return "";
  return n > 0 ? "val-pos" : "val-neg";
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

type IconName = "sync" | "fifo" | "metrics" | "paperless" | "refresh";

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
    label: "Sync Paperless",
    hint: "Belege pullen und Staging-Queue aktualisieren.",
    icon: "paperless",
    run: () => api.stagingSync(),
  },
];

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
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
  const [fieldMapDraft, setFieldMapDraft] = useState<Record<string, string>>({});
  const [tagDraft, setTagDraft] = useState("");
  const [accountDraft, setAccountDraft] = useState("");
  const [dataSourceDraft, setDataSourceDraft] = useState("YAHOO");
  const [allowanceDraft, setAllowanceDraft] = useState("1000");
  const [warnPctDraft, setWarnPctDraft] = useState("0.85");
  const [riskFreeDraft, setRiskFreeDraft] = useState("0");

  const refresh = useCallback(async () => {
    setError("");
    try {
      const [ov, lotData, stagingData, versionInfo] = await Promise.all([
        api.overview(),
        api.lots(),
        api.staging(),
        api.version().catch(() => FALLBACK_VERSION),
      ]);
      setOverview(ov);
      setLots(lotData.lots);
      setStaging(stagingData.items);
      setVersion(versionInfo);
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
      setTagDraft(cfg.tag ?? "");
      setAccountDraft(cfg.ghostfolio_default_account_id ?? "");
      setDataSourceDraft(cfg.ghostfolio_data_source || "YAHOO");
      setAllowanceDraft(portfolio.tax_allowance_eur);
      setWarnPctDraft(portfolio.tax_warn_pct);
      setRiskFreeDraft(portfolio.risk_free_rate);
      if (cfg.paperless_configured) {
        try {
          const fields = await api.paperlessCustomFields();
          setCustomFields(fields.fields);
        } catch {
          setCustomFields([]);
        }
      } else {
        setCustomFields([]);
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

  async function onSaveSettings(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setStatus("Einstellungen speichern…");
    try {
      const field_map: Record<string, number | null> = {};
      for (const [role, raw] of Object.entries(fieldMapDraft)) {
        field_map[role] = raw.trim() === "" ? null : Number(raw);
      }
      const [saved, portfolio] = await Promise.all([
        api.savePaperlessSettings({
          field_map,
          tag: tagDraft.trim() || null,
          ghostfolio_default_account_id: accountDraft.trim() || null,
          ghostfolio_data_source: dataSourceDraft.trim() || "YAHOO",
        }),
        api.savePortfolioSettings({
          tax_allowance_eur: allowanceDraft.trim() || "1000",
          tax_warn_pct: warnPctDraft.trim() || "0.85",
          risk_free_rate: riskFreeDraft.trim() || "0",
        }),
      ]);
      setPaperlessSettings(saved);
      setPortfolioSettings(portfolio);
      setStatus("Einstellungen gespeichert");
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
      const fields = await api.paperlessCustomFields();
      setCustomFields(fields.fields);
      setStatus(`Paperless OK (${result.custom_field_count} Custom Fields)`);
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
        <div className="ops-icons" role="toolbar" aria-label="Wartungsaktionen">
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
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </nav>

      <div className="status-bar" role="status">
        <div className="status-bar-main">
          {status && <p className={`status ${error ? "" : "ok"}`}>{status}</p>}
          {error && <p className="status error">{error}</p>}
          {!status && !error && <p className="status">Bereit</p>}
        </div>
        <button
          type="button"
          className="icon-btn icon-btn-on-panel"
          title="Ansicht aktualisieren"
          aria-label="Ansicht aktualisieren"
          onClick={() => void refresh()}
        >
          <Icon name="refresh" />
        </button>
      </div>

      {tab === "overview" && overview && (
        <div className="workspace">
          <Panel label="Kennzahlen" meta={`AS OF ${overview.as_of}`}>
            <div className="grid">
              <div className="stat stat-hero">
                <span>NAV</span>
                <strong className="mono">{money(overview.nav)}</strong>
              </div>
              <div className="stat">
                <span>Investiert</span>
                <strong className="mono">{money(overview.invested)}</strong>
              </div>
              <div className="stat">
                <span>Unrealisiert</span>
                <strong className={`mono ${signedClass(overview.unrealized_gain)}`}>
                  {money(overview.unrealized_gain)}
                </strong>
              </div>
              <div className="stat">
                <span>CAGR</span>
                <strong className={`mono ${signedClass(overview.cagr.cagr)}`}>
                  {pct(overview.cagr.cagr)}
                </strong>
              </div>
              <div className="stat">
                <span>IRR (MWR)</span>
                <strong className={`mono ${signedClass(overview.mwr?.irr)}`}>
                  {pct(overview.mwr?.irr)}
                </strong>
              </div>
              <div className="stat">
                <span>Einfache Rendite</span>
                <strong className={`mono ${signedClass(overview.mwr?.simple_return)}`}>
                  {pct(overview.mwr?.simple_return)}
                </strong>
              </div>
              <div className="stat">
                <span>Max Drawdown</span>
                <strong className={`mono ${signedClass(overview.risk?.max_drawdown)}`}>
                  {pct(overview.risk?.max_drawdown)}
                </strong>
              </div>
              <div className="stat">
                <span>Volatilität</span>
                <strong className="mono">{pct(overview.risk?.volatility)}</strong>
              </div>
              <div className="stat">
                <span>Sharpe</span>
                <strong className={`mono ${signedClass(overview.risk?.sharpe)}`}>
                  {overview.risk?.sharpe == null ? "—" : Number(overview.risk.sharpe).toFixed(2)}
                </strong>
              </div>
              <div className="stat">
                <span>Freibetrag rest ({overview.tax_allowance?.year ?? "—"})</span>
                <strong
                  className={`mono ${overview.tax_allowance?.warn ? "val-neg" : signedClass(overview.tax_allowance?.remaining)}`}
                >
                  {money(overview.tax_allowance?.remaining)}
                </strong>
              </div>
              <div className="stat">
                <span>Dividenden</span>
                <strong className="mono">{money(overview.dividends.total)}</strong>
              </div>
            </div>
            {overview.tax_allowance?.warn ? (
              <p className="status error" style={{ marginTop: "0.75rem" }}>
                Freibetrag zu {pct(overview.tax_allowance.used_pct)} ausgeschöpft (Warnschwelle{" "}
                {pct(overview.tax_allowance.warn_pct)}) — realisiert YTD{" "}
                {money(overview.tax_allowance.realized_ytd)} / {money(overview.tax_allowance.allowance)}.
              </p>
            ) : null}
          </Panel>
          <Panel label="Perioden-Rendite" offset>
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
                      <td className={`mono ${signedClass(p.period_return)}`}>
                        {pct(p.period_return)}
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
                      <th>Datum</th>
                      <th>Betrag</th>
                    </tr>
                  </thead>
                  <tbody>
                    {overview.cashflows.map((cf, idx) => (
                      <tr key={`${cf.date}-${idx}`}>
                        <td className="mono">{cf.date}</td>
                        <td className={`mono ${signedClass(cf.amount)}`}>{money(cf.amount)}</td>
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
                  <th>ISIN</th>
                  <th>Datum</th>
                  <th>Status</th>
                  <th>Menge</th>
                  <th>Einstand</th>
                  <th>Marktkurs</th>
                  <th>u. Gewinn</th>
                  <th>u. %</th>
                </tr>
              </thead>
              <tbody>
                {lots.map((lot) => (
                  <tr key={lot.id}>
                    <td className="mono">{lot.isin}</td>
                    <td className="mono">{lot.open_date}</td>
                    <td>{lot.status}</td>
                    <td className="mono">{lot.open_qty}</td>
                    <td className="mono">{money(lot.unit_cost)}</td>
                    <td className="mono">{money(lot.mark_price)}</td>
                    <td className={`mono ${signedClass(lot.unrealized_gain)}`}>
                      {money(lot.unrealized_gain)}
                    </td>
                    <td className={`mono ${signedClass(lot.unrealized_gain_pct)}`}>
                      {lot.unrealized_gain_pct == null ? "—" : `${lot.unrealized_gain_pct} %`}
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
                  <th>ISIN</th>
                  <th>Menge</th>
                  <th>Investiert</th>
                  <th>Marktwert</th>
                  <th>Einfache Rendite</th>
                  <th>IRR</th>
                  <th>Max DD</th>
                </tr>
              </thead>
              <tbody>
                {overview.positions.map((p) => (
                  <tr key={p.isin}>
                    <td className="mono">{p.isin}</td>
                    <td className="mono">{p.open_qty}</td>
                    <td className="mono">{money(p.invested)}</td>
                    <td className="mono">{money(p.market_value)}</td>
                    <td className={`mono ${signedClass(p.simple_return)}`}>
                      {pct(p.simple_return)}
                    </td>
                    <td className={`mono ${signedClass(p.irr)}`}>{pct(p.irr)}</td>
                    <td className={`mono ${signedClass(p.max_drawdown)}`}>
                      {pct(p.max_drawdown)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {tab === "staging" && (
        <Panel label="Staging Queue" meta={`${staging.length} EINTRÄGE`}>
          <p className="muted">
            Review-Queue aus Paperless. Confirm importiert nach Ghostfolio; danach Sync ausführen.
          </p>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>ID</th>
                  <th>Doc</th>
                  <th>Status</th>
                  <th>Typ</th>
                  <th>Symbol</th>
                  <th>Menge</th>
                  <th>Kurs</th>
                  <th>Datum</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {staging.map((item) => (
                  <tr key={item.id}>
                    <td className="mono">{item.id}</td>
                    <td className="mono">{item.paperless_doc_id}</td>
                    <td>{item.status}</td>
                    <td>{item.payload.wp_typ ?? "—"}</td>
                    <td className="mono">{item.payload.symbol ?? item.payload.isin ?? "—"}</td>
                    <td className="mono">{item.payload.quantity ?? "—"}</td>
                    <td className="mono">{money(item.payload.unit_price)}</td>
                    <td className="mono">{item.payload.trade_date ?? "—"}</td>
                    <td className="row-actions">
                      <button
                        type="button"
                        className="primary"
                        disabled={item.status === "imported"}
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
                ))}
              </tbody>
            </table>
          </div>
          {staging.length === 0 && <p className="muted">Keine Staging-Einträge.</p>}
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
                  <strong className={`mono ${signedClass(String(simResult.realized_gain))}`}>
                    {money(String(simResult.realized_gain))}
                  </strong>
                </p>
                <p>
                  Geschätzte Steuer:{" "}
                  <strong className="mono">{money(String(simResult.estimated_tax))}</strong>
                </p>
                <p>
                  Nach Steuer:{" "}
                  <strong className={`mono ${signedClass(String(simResult.net_after_tax))}`}>
                    {money(String(simResult.net_after_tax))}
                  </strong>
                </p>
                <pre className="mono">{JSON.stringify(simResult.lots, null, 2)}</pre>
              </div>
            ) : (
              <p className="muted">Noch keine Simulation — Parameter links ausfüllen.</p>
            )}
          </Panel>
        </div>
      )}

      {tab === "settings" && (
        <>
          <Panel label="Wartung / Ops">
            <p className="muted">
              Server-Jobs zum Nachziehen und Neuaufbauen. Dieselben Aktionen liegen als kleine Icons
              rechts in der Topbar — hier mit Labels und Kurzhinweisen.
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
          </Panel>
          <Panel label="Portfolio / Steuer & Risiko">
            <p className="muted">
              Freibetrag und risikofreier Zins für Sharpe. Werte sind Schätzungen — keine Steuerberatung.
              Speichern unten speichert Paperless- und Portfolio-Settings gemeinsam
              {portfolioSettings
                ? ` (aktuell Freibetrag ${portfolioSettings.tax_allowance_eur} EUR).`
                : "."}
            </p>
          </Panel>
          <Panel label="Einstellungen / Paperless">
            <p className="muted">
              Paperless-Custom-Fields den PortMetrics-Rollen zuordnen. URL/Token/Webhook-Secret bleiben
              in der Env; Mapping, Tag und Ghostfolio-Defaults werden in der Datenbank gespeichert.
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
            <form className="form form-wide" onSubmit={(e) => void onSaveSettings(e)}>
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
              <div className="settings-actions">
                <button type="button" onClick={() => void onTestPaperless()}>
                  Verbindung testen
                </button>
                <button type="button" onClick={() => void loadSettings()}>
                  Neu laden
                </button>
              </div>
              {(paperlessSettings?.roles ?? []).map((role) => (
                <label key={role}>
                  {ROLE_LABELS[role] ?? role}
                  <select
                    value={fieldMapDraft[role] ?? ""}
                    onChange={(e) =>
                      setFieldMapDraft((prev) => ({ ...prev, [role]: e.target.value }))
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
              <label>
                Paperless-Tag (optional)
                <input
                  value={tagDraft}
                  onChange={(e) => setTagDraft(e.target.value)}
                  placeholder="wertpapier"
                />
              </label>
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
        </>
      )}
    </div>
  );
}
