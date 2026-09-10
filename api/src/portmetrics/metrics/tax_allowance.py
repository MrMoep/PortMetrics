"""Tax allowance (Freibetrag) tracker from FIFO realized gains."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from portmetrics.db.models import Activity, LotConsumption
from portmetrics.settings.portfolio import get_portfolio_settings

ZERO = Decimal("0")


def realized_gains_for_year(session: Session, year: int) -> Decimal:
    """Sum LotConsumption.realized_gain for sells in the given calendar year."""
    rows = session.execute(
        select(LotConsumption.realized_gain)
        .join(Activity, Activity.id == LotConsumption.sell_activity_id)
        .where(Activity.type == "SELL")
        .where(Activity.trade_date >= date(year, 1, 1))
        .where(Activity.trade_date <= date(year, 12, 31))
    ).all()
    total = ZERO
    for (gain,) in rows:
        total += Decimal(str(gain))
    return total


def tax_allowance_payload(
    session: Session,
    *,
    as_of: date | None = None,
) -> dict:
    """
    Compare YTD net realized gains to configured Freibetrag.

    Note: Schätzung — keine Steuerberatung. Net includes losses (offsets gains).
    """
    end = as_of or date.today()
    year = end.year
    settings = get_portfolio_settings(session)
    allowance = Decimal(settings["tax_allowance_eur"])
    warn_pct = Decimal(settings["tax_warn_pct"])
    realized = realized_gains_for_year(session, year)
    # Only positive net gains consume the allowance (DE-style simplification).
    taxable = max(ZERO, realized)
    remaining = allowance - taxable
    used_pct = (taxable / allowance) if allowance > 0 else ZERO
    warn = bool(allowance > 0 and used_pct >= warn_pct)
    return {
        "year": year,
        "allowance": str(allowance),
        "realized_ytd": str(realized),
        "taxable_ytd": str(taxable),
        "remaining": str(remaining),
        "used_pct": str(used_pct.quantize(Decimal("0.0001"))),
        "warn": warn,
        "warn_pct": str(warn_pct),
    }
