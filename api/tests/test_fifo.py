from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from portmetrics.db.models import Activity
from portmetrics.fifo.engine import FifoError, apply_sell, create_lot_from_buy, estimate_tax
from portmetrics.fifo.service import list_open_lots, rebuild_lots, simulate_sell


def test_fifo_consumes_oldest_lot_first() -> None:
    lots = [
        create_lot_from_buy(
            activity_id=1,
            asset_key="IE00",
            quantity=Decimal("10"),
            unit_price=Decimal("100"),
            fee=Decimal("0"),
            trade_date=date(2023, 1, 1),
        ),
        create_lot_from_buy(
            activity_id=2,
            asset_key="IE00",
            quantity=Decimal("10"),
            unit_price=Decimal("120"),
            fee=Decimal("0"),
            trade_date=date(2024, 1, 1),
        ),
    ]
    result = apply_sell(
        lots,
        asset_key="IE00",
        quantity=Decimal("5"),
        unit_price=Decimal("150"),
        trade_date=date(2025, 1, 1),
    )
    assert len(result.consumptions) == 1
    assert result.consumptions[0].lot_activity_id == 1
    assert lots[0].open_qty == Decimal("5")
    assert lots[0].status == "PARTIAL"
    assert lots[1].open_qty == Decimal("10")
    assert result.realized_gain == Decimal("250")  # 5*(150-100)


def test_fifo_insufficient_qty_raises() -> None:
    lots = [
        create_lot_from_buy(
            activity_id=1,
            asset_key="IE00",
            quantity=Decimal("2"),
            unit_price=Decimal("10"),
            fee=Decimal("0"),
            trade_date=date(2023, 1, 1),
        )
    ]
    with pytest.raises(FifoError):
        apply_sell(
            lots,
            asset_key="IE00",
            quantity=Decimal("5"),
            unit_price=Decimal("12"),
        )


def test_estimate_tax_only_on_gains() -> None:
    assert estimate_tax(Decimal("100"), Decimal("0.25")) == Decimal("25.00")
    assert estimate_tax(Decimal("-10"), Decimal("0.25")) == Decimal("0")


def _buy(
    session: Session,
    *,
    qty: str,
    price: str,
    day: date,
    isin: str = "IE00BK5BQT80",
) -> Activity:
    row = Activity(
        gf_activity_id=uuid4(),
        account_id="acc",
        isin=isin,
        symbol="VWCE.DE",
        type="BUY",
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        fee=Decimal("1"),
        currency="EUR",
        trade_date=day,
    )
    session.add(row)
    session.flush()
    return row


def _sell(
    session: Session,
    *,
    qty: str,
    price: str,
    day: date,
    isin: str = "IE00BK5BQT80",
) -> Activity:
    row = Activity(
        gf_activity_id=uuid4(),
        account_id="acc",
        isin=isin,
        symbol="VWCE.DE",
        type="SELL",
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        fee=Decimal("0"),
        currency="EUR",
        trade_date=day,
    )
    session.add(row)
    session.flush()
    return row


def test_rebuild_lots_and_simulate(db_session: Session) -> None:
    _buy(db_session, qty="10", price="100", day=date(2023, 1, 1))
    _buy(db_session, qty="10", price="120", day=date(2024, 1, 1))
    _sell(db_session, qty="5", price="150", day=date(2025, 1, 1))
    db_session.flush()

    rebuilt = rebuild_lots(db_session)
    assert rebuilt.lots_created == 2
    assert rebuilt.consumptions == 1

    lots = list_open_lots(db_session, asset_key="IE00BK5BQT80")
    assert len(lots) == 2
    assert lots[0]["status"] == "PARTIAL"
    assert Decimal(lots[0]["open_qty"]) == Decimal("5")

    sim = simulate_sell(
        db_session,
        asset_key="IE00BK5BQT80",
        quantity=Decimal("5"),
        unit_price=Decimal("160"),
        tax_rate=Decimal("0.25"),
    )
    assert len(sim["lots"]) == 1
    assert sim["lots"][0]["buy_activity_id"] is not None
    assert Decimal(sim["estimated_tax"]) > 0
