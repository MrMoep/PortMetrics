from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from portmetrics.db.models import Activity, MetricsDaily, PriceSnapshot
from portmetrics.fifo.service import asset_key_for, list_open_lots

ZERO = Decimal("0")


@dataclass(frozen=True)
class PeriodReturn:
    label: str
    start_date: date
    end_date: date
    start_nav: Decimal
    end_nav: Decimal
    contributions: Decimal
    withdrawals: Decimal
    period_return: Decimal | None


@dataclass(frozen=True)
class AnnualReturn:
    """Calendar-year return plus open-ended return from the same start to as-of."""

    label: str
    start_date: date
    end_date: date
    year_return: Decimal | None
    return_to_date: Decimal | None


def _d(value: Decimal | int | str | None) -> Decimal:
    if value is None:
        return ZERO
    return Decimal(str(value))


def _asset_key(activity: Activity) -> str:
    return asset_key_for(activity)


def load_activities(session: Session) -> list[Activity]:
    return list(
        session.scalars(select(Activity).order_by(Activity.trade_date.asc(), Activity.id.asc()))
    )


def price_map(session: Session) -> dict[tuple[str, date], Decimal]:
    rows = session.scalars(select(PriceSnapshot)).all()
    return {(row.isin, row.price_date): _d(row.close_price) for row in rows}


def last_trade_price_as_of(
    activities: list[Activity],
    asset_key: str,
    as_of: date,
) -> Decimal | None:
    price: Decimal | None = None
    for activity in activities:
        if activity.trade_date > as_of:
            break
        if _asset_key(activity) == asset_key:
            price = _d(activity.unit_price)
    return price


def holdings_as_of(activities: list[Activity], as_of: date) -> dict[str, Decimal]:
    holdings: dict[str, Decimal] = {}
    for activity in activities:
        if activity.trade_date > as_of:
            break
        key = _asset_key(activity)
        qty = holdings.get(key, ZERO)
        if activity.type == "BUY":
            qty += _d(activity.quantity)
        elif activity.type == "SELL":
            qty -= _d(activity.quantity)
        holdings[key] = qty
    return {k: v for k, v in holdings.items() if v != 0}


def nav_as_of(
    activities: list[Activity],
    prices: dict[tuple[str, date], Decimal],
    as_of: date,
) -> Decimal:
    holdings = holdings_as_of(activities, as_of)
    total = ZERO
    for key, qty in holdings.items():
        mark = prices.get((key, as_of))
        if mark is None:
            mark = last_trade_price_as_of(activities, key, as_of)
        if mark is None:
            continue
        total += qty * mark
    return total


def cashflows_between(
    activities: list[Activity],
    start: date,
    end: date,
) -> tuple[Decimal, Decimal]:
    """Returns (contributions, withdrawals) in [start, end]."""
    contributions = ZERO
    withdrawals = ZERO
    for activity in activities:
        if activity.trade_date < start or activity.trade_date > end:
            continue
        amount = _d(activity.quantity) * _d(activity.unit_price)
        fee = _d(activity.fee)
        if activity.type == "BUY":
            contributions += amount + fee
        elif activity.type == "SELL":
            withdrawals += amount - fee
    return contributions, withdrawals


def period_return(
    activities: list[Activity],
    prices: dict[tuple[str, date], Decimal],
    *,
    label: str,
    start: date,
    end: date,
) -> PeriodReturn:
    start_nav = nav_as_of(activities, prices, start)
    end_nav = nav_as_of(activities, prices, end)
    contributions, withdrawals = cashflows_between(activities, start, end)
    net_cf = contributions - withdrawals
    denom = start_nav + contributions
    ret: Decimal | None
    if denom == 0:
        ret = None
    else:
        ret = ((end_nav - start_nav - net_cf) / denom).quantize(Decimal("0.0001"))
    return PeriodReturn(
        label=label,
        start_date=start,
        end_date=end,
        start_nav=start_nav,
        end_nav=end_nav,
        contributions=contributions,
        withdrawals=withdrawals,
        period_return=ret,
    )


def month_start(d: date) -> date:
    return d.replace(day=1)


def year_start(d: date) -> date:
    return d.replace(month=1, day=1)


def previous_month_range(d: date) -> tuple[date, date]:
    first_this = month_start(d)
    end_prev = first_this - timedelta(days=1)
    start_prev = month_start(end_prev)
    return start_prev, end_prev


def previous_year_range(d: date) -> tuple[date, date]:
    start = date(d.year - 1, 1, 1)
    end = date(d.year - 1, 12, 31)
    return start, end


def compute_standard_periods(
    activities: list[Activity],
    prices: dict[tuple[str, date], Decimal],
    as_of: date | None = None,
) -> list[PeriodReturn]:
    if not activities:
        return []
    end = as_of or date.today()
    first = activities[0].trade_date
    periods: list[tuple[str, date, date]] = [
        ("30d", max(first, end - timedelta(days=30)), end),
        ("mtd", max(first, month_start(end)), end),
        ("ytd", max(first, year_start(end)), end),
    ]
    pm_start, pm_end = previous_month_range(end)
    if pm_end >= first:
        periods.append(("last_month", max(first, pm_start), pm_end))
    py_start, py_end = previous_year_range(end)
    if py_end >= first:
        periods.append(("last_year", max(first, py_start), py_end))

    return [
        period_return(activities, prices, label=label, start=start, end=end_date)
        for label, start, end_date in periods
    ]


def compute_annual_returns(
    activities: list[Activity],
    prices: dict[tuple[str, date], Decimal],
    as_of: date | None = None,
) -> list[AnnualReturn]:
    """YTD then prior calendar years back to the first activity.

    ``year_return`` closes at year-end (or as-of for YTD).
    ``return_to_date`` uses the same start but ends at as-of; omitted for YTD
    because both windows are identical.
    """
    if not activities:
        return []
    end = as_of or date.today()
    first = activities[0].trade_date
    rows: list[AnnualReturn] = []
    for year in range(end.year, first.year - 1, -1):
        start = max(first, date(year, 1, 1))
        if year == end.year:
            closed = period_return(
                activities, prices, label="ytd", start=start, end=end
            )
            rows.append(
                AnnualReturn(
                    label="ytd",
                    start_date=closed.start_date,
                    end_date=closed.end_date,
                    year_return=closed.period_return,
                    return_to_date=None,
                )
            )
            continue
        year_end = date(year, 12, 31)
        if year_end < first:
            continue
        closed = period_return(
            activities, prices, label=str(year), start=start, end=year_end
        )
        open_ended = period_return(
            activities, prices, label=f"{year}_to_date", start=start, end=end
        )
        rows.append(
            AnnualReturn(
                label=str(year),
                start_date=closed.start_date,
                end_date=closed.end_date,
                year_return=closed.period_return,
                return_to_date=open_ended.period_return,
            )
        )
    return rows


def _annual_return_dict(row: AnnualReturn) -> dict:
    return {
        "label": row.label,
        "start_date": row.start_date.isoformat(),
        "end_date": row.end_date.isoformat(),
        "year_return": str(row.year_return) if row.year_return is not None else None,
        "return_to_date": (
            str(row.return_to_date) if row.return_to_date is not None else None
        ),
    }


def cagr(
    activities: list[Activity],
    prices: dict[tuple[str, date], Decimal],
    *,
    start: date | None = None,
    end: date | None = None,
) -> dict:
    if not activities:
        return {"cagr": None, "years": None, "start_nav": "0", "end_nav": "0"}
    end_d = end or date.today()
    start_d = start or activities[0].trade_date
    start_nav = nav_as_of(activities, prices, start_d)
    # If start NAV is 0, use first contribution as base
    contributions, _ = cashflows_between(activities, start_d, start_d)
    base = start_nav if start_nav > 0 else contributions
    end_nav = nav_as_of(activities, prices, end_d)
    days = max((end_d - start_d).days, 1)
    years = Decimal(days) / Decimal("365.25")
    if base <= 0 or end_nav <= 0 or years <= 0:
        return {
            "cagr": None,
            "years": str(years.quantize(Decimal("0.01"))),
            "start_date": start_d.isoformat(),
            "end_date": end_d.isoformat(),
            "start_nav": str(start_nav),
            "end_nav": str(end_nav),
            "base": str(base),
        }
    ratio = end_nav / base
    value = (ratio ** (Decimal("1") / years) - Decimal("1")).quantize(Decimal("0.0001"))
    return {
        "cagr": str(value),
        "years": str(years.quantize(Decimal("0.01"))),
        "start_date": start_d.isoformat(),
        "end_date": end_d.isoformat(),
        "start_nav": str(start_nav),
        "end_nav": str(end_nav),
        "base": str(base),
    }


def nav_series(
    activities: list[Activity],
    prices: dict[tuple[str, date], Decimal],
    *,
    start: date | None = None,
    end: date | None = None,
) -> list[dict]:
    if not activities:
        return []
    start_d = start or activities[0].trade_date
    end_d = end or date.today()
    out: list[dict] = []
    cursor = start_d
    while cursor <= end_d:
        nav = nav_as_of(activities, prices, cursor)
        out.append({"date": cursor.isoformat(), "nav": str(nav)})
        cursor += timedelta(days=1)
    return out


def position_simple_return(session: Session, asset_key: str | None = None) -> list[dict]:
    lots = list_open_lots(session, asset_key=asset_key)
    by_asset: dict[str, dict[str, Decimal]] = {}
    meta: dict[str, dict[str, str | None]] = {}
    for lot in lots:
        key = lot["isin"]
        bucket = by_asset.setdefault(
            key,
            {"open_qty": ZERO, "invested": ZERO, "market_value": ZERO},
        )
        open_qty = _d(lot["open_qty"])
        unit_cost = _d(lot["unit_cost"])
        bucket["open_qty"] += open_qty
        bucket["invested"] += open_qty * unit_cost
        if lot["market_value"] is not None:
            bucket["market_value"] += _d(lot["market_value"])
        if key not in meta:
            meta[key] = {
                "symbol": lot.get("symbol"),
                "wkn": lot.get("wkn"),
                "isin_code": lot.get("isin_code"),
                "display_name": lot.get("display_name"),
                "display_id": lot.get("display_id") or key,
            }
    rows: list[dict] = []
    for key, values in sorted(by_asset.items()):
        invested = values["invested"]
        market = values["market_value"]
        simple = None
        if invested != 0 and market != 0:
            simple = ((market - invested) / invested).quantize(Decimal("0.0001"))
        ids = meta.get(key) or {}
        rows.append(
            {
                "isin": key,
                "symbol": ids.get("symbol"),
                "wkn": ids.get("wkn"),
                "isin_code": ids.get("isin_code"),
                "display_name": ids.get("display_name"),
                "display_id": ids.get("display_id") or key,
                "open_qty": str(values["open_qty"]),
                "invested": str(invested),
                "market_value": str(market),
                "simple_return": str(simple) if simple is not None else None,
            }
        )
    return rows


def dividend_summary(activities: list[Activity]) -> dict:
    total = ZERO
    by_asset: dict[str, Decimal] = {}
    for activity in activities:
        if activity.type != "DIVIDEND":
            continue
        amount = _d(activity.quantity) * _d(activity.unit_price)
        total += amount
        key = _asset_key(activity)
        by_asset[key] = by_asset.get(key, ZERO) + amount
    return {
        "total": str(total),
        "by_isin": [{"isin": k, "amount": str(v)} for k, v in sorted(by_asset.items())],
    }


def rebuild_metrics_daily(session: Session, *, end: date | None = None) -> int:
    activities = load_activities(session)
    if not activities:
        session.execute(delete(MetricsDaily))
        return 0
    prices = price_map(session)
    end_d = end or date.today()
    start_d = activities[0].trade_date
    session.execute(delete(MetricsDaily))
    count = 0
    cursor = start_d
    while cursor <= end_d:
        nav = nav_as_of(activities, prices, cursor)
        # invested ≈ cumulative net contributions to date
        contrib, withdr = cashflows_between(activities, start_d, cursor)
        invested = contrib - withdr
        unrealized = nav - invested if invested != 0 else ZERO
        mtd = period_return(
            activities,
            prices,
            label="mtd",
            start=max(start_d, month_start(cursor)),
            end=cursor,
        )
        ytd = period_return(
            activities,
            prices,
            label="ytd",
            start=max(start_d, year_start(cursor)),
            end=cursor,
        )
        r30 = period_return(
            activities,
            prices,
            label="30d",
            start=max(start_d, cursor - timedelta(days=30)),
            end=cursor,
        )
        session.add(
            MetricsDaily(
                metric_date=cursor,
                nav=nav,
                invested=invested,
                unrealized_gain=unrealized,
                mtd_return=mtd.period_return,
                ytd_return=ytd.period_return,
                return_30d=r30.period_return,
            )
        )
        count += 1
        cursor += timedelta(days=1)
    session.flush()
    return count


def overview_payload(session: Session, as_of: date | None = None) -> dict:
    from decimal import Decimal as D

    from portmetrics.metrics.irr import cashflow_timeline, irr_payload
    from portmetrics.metrics.risk import position_drawdown, risk_payload
    from portmetrics.metrics.tax_allowance import tax_allowance_payload
    from portmetrics.settings.portfolio import get_portfolio_settings

    activities = load_activities(session)
    prices = price_map(session)
    end = as_of or date.today()
    periods = compute_standard_periods(activities, prices, as_of=end)
    annual = compute_annual_returns(activities, prices, as_of=end)
    nav = nav_as_of(activities, prices, end) if activities else ZERO
    contrib, withdr = (
        cashflows_between(activities, activities[0].trade_date, end) if activities else (ZERO, ZERO)
    )
    invested = contrib - withdr
    portfolio_cfg = get_portfolio_settings(session)
    risk_free = D(portfolio_cfg["risk_free_rate"])
    mwr = irr_payload(activities, prices, as_of=end)
    positions = position_simple_return(session)
    for row in positions:
        key = row["isin"]
        row["irr"] = irr_payload(activities, prices, as_of=end, asset_key=key).get("irr")
        row["max_drawdown"] = position_drawdown(activities, prices, key, as_of=end).get(
            "max_drawdown"
        )
    return {
        "as_of": end.isoformat(),
        "nav": str(nav),
        "invested": str(invested),
        "unrealized_gain": str(nav - invested),
        "periods": [
            {
                "label": p.label,
                "start_date": p.start_date.isoformat(),
                "end_date": p.end_date.isoformat(),
                "start_nav": str(p.start_nav),
                "end_nav": str(p.end_nav),
                "contributions": str(p.contributions),
                "withdrawals": str(p.withdrawals),
                "period_return": str(p.period_return) if p.period_return is not None else None,
            }
            for p in periods
        ],
        "annual_returns": [_annual_return_dict(row) for row in annual],
        "cagr": cagr(activities, prices, end=end),
        "mwr": mwr,
        "cashflows": cashflow_timeline(activities),
        "risk": risk_payload(activities, prices, as_of=end, risk_free_rate=risk_free),
        "tax_allowance": tax_allowance_payload(session, as_of=end),
        "dividends": dividend_summary(activities),
        "positions": positions,
    }
