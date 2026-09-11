/** Pure display / nav / sort helpers used by the SPA (unit-tested). */

export type SettingsSection = "ops" | "portfolio" | "paperless" | "ghostfolio" | "assets";
export type SortDir = "asc" | "desc";
export type SortState = { key: string; dir: SortDir };

export type IdName = { id: number; name: string };

export const SETTINGS_SECTIONS: { id: SettingsSection; label: string }[] = [
  { id: "ops", label: "Wartung" },
  { id: "portfolio", label: "Portfolio" },
  { id: "assets", label: "Assets" },
  { id: "paperless", label: "Paperless" },
  { id: "ghostfolio", label: "Ghostfolio" },
];

const SETTINGS_SECTION_IDS = new Set<string>(SETTINGS_SECTIONS.map((s) => s.id));

export function parseSettingsHash(hash: string): SettingsSection | null {
  const match = hash.match(/^#settings\/([a-z]+)$/i);
  if (!match) return null;
  const id = match[1].toLowerCase();
  return SETTINGS_SECTION_IDS.has(id) ? (id as SettingsSection) : null;
}

export function settingsHash(section: SettingsSection): string {
  return `#settings/${section}`;
}

export function sameIdNameList(a: IdName[], b: IdName[]): boolean {
  if (a.length !== b.length) return false;
  const ids = new Set(a.map((row) => row.id));
  return b.every((row) => ids.has(row.id));
}

export function pct(value: string | null | undefined, hide = false): string {
  if (value == null) return "—";
  if (hide) return "0,00 %";
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return `${(n * 100).toFixed(2)} %`;
}

export function money(value: string | null | undefined, hide = false): string {
  if (value == null) return "—";
  if (hide) return "0,00";
  const n = Number(value);
  if (Number.isNaN(n)) return value;
  return n.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Percent points already scaled (e.g. API `12.34` → `12.34 %`). */
export function pctPoints(value: string | number | null | undefined, hide = false): string {
  if (value == null || value === "") return "—";
  if (hide) return "0,00 %";
  return `${value} %`;
}

export function qty(value: string | number | null | undefined, hide = false): string {
  if (value == null || value === "") return "—";
  if (hide) return "0";
  return String(value);
}

export function ratio(value: string | number | null | undefined, hide = false): string {
  if (value == null || value === "") return "—";
  if (hide) return "0.00";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toFixed(2);
}

export function signedClass(value: string | number | null | undefined, hide = false): string {
  if (hide) return "";
  if (value == null || value === "") return "";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n) || n === 0) return "";
  return n > 0 ? "val-pos" : "val-neg";
}

export function toggleSort(prev: SortState, key: string, defaultDir: SortDir = "desc"): SortState {
  if (prev.key === key) {
    return { key, dir: prev.dir === "asc" ? "desc" : "asc" };
  }
  return { key, dir: defaultDir };
}

export function cmpScalar(a: unknown, b: unknown): number {
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

export function sortRows<T>(rows: T[], sort: SortState): T[] {
  return [...rows].sort((ra, rb) => {
    const recA = ra as Record<string, unknown>;
    const recB = rb as Record<string, unknown>;
    const c = cmpScalar(recA[sort.key], recB[sort.key]);
    return sort.dir === "asc" ? c : -c;
  });
}

export function assetIdColumnLabel(pref: string | null | undefined): string {
  if (pref === "wkn") return "WKN";
  if (pref === "isin") return "ISIN";
  return "Symbol";
}
