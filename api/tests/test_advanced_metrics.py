from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from portmetrics.db.models import Activity
from portmetrics.metrics.irr import (
    annualize_daily_irr,
    dated_cashflows,
    irr_payload,
    solve_irr_daily,
)
from portmetrics.metrics.risk import (
    daily_returns,
    max_drawdown,
    risk_payload,
    volatility_annualized,
)
from portmetrics.settings.portfolio import get_portfolio_settings, save_portfolio_settings


def _act(
    *,
    day: date,
    typ: str,
    qty: str,
    price: str,
    isin: str = "IE00",
    fee: str = "0",
    id_: int = 1,
) -> Activity:
    return Activity(
        id=id_,
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


def test_irr_known_cashflows() -> None:
    # Invest 100, one year later worth 110 → ~10% IRR
    activities = [
        _act(day=date(2023, 1, 1), typ="BUY", qty="1", price="100", id_=1),
    ]
    prices = {("IE00", date(2024, 1, 1)): Decimal("110")}
    result = irr_payload(activities, prices, as_of=date(2024, 1, 1))
    assert result["irr"] is not None
    irr = Decimal(result["irr"])
    assert Decimal("0.08") < irr < Decimal("0.12")
    assert result["simple_return"] == "0.1000"


def test_solve_irr_daily_roundtrip() -> None:
    flows = [
        (date(2024, 1, 1), Decimal("-100")),
        (date(2024, 1, 11), Decimal("110")),
    ]
    daily = solve_irr_daily(flows)
    assert daily is not None
    ann = annualize_daily_irr(daily)
    assert ann > 0


def test_dated_cashflows_signs() -> None:
    activities = [
        _act(day=date(2024, 1, 1), typ="BUY", qty="2", price="50", fee="1", id_=1),
        _act(day=date(2024, 2, 1), typ="SELL", qty="1", price="60", fee="1", id_=2),
        _act(day=date(2024, 3, 1), typ="DIVIDEND", qty="1", price="2.5", id_=3),
        _act(day=date(2024, 4, 1), typ="INTEREST", qty="1", price="1.5", id_=4),
    ]
    flows = dated_cashflows(activities)
    assert flows[0][1] == Decimal("-101")
    assert flows[1][1] == Decimal("59")
    assert flows[2][1] == Decimal("2.5")
    assert flows[3][1] == Decimal("1.5")


def test_cashflow_timeline_includes_type_and_asset() -> None:
    from portmetrics.metrics.irr import cashflow_timeline

    activities = [
        _act(day=date(2024, 1, 1), typ="BUY", qty="1", price="100", isin="VWCE", id_=1),
        _act(day=date(2024, 6, 1), typ="DIVIDEND", qty="1", price="3", isin="VWCE", id_=2),
    ]
    rows = cashflow_timeline(activities, display_id_by_key={"VWCE": "VWCE"})
    assert len(rows) == 2
    assert rows[0]["type"] == "BUY"
    assert rows[0]["asset"] == "VWCE"
    assert rows[1]["type"] == "DIVIDEND"
    assert rows[1]["amount"] == "3"

def test_max_drawdown() -> None:
    navs = [
        (date(2024, 1, 1), Decimal("100")),
        (date(2024, 1, 2), Decimal("120")),
        (date(2024, 1, 3), Decimal("90")),
        (date(2024, 1, 4), Decimal("100")),
    ]
    dd = max_drawdown(navs)
    assert dd["max_drawdown"] == "-0.2500"
    assert dd["peak_date"] == "2024-01-02"
    assert dd["trough_date"] == "2024-01-03"


def test_volatility_smoke() -> None:
    navs = [
        (date(2024, 1, 1), Decimal("100")),
        (date(2024, 1, 2), Decimal("101")),
        (date(2024, 1, 3), Decimal("99")),
        (date(2024, 1, 4), Decimal("102")),
    ]
    vol = volatility_annualized(daily_returns(navs))
    assert vol is not None
    assert vol > 0


def test_risk_payload_empty() -> None:
    result = risk_payload([], {})
    assert result["max_drawdown"] is None
    assert result["observations"] == 0


def test_portfolio_settings_roundtrip(db_session) -> None:
    cfg = get_portfolio_settings(db_session)
    assert cfg["tax_allowance_eur"] == "1000"
    saved = save_portfolio_settings(
        db_session,
        {
            "tax_allowance_eur": "2000",
            "tax_warn_pct": "0.9",
            "risk_free_rate": "0.02",
        },
    )
    assert saved["tax_allowance_eur"] == "2000"
    assert saved["risk_free_rate"] == "0.02"
    assert saved["asset_id_preference"] == "symbol"
    assert get_portfolio_settings(db_session)["tax_warn_pct"] == "0.9"


def test_tax_allowance_from_fifo(db_session) -> None:
    from portmetrics.fifo.service import rebuild_lots
    from portmetrics.metrics.tax_allowance import tax_allowance_payload

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
            trade_date=date(2025, 1, 10),
        )
    )
    db_session.add(
        Activity(
            gf_activity_id=uuid4(),
            account_id="a",
            isin="IE00",
            symbol="IE00",
            type="SELL",
            quantity=Decimal("5"),
            unit_price=Decimal("120"),
            fee=Decimal("0"),
            currency="EUR",
            trade_date=date(2025, 3, 10),
        )
    )
    db_session.flush()
    rebuild_lots(db_session)
    save_portfolio_settings(db_session, {"tax_allowance_eur": "1000", "tax_warn_pct": "0.5"})
    payload = tax_allowance_payload(db_session, as_of=date(2025, 6, 1))
    assert Decimal(payload["realized_ytd"]) == Decimal("100")
    assert Decimal(payload["dividends_ytd"]) == Decimal("0")
    assert Decimal(payload["interest_ytd"]) == Decimal("0")
    assert Decimal(payload["taxable_ytd"]) == Decimal("100")
    assert Decimal(payload["remaining"]) == Decimal("900")
    assert payload["warn"] is False


def test_tax_allowance_includes_dividends_and_interest(db_session) -> None:
    from portmetrics.metrics.tax_allowance import tax_allowance_payload

    db_session.add(
        Activity(
            gf_activity_id=uuid4(),
            account_id="a",
            isin="IE00",
            symbol="IE00",
            type="DIVIDEND",
            quantity=Decimal("1"),
            unit_price=Decimal("40"),
            fee=Decimal("5"),
            currency="EUR",
            trade_date=date(2025, 4, 1),
        )
    )
    db_session.add(
        Activity(
            gf_activity_id=uuid4(),
            account_id="a",
            isin="CASH",
            symbol="CASH",
            type="INTEREST",
            quantity=Decimal("1"),
            unit_price=Decimal("10"),
            fee=Decimal("0"),
            currency="EUR",
            trade_date=date(2025, 5, 1),
        )
    )
    db_session.add(
        Activity(
            gf_activity_id=uuid4(),
            account_id="a",
            isin="IE00",
            symbol="IE00",
            type="DIVIDEND",
            quantity=Decimal("1"),
            unit_price=Decimal("99"),
            fee=Decimal("0"),
            currency="EUR",
            trade_date=date(2024, 12, 1),
        )
    )
    db_session.flush()
    save_portfolio_settings(db_session, {"tax_allowance_eur": "1000", "tax_warn_pct": "0.5"})
    payload = tax_allowance_payload(db_session, as_of=date(2025, 6, 1))
    assert Decimal(payload["dividends_ytd"]) == Decimal("40")
    assert Decimal(payload["interest_ytd"]) == Decimal("10")
    assert Decimal(payload["taxable_ytd"]) == Decimal("50")
    assert Decimal(payload["remaining"]) == Decimal("950")
