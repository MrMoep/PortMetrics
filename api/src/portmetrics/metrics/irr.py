"""Money-weighted return (IRR / MWR) from dated cashflows + terminal NAV."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from portmetrics.db.models import Activity
from portmetrics.metrics.periods import ZERO, _asset_key, _d, nav_as_of

# IRR search bounds (daily rate)
_IRR_LO = Decimal("-0.99")
_IRR_HI = Decimal("10")

# External capital + distributed income (securities-only NAV).
TRADE_TYPES = frozenset({"BUY", "SELL"})
INCOME_TYPES = frozenset({"DIVIDEND", "INTEREST"})
CASHFLOW_TYPES = TRADE_TYPES | INCOME_TYPES


def _signed_amount(activity: Activity) -> Decimal | None:
    """Cashflow sign convention: BUY −, SELL/DIVIDEND/INTEREST +."""
    if activity.type not in CASHFLOW_TYPES:
        return None
    amount = _d(activity.quantity) * _d(activity.unit_price)
    fee = _d(activity.fee)
    if activity.type == "BUY":
        return -(amount + fee)
    if activity.type == "SELL":
        return amount - fee
    # DIVIDEND / INTEREST: gross distribution (fee = withholding, not netted here)
    return amount


def dated_cashflows(
    activities: list[Activity],
    *,
    asset_key: str | None = None,
) -> list[tuple[date, Decimal]]:
    """
    External cashflows for IRR: BUY = outflow (−), SELL/DIVIDEND/INTEREST = inflow (+).
    Trade fees included on BUY/SELL. Filtered by asset_key when set.
    """
    flows: list[tuple[date, Decimal]] = []
    for activity in activities:
        if asset_key is not None and _asset_key(activity) != asset_key:
            continue
        signed = _signed_amount(activity)
        if signed is None:
            continue
        flows.append((activity.trade_date, signed))
    flows.sort(key=lambda x: x[0])
    return flows


def _npv(flows: list[tuple[date, Decimal]], daily_rate: Decimal, *, base: date) -> Decimal:
    total = ZERO
    one = Decimal("1")
    for day, amount in flows:
        days = (day - base).days
        total += amount / ((one + daily_rate) ** days)
    return total


def solve_irr_daily(flows: list[tuple[date, Decimal]]) -> Decimal | None:
    """Bisection for daily IRR such that NPV of flows ≈ 0."""
    if len(flows) < 2:
        return None
    base = flows[0][0]
    # Need both signs for a meaningful IRR root
    if not (any(a < 0 for _, a in flows) and any(a > 0 for _, a in flows)):
        return None
    lo, hi = _IRR_LO, _IRR_HI
    f_lo = _npv(flows, lo, base=base)
    f_hi = _npv(flows, hi, base=base)
    if f_lo * f_hi > 0:
        return None
    for _ in range(80):
        mid = (lo + hi) / 2
        f_mid = _npv(flows, mid, base=base)
        if abs(f_mid) < Decimal("1e-10"):
            return mid
        if f_lo * f_mid <= 0:
            hi = mid
            f_hi = f_mid
        else:
            lo = mid
            f_lo = f_mid
    return (lo + hi) / 2


def annualize_daily_irr(daily: Decimal) -> Decimal:
    return ((Decimal("1") + daily) ** Decimal("365.25") - Decimal("1")).quantize(Decimal("0.0001"))


def simple_return_from_flows(
    flows: list[tuple[date, Decimal]],
    *,
    terminal_nav: Decimal,
) -> Decimal | None:
    """(terminal − net_invested) / net_invested; net_invested = −sum(outflows) roughly invested."""
    invested = ZERO
    returned = ZERO
    for _, amount in flows:
        if amount < 0:
            invested += -amount
        else:
            returned += amount
    # terminal NAV is still held (not in flows yet)
    total_value = returned + terminal_nav
    if invested <= 0:
        return None
    return ((total_value - invested) / invested).quantize(Decimal("0.0001"))


def irr_payload(
    activities: list[Activity],
    prices: dict[tuple[str, date], Decimal],
    *,
    as_of: date | None = None,
    asset_key: str | None = None,
) -> dict:
    end = as_of or date.today()
    flows = dated_cashflows(activities, asset_key=asset_key)
    if not flows:
        return {
            "irr": None,
            "simple_return": None,
            "start_date": None,
            "end_date": end.isoformat(),
            "cashflow_count": 0,
            "terminal_nav": "0",
        }
    if asset_key is None:
        terminal = nav_as_of(activities, prices, end)
    else:
        from portmetrics.metrics.periods import holdings_as_of, last_trade_price_as_of

        qty = holdings_as_of(activities, end).get(asset_key, ZERO)
        mark = prices.get((asset_key, end))
        if mark is None:
            mark = last_trade_price_as_of(activities, asset_key, end)
        terminal = qty * mark if mark is not None else ZERO

    full_flows = list(flows)
    if terminal != 0:
        full_flows.append((end, terminal))
    daily = solve_irr_daily(full_flows)
    irr = annualize_daily_irr(daily) if daily is not None else None
    simple = simple_return_from_flows(flows, terminal_nav=terminal)
    return {
        "irr": str(irr) if irr is not None else None,
        "simple_return": str(simple) if simple is not None else None,
        "start_date": flows[0][0].isoformat(),
        "end_date": end.isoformat(),
        "cashflow_count": len(flows),
        "terminal_nav": str(terminal),
    }


def cashflow_timeline(
    activities: list[Activity],
    *,
    asset_key: str | None = None,
    display_id_by_key: dict[str, str] | None = None,
) -> list[dict]:
    """Dated cashflow events for UI (BUY/SELL/DIVIDEND/INTEREST)."""
    rows: list[dict] = []
    for activity in activities:
        key = _asset_key(activity)
        if asset_key is not None and key != asset_key:
            continue
        signed = _signed_amount(activity)
        if signed is None:
            continue
        display = (display_id_by_key or {}).get(key) or activity.symbol or key or "—"
        rows.append(
            {
                "date": activity.trade_date.isoformat(),
                "type": activity.type,
                "asset": display,
                "asset_key": key,
                "amount": str(signed),
            }
        )
    rows.sort(key=lambda r: (r["date"], r["type"], r["asset"]))
    return rows
