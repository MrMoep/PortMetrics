"""Tax allowance (Freibetrag) tracker from FIFO realized gains + income."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from portmetrics.db.models import Activity, LotConsumption
from portmetrics.settings.portfolio import get_portfolio_settings

ZERO = Decimal("0")


def _d(value: Decimal | int | str | None) -> Decimal:
    if value is None:
        return ZERO
    return Decimal(str(value))


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


def income_for_year(session: Session, year: int, *, activity_type: str) -> Decimal:
    """Gross DIVIDEND or INTEREST for the calendar year (qty × unit_price)."""
    rows = session.scalars(
        select(Activity)
        .where(Activity.type == activity_type)
        .where(Activity.trade_date >= date(year, 1, 1))
        .where(Activity.trade_date <= date(year, 12, 31))
    ).all()
    total = ZERO
    for activity in rows:
        total += _d(activity.quantity) * _d(activity.unit_price)
    return total


def tax_allowance_payload(
    session: Session,
    *,
    as_of: date | None = None,
) -> dict:
    """
    Compare YTD taxable Kapitalerträge to configured Freibetrag.

    Taxable ≈ max(0, net realized gains) + gross dividends + gross interest.
    Note: Schätzung — keine Steuerberatung. No Teilfreistellung / Quellensteuer.
    """
    end = as_of or date.today()
    year = end.year
    settings = get_portfolio_settings(session)
    allowance = Decimal(settings["tax_allowance_eur"])
    warn_pct = Decimal(settings["tax_warn_pct"])
    realized = realized_gains_for_year(session, year)
    dividends_ytd = income_for_year(session, year, activity_type="DIVIDEND")
    interest_ytd = income_for_year(session, year, activity_type="INTEREST")
    # Only positive net gains consume the allowance (DE-style simplification).
    gains_taxable = max(ZERO, realized)
    taxable = gains_taxable + dividends_ytd + interest_ytd
    remaining = allowance - taxable
    used_pct = (taxable / allowance) if allowance > 0 else ZERO
    warn = bool(allowance > 0 and used_pct >= warn_pct)
    return {
        "year": year,
        "allowance": str(allowance),
        "realized_ytd": str(realized),
        "dividends_ytd": str(dividends_ytd),
        "interest_ytd": str(interest_ytd),
        "taxable_ytd": str(taxable),
        "remaining": str(remaining),
        "used_pct": str(used_pct.quantize(Decimal("0.0001"))),
        "warn": warn,
        "warn_pct": str(warn_pct),
    }
