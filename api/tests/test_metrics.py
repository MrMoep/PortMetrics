from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from portmetrics.db.models import Activity, MetricsDaily, PriceSnapshot
from portmetrics.fifo.service import rebuild_lots
from portmetrics.metrics.periods import (
    cagr,
    compute_standard_periods,
    dividend_summary,
    nav_as_of,
    overview_payload,
    period_return,
    rebuild_metrics_daily,
)


def _act(
    *,
    day: date,
    typ: str,
    qty: str,
    price: str,
    isin: str = "IE00",
    fee: str = "0",
) -> Activity:
    return Activity(
        id=1,
        gf_activity_id=uuid4(),
        account_id="a",
        isin=isin,
        symbol=isin,
        type=typ,
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        fee=Decimal(fee),
        currency="EUR",
        trade_date=day,
    )


def test_period_return_with_contribution() -> None:
    activities = [
        _act(day=date(2024, 1, 1), typ="BUY", qty="10", price="100"),
    ]
    # mutate ids uniquely
    activities[0].id = 1
    activities.append(
        Activity(
            id=2,
            gf_activity_id=uuid4(),
            account_id="a",
            isin="IE00",
            symbol="IE00",
            type="BUY",
            quantity=Decimal("10"),
            unit_price=Decimal("100"),
            fee=Decimal("0"),
            currency="EUR",
            trade_date=date(2024, 6, 1),
        )
    )
    prices = {
        ("IE00", date(2024, 1, 1)): Decimal("100"),
        ("IE00", date(2024, 12, 31)): Decimal("110"),
    }
    # Without explicit mid prices, last trade price carries forward via last_trade_price_as_of
    result = period_return(
        activities,
        prices,
        label="ytd",
        start=date(2024, 1, 1),
        end=date(2024, 12, 31),
    )
    assert result.end_nav == Decimal("2200")  # 20 * 110
    assert result.contributions == Decimal("2000")
    assert result.period_return is not None


def test_nav_uses_holdings() -> None:
    a = _act(day=date(2024, 1, 1), typ="BUY", qty="5", price="10")
    a.id = 1
    prices = {("IE00", date(2024, 2, 1)): Decimal("12")}
    assert nav_as_of([a], prices, date(2024, 2, 1)) == Decimal("60")


def test_dividends_sum() -> None:
    buy = _act(day=date(2024, 1, 1), typ="BUY", qty="1", price="10")
    buy.id = 1
    div = Activity(
        id=2,
        gf_activity_id=uuid4(),
        account_id="a",
        isin="IE00",
        symbol="IE00",
        type="DIVIDEND",
        quantity=Decimal("1"),
        unit_price=Decimal("2.5"),
        fee=Decimal("0"),
        currency="EUR",
        trade_date=date(2024, 3, 1),
    )
    summary = dividend_summary([buy, div])
    assert summary["total"] == "2.5"


def test_standard_periods_and_cagr_smoke() -> None:
    a = _act(day=date(2023, 1, 1), typ="BUY", qty="10", price="100")
    a.id = 1
    activities = [a]
    prices = {
        ("IE00", date(2023, 1, 1)): Decimal("100"),
        ("IE00", date(2024, 1, 1)): Decimal("110"),
    }
    periods = compute_standard_periods(activities, prices, as_of=date(2024, 1, 1))
    assert any(p.label == "ytd" for p in periods)
    result = cagr(activities, prices, start=date(2023, 1, 1), end=date(2024, 1, 1))
    assert result["cagr"] is not None


def test_annual_returns_ytd_and_prior_years() -> None:
    from portmetrics.metrics.periods import compute_annual_returns

    a = _act(day=date(2024, 6, 1), typ="BUY", qty="10", price="100")
    a.id = 1
    activities = [a]
    prices = {
        ("IE00", date(2024, 6, 1)): Decimal("100"),
        ("IE00", date(2024, 12, 31)): Decimal("110"),
        ("IE00", date(2025, 12, 31)): Decimal("120"),
        ("IE00", date(2026, 6, 1)): Decimal("130"),
    }
    rows = compute_annual_returns(activities, prices, as_of=date(2026, 6, 1))
    assert [r.label for r in rows] == ["ytd", "2025", "2024"]
    ytd = rows[0]
    assert ytd.start_date == date(2026, 1, 1)
    assert ytd.end_date == date(2026, 6, 1)
    assert ytd.return_to_date is None
    assert ytd.year_return is not None
    closed_2025 = rows[1]
    assert closed_2025.start_date == date(2025, 1, 1)
    assert closed_2025.end_date == date(2025, 12, 31)
    assert closed_2025.year_return is not None
    assert closed_2025.return_to_date is not None
    # Open-ended window continues past year-end → different (usually higher) return
    assert closed_2025.return_to_date != closed_2025.year_return
    first_year = rows[2]
    assert first_year.start_date == date(2024, 6, 1)
    assert first_year.end_date == date(2024, 12, 31)


def test_overview_payload_aggregates(db_session) -> None:
    db_session.add(
        Activity(
            gf_activity_id=uuid4(),
            account_id="a",
            isin="IE00",
            symbol="IE00",
            type="BUY",
            quantity=Decimal("10"),
            unit_price=Decimal("100"),
            fee=Decimal("0"),
            currency="EUR",
            trade_date=date(2026, 1, 5),
        )
    )
    db_session.add(
        PriceSnapshot(
            isin="IE00",
            symbol="IE00",
            price_date=date(2026, 1, 10),
            close_price=Decimal("110"),
            currency="EUR",
            source="test",
        )
    )
    db_session.flush()
    rebuild_lots(db_session)

    payload = overview_payload(db_session, as_of=date(2026, 1, 10))
    assert payload["as_of"] == "2026-01-10"
    assert Decimal(payload["nav"]) == Decimal("1100")
    assert Decimal(payload["invested"]) == Decimal("1000")
    assert Decimal(payload["unrealized_gain"]) == Decimal("100")
    assert len(payload["periods"]) > 0
    assert len(payload["annual_returns"]) == 1
    assert payload["annual_returns"][0]["label"] == "ytd"
    assert payload["annual_returns"][0]["return_to_date"] is None
    assert payload["cagr"] is not None
    assert "irr" in payload["mwr"]
    assert "max_drawdown" in payload["risk"]
    assert "remaining" in payload["tax_allowance"]
    assert payload["dividends"]["total"] == "0"
    assert len(payload["positions"]) == 1
    assert payload["positions"][0]["isin"] == "IE00"
    assert "irr" in payload["positions"][0]
    assert "max_drawdown" in payload["positions"][0]


def test_overview_payload_empty(db_session) -> None:
    payload = overview_payload(db_session, as_of=date(2026, 1, 1))
    assert payload["nav"] == "0"
    assert payload["invested"] == "0"
    assert payload["positions"] == []
    assert payload["cashflows"] == []
    assert payload["annual_returns"] == []


def test_rebuild_metrics_daily_persists_rows(db_session) -> None:
    db_session.add(
        Activity(
            gf_activity_id=uuid4(),
            account_id="a",
            isin="IE00",
            symbol="IE00",
            type="BUY",
            quantity=Decimal("5"),
            unit_price=Decimal("100"),
            fee=Decimal("0"),
            currency="EUR",
            trade_date=date(2026, 9, 1),
        )
    )
    db_session.add(
        PriceSnapshot(
            isin="IE00",
            symbol="IE00",
            price_date=date(2026, 9, 1),
            close_price=Decimal("105"),
            currency="EUR",
            source="test",
        )
    )
    db_session.flush()

    written = rebuild_metrics_daily(db_session, end=date(2026, 9, 3))
    assert written == 3
    rows = db_session.scalars(
        select(MetricsDaily).order_by(MetricsDaily.metric_date.asc())
    ).all()
    assert len(rows) == 3
    assert rows[0].metric_date == date(2026, 9, 1)
    assert Decimal(rows[0].nav) == Decimal("525")
    assert Decimal(rows[0].invested) == Decimal("500")
    assert rows[-1].metric_date == date(2026, 9, 3)

    # Rebuild replaces previous rows
    again = rebuild_metrics_daily(db_session, end=date(2026, 9, 2))
    assert again == 2
    assert len(db_session.scalars(select(MetricsDaily)).all()) == 2


def test_rebuild_metrics_daily_empty_clears(db_session) -> None:
    assert rebuild_metrics_daily(db_session, end=date(2026, 9, 1)) == 0
    assert db_session.scalars(select(MetricsDaily)).all() == []
