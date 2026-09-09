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
  dividends: { total: string };
  positions: Array<{
    isin: string;
    open_qty: string;
    invested: string;
    market_value: string;
    simple_return: string | null;
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
    symbol?: string;
    quantity?: string;
    unit_price?: string;
    fee?: string;
    trade_date?: string;
    currency?: string;
  };
  gf_activity_id: string | null;
  error: string | null;
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
