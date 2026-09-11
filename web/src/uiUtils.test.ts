import { describe, expect, it } from "vitest";
import {
  cmpScalar,
  money,
  parseSettingsHash,
  pct,
  pctPoints,
  qty,
  ratio,
  sameIdNameList,
  settingsHash,
  signedClass,
  sortRows,
  toggleSort,
} from "./uiUtils";

describe("parseSettingsHash / settingsHash", () => {
  it("parses known sections", () => {
    expect(parseSettingsHash("#settings/ops")).toBe("ops");
    expect(parseSettingsHash("#settings/portfolio")).toBe("portfolio");
    expect(parseSettingsHash("#SETTINGS/Paperless")).toBe("paperless");
    expect(parseSettingsHash("#settings/assets")).toBe("assets");
  });

  it("rejects unknown or malformed hashes", () => {
    expect(parseSettingsHash("#settings/unknown")).toBeNull();
    expect(parseSettingsHash("#ops")).toBeNull();
    expect(parseSettingsHash("")).toBeNull();
  });

  it("round-trips settingsHash", () => {
    expect(parseSettingsHash(settingsHash("ghostfolio"))).toBe("ghostfolio");
  });
});

describe("sameIdNameList", () => {
  it("compares by id set", () => {
    expect(sameIdNameList([{ id: 1, name: "a" }], [{ id: 1, name: "other" }])).toBe(true);
    expect(sameIdNameList([{ id: 1, name: "a" }], [{ id: 2, name: "a" }])).toBe(false);
    expect(sameIdNameList([{ id: 1, name: "a" }], [])).toBe(false);
  });
});

describe("formatters", () => {
  it("formats pct as percent points from ratio", () => {
    expect(pct("0.1234")).toBe("12.34 %");
    expect(pct(null)).toBe("—");
    expect(pct("0.1", true)).toBe("0,00 %");
    expect(pct("n/a")).toBe("n/a");
  });

  it("formats money with de-DE locale", () => {
    expect(money("1234.5")).toMatch(/1\.234,50/);
    expect(money(null)).toBe("—");
    expect(money("9", true)).toBe("0,00");
  });

  it("formats pctPoints, qty, ratio", () => {
    expect(pctPoints("12.34")).toBe("12.34 %");
    expect(pctPoints(null)).toBe("—");
    expect(qty(10)).toBe("10");
    expect(qty("")).toBe("—");
    expect(ratio("1.234")).toBe("1.23");
    expect(ratio(null)).toBe("—");
  });

  it("signedClass maps sign to CSS class", () => {
    expect(signedClass("1")).toBe("val-pos");
    expect(signedClass("-0.5")).toBe("val-neg");
    expect(signedClass("0")).toBe("");
    expect(signedClass("1", true)).toBe("");
  });
});

describe("sort helpers", () => {
  it("toggleSort flips direction on same key", () => {
    expect(toggleSort({ key: "nav", dir: "desc" }, "nav")).toEqual({
      key: "nav",
      dir: "asc",
    });
    expect(toggleSort({ key: "nav", dir: "asc" }, "other")).toEqual({
      key: "other",
      dir: "desc",
    });
  });

  it("cmpScalar orders numbers and nulls", () => {
    expect(cmpScalar("10", "2")).toBeGreaterThan(0);
    expect(cmpScalar(null, "1")).toBe(1);
    expect(cmpScalar("1", null)).toBe(-1);
  });

  it("sortRows sorts ascending and descending", () => {
    const rows = [{ v: "10" }, { v: "2" }, { v: "3" }];
    expect(sortRows(rows, { key: "v", dir: "asc" }).map((r) => r.v)).toEqual([
      "2",
      "3",
      "10",
    ]);
    expect(sortRows(rows, { key: "v", dir: "desc" }).map((r) => r.v)).toEqual([
      "10",
      "3",
      "2",
    ]);
  });
});
