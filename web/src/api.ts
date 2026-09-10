export type Overview = {
  as_of: string;
  nav: string;
  invested: string;
  unrealized_gain: string;
  periods: Array<{
    label: string;
    start_date: string;
    end_date: string;
    period_return: string | null;
  }>;
  cagr: { cagr: string | null; years: string | null };
  mwr?: {
    irr: string | null;
    simple_return: string | null;
    start_date: string | null;
    end_date: string;
    cashflow_count: number;
    terminal_nav: string;
  };
  cashflows?: Array<{ date: string; amount: string }>;
  risk?: {
    max_drawdown: string | null;
    peak_date: string | null;
    trough_date: string | null;
    volatility: string | null;
    sharpe: string | null;
    risk_free_rate: string;
    observations: number;
  };
  tax_allowance?: {
    year: number;
    allowance: string;
    realized_ytd: string;
    taxable_ytd: string;
    remaining: string;
    used_pct: string;
    warn: boolean;
    warn_pct: string;
  };
  dividends: { total: string };
  positions: Array<{
    isin: string;
    open_qty: string;
    invested: string;
    market_value: string;
    simple_return: string | null;
    irr?: string | null;
    max_drawdown?: string | null;
  }>;
};

export type Lot = {
  id: number;
  isin: string;
  open_qty: string;
  unit_cost: string;
  open_date: string;
  status: string;
  mark_price: string | null;
  unrealized_gain: string | null;
  unrealized_gain_pct: string | null;
};

export type StagingItem = {
  id: number;
  paperless_doc_id: number;
  status: string;
  payload: {
    title?: string;
    wp_typ?: string;
    isin?: string;
    wkn?: string;
    symbol?: string;
    quantity?: string;
    unit_price?: string;
    fee?: string;
    trade_date?: string;
    currency?: string;
    importable?: boolean;
  };
  gf_activity_id: string | null;
  error: string | null;
};

export type VersionInfo = {
  name: string;
  version: string;
  repository: string;
  channel?: string;
  built_at?: string;
  git_sha?: string;
  package_version?: string;
};

export type PaperlessField = {
  id: number;
  name: string | null;
  data_type?: string | null;
};

export type PaperlessRoleMeta = {
  role: string;
  required: boolean;
  label: string;
  hint?: string;
};

export type PaperlessSettings = {
  roles: string[];
  role_meta?: PaperlessRoleMeta[];
  field_map: Record<string, number>;
  tag: string | null;
  ghostfolio_default_account_id: string | null;
  ghostfolio_data_source: string;
  paperless_configured: boolean;
  webhook_secret_configured: boolean;
  webhook_path: string;
  paperless_sync_interval_minutes: number;
  notes?: Record<string, string>;
};

export type PortfolioSettings = {
  tax_allowance_eur: string;
  tax_warn_pct: string;
  risk_free_rate: string;
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  version: () => request<VersionInfo>("/api/version"),
  overview: () => request<Overview>("/api/metrics/overview"),
  lots: () => request<{ lots: Lot[] }>("/api/lots"),
  sync: () => request<Record<string, unknown>>("/api/sync/ghostfolio", { method: "POST" }),
  rebuildFifo: () => request<Record<string, unknown>>("/api/fifo/rebuild", { method: "POST" }),
  rebuildMetrics: () =>
    request<Record<string, unknown>>("/api/metrics/rebuild", { method: "POST" }),
  staging: (status?: string) =>
    request<{ items: StagingItem[] }>(
      status ? `/api/staging?status=${encodeURIComponent(status)}` : "/api/staging",
    ),
  stagingSync: () => request<Record<string, unknown>>("/api/staging/sync", { method: "POST" }),
  stagingConfirm: (id: number) =>
    request<StagingItem>(`/api/staging/${id}/confirm`, { method: "POST" }),
  stagingReject: (id: number) =>
    request<StagingItem>(`/api/staging/${id}/reject`, { method: "POST" }),
  paperlessSettings: () => request<PaperlessSettings>("/api/settings/paperless"),
  savePaperlessSettings: (body: {
    field_map: Record<string, number | null>;
    tag?: string | null;
    ghostfolio_default_account_id?: string | null;
    ghostfolio_data_source?: string;
  }) =>
    request<PaperlessSettings>("/api/settings/paperless", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  portfolioSettings: () => request<PortfolioSettings>("/api/settings/portfolio"),
  savePortfolioSettings: (body: {
    tax_allowance_eur?: string;
    tax_warn_pct?: string;
    risk_free_rate?: string;
  }) =>
    request<PortfolioSettings>("/api/settings/portfolio", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  paperlessCustomFields: () =>
    request<{ fields: PaperlessField[] }>("/api/settings/paperless/custom-fields"),
  testPaperless: () =>
    request<{ ok: boolean; custom_field_count: number; url: string | null }>(
      "/api/settings/paperless/test",
      { method: "POST" },
    ),
  simulateSell: (body: {
    isin: string;
    quantity: string;
    unit_price?: string;
    fee?: string;
  }) =>
    request<Record<string, unknown>>("/api/simulate/sell", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
