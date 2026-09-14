"""Portfolio risk metrics: max drawdown, volatility, optional Sharpe."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from math import sqrt

from portmetrics.db.models import Activity
from portmetrics.metrics.periods import (
    ZERO,
    _d,
    holdings_as_of,
    last_trade_price_as_of,
    nav_series,
)

TRADING_DAYS = Decimal("252")


def _nav_values(
    activities: list[Activity],
    prices: dict[tuple[str, date], Decimal],
    *,
    start: date | None,
    end: date | None,
) -> list[tuple[date, Decimal]]:
    series = nav_series(activities, prices, start=start, end=end)
    out: list[tuple[date, Decimal]] = []
    for point in series:
        nav = _d(point["nav"])
        if nav > 0:
            out.append((date.fromisoformat(point["date"]), nav))
    return out


def max_drawdown(navs: list[tuple[date, Decimal]]) -> dict:
    if not navs:
        return {
            "max_drawdown": None,
            "peak_date": None,
            "trough_date": None,
        }
    peak = navs[0][1]
    peak_date = navs[0][0]
    worst = ZERO
    worst_peak_date = peak_date
    worst_trough_date = peak_date
    for day, nav in navs:
        if nav > peak:
            peak = nav
            peak_date = day
        dd = (nav - peak) / peak if peak > 0 else ZERO
        if dd < worst:
            worst = dd
            worst_peak_date = peak_date
            worst_trough_date = day
    return {
        "max_drawdown": str(worst.quantize(Decimal("0.0001"))),
        "peak_date": worst_peak_date.isoformat(),
        "trough_date": worst_trough_date.isoformat(),
    }


def daily_returns(navs: list[tuple[date, Decimal]]) -> list[Decimal]:
    rets: list[Decimal] = []
    for i in range(1, len(navs)):
        prev = navs[i - 1][1]
        cur = navs[i][1]
        if prev > 0:
            rets.append((cur - prev) / prev)
    return rets


def volatility_annualized(returns: list[Decimal]) -> Decimal | None:
    n = len(returns)
    if n < 2:
        return None
    mean = sum(returns, ZERO) / Decimal(n)
    var = sum((r - mean) ** 2 for r in returns) / Decimal(n - 1)
    if var < 0:
        return None
    daily_std = Decimal(str(sqrt(float(var))))
    return (daily_std * Decimal(str(sqrt(float(TRADING_DAYS))))).quantize(Decimal("0.0001"))


def sharpe_ratio(
    returns: list[Decimal],
    *,
    risk_free_annual: Decimal,
) -> Decimal | None:
    n = len(returns)
    if n < 2:
        return None
    mean = sum(returns, ZERO) / Decimal(n)
    vol = volatility_annualized(returns)
    if vol is None or vol == 0:
        return None
    ann_return = mean * TRADING_DAYS
    return ((ann_return - risk_free_annual) / vol).quantize(Decimal("0.0001"))


def risk_payload(
    activities: list[Activity],
    prices: dict[tuple[str, date], Decimal],
    *,
    as_of: date | None = None,
    risk_free_rate: Decimal = ZERO,
) -> dict:
    end = as_of or date.today()
    if not activities:
        return {
            "max_drawdown": None,
            "peak_date": None,
            "trough_date": None,
            "volatility": None,
            "sharpe": None,
            "risk_free_rate": str(risk_free_rate),
            "observations": 0,
        }
    navs = _nav_values(activities, prices, start=activities[0].trade_date, end=end)
    dd = max_drawdown(navs)
    rets = daily_returns(navs)
    vol = volatility_annualized(rets)
    sharpe = sharpe_ratio(rets, risk_free_annual=risk_free_rate)
    return {
        **dd,
        "volatility": str(vol) if vol is not None else None,
        "sharpe": str(sharpe) if sharpe is not None else None,
        "risk_free_rate": str(risk_free_rate),
        "observations": len(navs),
    }


def position_drawdown(
    activities: list[Activity],
    prices: dict[tuple[str, date], Decimal],
    asset_key: str,
    *,
    as_of: date | None = None,
) -> dict:
    end = as_of or date.today()
    if not activities:
        return {"max_drawdown": None, "peak_date": None, "trough_date": None}
    start_d = activities[0].trade_date
    navs: list[tuple[date, Decimal]] = []
    cursor = start_d
    while cursor <= end:
        qty = holdings_as_of(activities, cursor).get(asset_key, ZERO)
        if qty != 0:
            mark = prices.get((asset_key, cursor))
            if mark is None:
                mark = last_trade_price_as_of(activities, asset_key, cursor)
            if mark is not None:
                navs.append((cursor, qty * mark))
        cursor += timedelta(days=1)
    return max_drawdown(navs)
