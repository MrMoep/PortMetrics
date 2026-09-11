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
    symbol?: string | null;
    wkn?: string | null;
    isin_code?: string | null;
    display_id?: string;
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
  symbol?: string | null;
  wkn?: string | null;
  isin_code?: string | null;
  display_id?: string;
  paperless_doc_id?: number | null;
  open_qty: string;
  unit_cost: string;
  open_date: string;
  status: string;
  mark_price: string | null;
  unrealized_gain: string | null;
  unrealized_gain_pct: string | null;
};

export type StagingMapping = {
  isin: string | null;
  preferred_symbol: string | null;
  table_wkn: string | null;
  suggested_symbol: string | null;
  suggested_count: number | null;
  suggested_last_trade_date: string | null;
  wkn_conflict: {
    table_value: string;
    observed_value: string;
    message: string;
  } | null;
  needs_mapping: boolean;
  mapping_ready: boolean;
  settings_href: string;
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
  mapping?: StagingMapping;
  can_confirm?: boolean;
};

export type AssetIdentifierRow = {
  isin: string;
  wkn: string | null;
  preferred_symbol: string | null;
  paperless_doc_id?: number | null;
  updated_at?: string | null;
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

export type PaperlessIdName = {
  id: number;
  name: string;
};

export type PaperlessSettings = {
  roles: string[];
  role_meta?: PaperlessRoleMeta[];
  field_map: Record<string, number>;
  tag: string | null;
  sync_tags?: PaperlessIdName[];
  sync_document_types?: PaperlessIdName[];
  ghostfolio_default_account_id: string | null;
  ghostfolio_data_source: string;
  public_url?: string | null;
  document_base_url?: string | null;
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
  asset_id_preference: "symbol" | "wkn" | "isin";
};

export type StagingSyncEvent = {
  event: string;
  scanned?: number;
  upserted?: number;
  skipped?: number;
  mode?: string;
  filters_active?: boolean;
  warning?: string | null;
  detail?: string;
  pages_scanned?: number;
  docs_seen?: number;
  processed?: number;
  total?: number;
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

async function stagingSyncStream(
  mode: "partial" | "full",
  onEvent?: (event: StagingSyncEvent) => void,
): Promise<StagingSyncEvent> {
  const response = await fetch(`/api/staging/sync?mode=${encodeURIComponent(mode)}`, {
    method: "POST",
    headers: { Accept: "application/x-ndjson, application/json" },
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `${response.status} ${response.statusText}`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json") && !contentType.includes("ndjson")) {
    const done = (await response.json()) as StagingSyncEvent;
    onEvent?.(done);
    return done;
  }
  if (!response.body) {
    throw new Error("Empty sync response body");
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let last: StagingSyncEvent | null = null;
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const event = JSON.parse(trimmed) as StagingSyncEvent;
      last = event;
      onEvent?.(event);
      if (event.event === "error") {
        throw new Error(event.detail || "Paperless sync failed");
      }
    }
  }
  if (buffer.trim()) {
    const event = JSON.parse(buffer.trim()) as StagingSyncEvent;
    last = event;
    onEvent?.(event);
    if (event.event === "error") {
      throw new Error(event.detail || "Paperless sync failed");
    }
  }
  if (!last || last.event !== "done") {
    throw new Error("Paperless sync ended without result");
  }
  return last;
}

export const api = {
  version: () => request<VersionInfo>("/api/version"),
  overview: () => request<Overview>("/api/metrics/overview"),
  lots: () => request<{ lots: Lot[] }>("/api/lots"),
  sync: () =>
    request<{
      fetched: number;
      upserted: number;
      deleted: number;
      prune_skipped?: boolean;
      checksum: string;
      price_assets: number;
      price_upserted: number;
      price_skipped: number;
      lots_created: number;
      consumptions: number;
      metrics_days: number;
    }>("/api/sync/ghostfolio", { method: "POST" }),
  rebuildFifo: () => request<Record<string, unknown>>("/api/fifo/rebuild", { method: "POST" }),
  rebuildMetrics: () =>
    request<Record<string, unknown>>("/api/metrics/rebuild", { method: "POST" }),
  staging: (status?: string) =>
    request<{ items: StagingItem[] }>(
      status ? `/api/staging?status=${encodeURIComponent(status)}` : "/api/staging",
    ),
  stagingSync: (
    mode: "partial" | "full" = "partial",
    onEvent?: (event: StagingSyncEvent) => void,
  ) => stagingSyncStream(mode, onEvent),
  stagingConfirm: (id: number) =>
    request<StagingItem>(`/api/staging/${id}/confirm`, { method: "POST" }),
  stagingReject: (id: number) =>
    request<StagingItem>(`/api/staging/${id}/reject`, { method: "POST" }),
  stagingMatchActivities: () =>
    request<{
      scanned: number;
      matched: number;
      ambiguous: number;
      unmatched: number;
      skipped: number;
      items: Array<Record<string, unknown>>;
    }>("/api/staging/match-activities", { method: "POST" }),
  paperlessSettings: () => request<PaperlessSettings>("/api/settings/paperless"),
  savePaperlessSettings: (body: {
    field_map?: Record<string, number | null>;
    tag?: string | null;
    sync_tags?: PaperlessIdName[];
    sync_document_types?: PaperlessIdName[];
    ghostfolio_default_account_id?: string | null;
    ghostfolio_data_source?: string;
    public_url?: string | null;
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
    asset_id_preference?: "symbol" | "wkn" | "isin";
  }) =>
    request<PortfolioSettings>("/api/settings/portfolio", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  assetIdentifiers: () => request<{ items: AssetIdentifierRow[] }>("/api/settings/assets"),
  saveAssetIdentifiers: (items: AssetIdentifierRow[]) =>
    request<{ items: AssetIdentifierRow[] }>("/api/settings/assets", {
      method: "PUT",
      body: JSON.stringify({ items }),
    }),
  applyAssetSuggestion: (body: {
    isin: string;
    symbol?: string | null;
    wkn?: string | null;
    paperless_doc_id?: number | null;
  }) =>
    request<AssetIdentifierRow>("/api/settings/assets/apply-suggestion", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  paperlessCustomFields: () =>
    request<{ fields: PaperlessField[] }>("/api/settings/paperless/custom-fields"),
  paperlessTags: () => request<{ tags: PaperlessIdName[] }>("/api/settings/paperless/tags"),
  paperlessDocumentTypes: () =>
    request<{ document_types: PaperlessIdName[] }>("/api/settings/paperless/document-types"),
  testPaperless: () =>
    request<{
      ok: boolean;
      custom_field_count: number;
      tag_count?: number;
      document_type_count?: number;
      url: string | null;
    }>("/api/settings/paperless/test", { method: "POST" }),
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
