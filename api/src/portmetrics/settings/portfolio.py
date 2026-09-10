"""Portfolio settings: tax allowance + risk-free rate (app_settings)."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from portmetrics.db.models import AppSetting

PORTFOLIO_SETTINGS_KEY = "portfolio"
DEFAULT_TAX_ALLOWANCE_EUR = Decimal("1000")  # DE Sparerpauschbetrag (ledig), Schätzung
DEFAULT_WARN_PCT = Decimal("0.85")
DEFAULT_RISK_FREE_RATE = Decimal("0")  # annual, e.g. 0.02 = 2%


def _dec(value: Any, default: Decimal) -> Decimal:
    if value is None or value == "":
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return default


def empty_portfolio_settings() -> dict[str, Any]:
    return {
        "tax_allowance_eur": str(DEFAULT_TAX_ALLOWANCE_EUR),
        "tax_warn_pct": str(DEFAULT_WARN_PCT),
        "risk_free_rate": str(DEFAULT_RISK_FREE_RATE),
    }


def get_portfolio_settings(session: Session) -> dict[str, Any]:
    row = session.get(AppSetting, PORTFOLIO_SETTINGS_KEY)
    base = empty_portfolio_settings()
    if row is None or not isinstance(row.value, dict):
        return base
    merged = dict(base)
    merged.update({k: v for k, v in row.value.items() if k in base})
    # Normalize to strings of Decimals
    return {
        "tax_allowance_eur": str(_dec(merged.get("tax_allowance_eur"), DEFAULT_TAX_ALLOWANCE_EUR)),
        "tax_warn_pct": str(_dec(merged.get("tax_warn_pct"), DEFAULT_WARN_PCT)),
        "risk_free_rate": str(_dec(merged.get("risk_free_rate"), DEFAULT_RISK_FREE_RATE)),
    }


def save_portfolio_settings(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    current = get_portfolio_settings(session)
    allowance = _dec(
        payload.get("tax_allowance_eur", current["tax_allowance_eur"]), DEFAULT_TAX_ALLOWANCE_EUR
    )
    warn_pct = _dec(payload.get("tax_warn_pct", current["tax_warn_pct"]), DEFAULT_WARN_PCT)
    risk_free = _dec(
        payload.get("risk_free_rate", current["risk_free_rate"]), DEFAULT_RISK_FREE_RATE
    )
    if allowance < 0:
        raise ValueError("tax_allowance_eur must be >= 0")
    if warn_pct < 0 or warn_pct > 1:
        raise ValueError("tax_warn_pct must be between 0 and 1")
    value = {
        "tax_allowance_eur": str(allowance),
        "tax_warn_pct": str(warn_pct),
        "risk_free_rate": str(risk_free),
    }
    row = session.get(AppSetting, PORTFOLIO_SETTINGS_KEY)
    if row is None:
        session.add(AppSetting(key=PORTFOLIO_SETTINGS_KEY, value=value))
    else:
        row.value = value
    session.flush()
    return get_portfolio_settings(session)
