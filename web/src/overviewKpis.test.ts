import { describe, expect, it } from "vitest";
import {
  DEFAULT_KPI_IDS,
  defaultOverviewLayout,
  editorOrder,
  normalizeOverviewLayout,
} from "./overviewKpis";

describe("normalizeOverviewLayout", () => {
  it("returns defaults for empty input", () => {
    expect(normalizeOverviewLayout(null)).toEqual(defaultOverviewLayout());
    expect(normalizeOverviewLayout({ kpi_ids: [] })).toEqual(defaultOverviewLayout());
  });

  it("drops unknown ids and dedupes", () => {
    const layout = normalizeOverviewLayout({
      kpi_ids: ["nav", "nope", "nav", "invested"],
      hero_id: "invested",
    });
    expect(layout.kpi_ids).toEqual(["nav", "invested"]);
    expect(layout.hero_id).toBe("invested");
  });

  it("falls back hero to first visible", () => {
    const layout = normalizeOverviewLayout({
      kpi_ids: ["cagr", "sharpe"],
      hero_id: "nav",
    });
    expect(layout.hero_id).toBe("cagr");
  });
});

describe("editorOrder", () => {
  it("keeps visible order then appends hidden catalog leftovers", () => {
    const layout = normalizeOverviewLayout({
      kpi_ids: ["sharpe", "nav"],
      hero_id: "sharpe",
    });
    const order = editorOrder(layout);
    expect(order.slice(0, 2)).toEqual(["sharpe", "nav"]);
    expect(order).toHaveLength(DEFAULT_KPI_IDS.length);
    expect(new Set(order).size).toBe(DEFAULT_KPI_IDS.length);
  });
});
