"""Overview KPI layout prefs (app_settings key `overview`)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from portmetrics.db.models import AppSetting

OVERVIEW_SETTINGS_KEY = "overview"

# Stable catalog IDs — must stay in sync with web/src/overviewKpis.ts
KNOWN_KPI_IDS: tuple[str, ...] = (
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
)

KNOWN_KPI_ID_SET = frozenset(KNOWN_KPI_IDS)
DEFAULT_KPI_IDS: list[str] = list(KNOWN_KPI_IDS)
DEFAULT_HERO_ID = "nav"


def empty_overview_settings() -> dict[str, Any]:
    return {
        "kpi_ids": list(DEFAULT_KPI_IDS),
        "hero_id": DEFAULT_HERO_ID,
    }


def normalize_overview_settings(raw: Any) -> dict[str, Any]:
    """Filter unknown IDs, enforce ≥1 visible KPI, resolve hero."""
    base = empty_overview_settings()
    if not isinstance(raw, dict):
        return base

    raw_ids = raw.get("kpi_ids")
    if not isinstance(raw_ids, list):
        raw_ids = base["kpi_ids"]

    seen: set[str] = set()
    kpi_ids: list[str] = []
    for item in raw_ids:
        kid = str(item or "").strip()
        if kid in KNOWN_KPI_ID_SET and kid not in seen:
            seen.add(kid)
            kpi_ids.append(kid)

    if not kpi_ids:
        kpi_ids = list(DEFAULT_KPI_IDS)

    hero = str(raw.get("hero_id") or "").strip()
    if hero not in kpi_ids:
        hero = kpi_ids[0]

    return {"kpi_ids": kpi_ids, "hero_id": hero}


def get_overview_settings(session: Session) -> dict[str, Any]:
    row = session.get(AppSetting, OVERVIEW_SETTINGS_KEY)
    if row is None:
        return empty_overview_settings()
    return normalize_overview_settings(row.value)


def save_overview_settings(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    value = normalize_overview_settings(payload)
    row = session.get(AppSetting, OVERVIEW_SETTINGS_KEY)
    if row is None:
        session.add(AppSetting(key=OVERVIEW_SETTINGS_KEY, value=value))
    else:
        row.value = value
    session.flush()
    return get_overview_settings(session)
