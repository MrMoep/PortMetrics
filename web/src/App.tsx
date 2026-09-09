import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, Lot, Overview, StagingItem, VersionInfo } from "./api";

type Tab = "overview" | "lots" | "positions" | "simulator" | "staging";

const FALLBACK_VERSION: VersionInfo = {
  name: "PortMetrics",
  version: "0.1.0",
  repository: "https://github.com/MrMoep/PortMetrics",
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

export default function App() {
  const [tab, setTab] = useState<Tab>("overview");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [lots, setLots] = useState<Lot[]>([]);
  const [staging, setStaging] = useState<StagingItem[]>([]);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [simResult, setSimResult] = useState<Record<string, unknown> | null>(null);
  const [version, setVersion] = useState<VersionInfo>(FALLBACK_VERSION);

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

  useEffect(() => {
    void refresh();
  }, [refresh]);

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

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <h1>PortMetrics</h1>
          <p>
            FIFO-Lots, Perioden-Rendite, Verkaufs-Simulator
            {" · "}
            <a
              className="version-link"
              href={version.repository}
              target="_blank"
              rel="noreferrer"
              title="GitHub Repository"
            >
              v{version.version}
            </a>
          </p>
        </div>
        <div className="actions">
          <button type="button" onClick={() => void runAction("Sync", api.sync)}>
            Sync Ghostfolio
          </button>
          <button type="button" onClick={() => void runAction("FIFO", api.rebuildFifo)}>
            Rebuild FIFO
          </button>
          <button type="button" onClick={() => void runAction("Metrics", api.rebuildMetrics)}>
            Rebuild Metrics
          </button>
          <button type="button" onClick={() => void runAction("Paperless", api.stagingSync)}>
            Sync Paperless
          </button>
          <button type="button" className="primary" onClick={() => void refresh()}>
            Aktualisieren
          </button>
        </div>
      </header>

      <nav className="nav">
        {(
          [
            ["overview", "Overview"],
            ["lots", "FIFO Lots"],
            ["positions", "Positionen"],
            ["staging", "Staging"],
            ["simulator", "Simulator"],
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

      {status && <p className={`status ${error ? "" : "ok"}`}>{status}</p>}
      {error && <p className="status error">{error}</p>}

      {tab === "overview" && overview && (
        <section className="panel">
          <div className="grid">
            <div className="stat">
              <span>NAV</span>
              <strong>{money(overview.nav)}</strong>
            </div>
            <div className="stat">
              <span>Investiert</span>
              <strong>{money(overview.invested)}</strong>
            </div>
            <div className="stat">
              <span>Unrealisiert</span>
              <strong>{money(overview.unrealized_gain)}</strong>
            </div>
            <div className="stat">
              <span>CAGR</span>
              <strong>{pct(overview.cagr.cagr)}</strong>
            </div>
            <div className="stat">
              <span>Dividenden</span>
              <strong>{money(overview.dividends.total)}</strong>
            </div>
          </div>
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
                  <td className="mono">{pct(p.period_return)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === "lots" && (
        <section className="panel">
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
                  <td className="mono">{money(lot.unrealized_gain)}</td>
                  <td className="mono">
                    {lot.unrealized_gain_pct == null ? "—" : `${lot.unrealized_gain_pct} %`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === "positions" && overview && (
        <section className="panel">
          <table>
            <thead>
              <tr>
                <th>ISIN</th>
                <th>Menge</th>
                <th>Investiert</th>
                <th>Marktwert</th>
                <th>Einfache Rendite</th>
              </tr>
            </thead>
            <tbody>
              {overview.positions.map((p) => (
                <tr key={p.isin}>
                  <td className="mono">{p.isin}</td>
                  <td className="mono">{p.open_qty}</td>
                  <td className="mono">{money(p.invested)}</td>
                  <td className="mono">{money(p.market_value)}</td>
                  <td className="mono">{pct(p.simple_return)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      {tab === "staging" && (
        <section className="panel">
          <p className="muted">
            Review-Queue aus Paperless. Confirm importiert nach Ghostfolio; danach Sync ausführen.
          </p>
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
          {staging.length === 0 && <p className="muted">Keine Staging-Einträge.</p>}
        </section>
      )}

      {tab === "simulator" && (
        <section className="panel">
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
          {simResult && (
            <div style={{ marginTop: 20 }}>
              <p>
                Realisierter Gewinn:{" "}
                <strong className="mono">{money(String(simResult.realized_gain))}</strong>
              </p>
              <p>
                Geschätzte Steuer:{" "}
                <strong className="mono">{money(String(simResult.estimated_tax))}</strong>
              </p>
              <p>
                Nach Steuer:{" "}
                <strong className="mono">{money(String(simResult.net_after_tax))}</strong>
              </p>
              <pre className="mono" style={{ whiteSpace: "pre-wrap", fontSize: 12 }}>
                {JSON.stringify(simResult.lots, null, 2)}
              </pre>
            </div>
          )}
        </section>
      )}
    </div>
  );
}
