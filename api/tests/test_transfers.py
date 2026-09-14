from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from portmetrics.db.models import Activity, DepotTransfer, LotConsumption
from portmetrics.fifo.engine import FifoError, apply_transfer, create_lot_from_buy
from portmetrics.fifo.service import list_open_lots, rebuild_lots
from portmetrics.fifo.transfers import create_transfer, delete_transfer, list_transfers


def _buy(
    session: Session,
    *,
    qty: str,
    price: str,
    day: date,
    account_id: str = "acc-a",
) -> Activity:
    row = Activity(
        gf_activity_id=uuid4(),
        account_id=account_id,
        isin="IE00BK5BQT80",
        symbol="VWCE.DE",
        type="BUY",
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        fee=Decimal("0"),
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
    account_id: str = "acc-b",
) -> Activity:
    row = Activity(
        gf_activity_id=uuid4(),
        account_id=account_id,
        isin="IE00BK5BQT80",
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


def test_apply_transfer_moves_cost_basis_without_gain() -> None:
    lots = [
        create_lot_from_buy(
            activity_id=1,
            asset_key="IE00",
            quantity=Decimal("10"),
            unit_price=Decimal("100"),
            fee=Decimal("0"),
            trade_date=date(2023, 1, 1),
            account_id="acc-a",
        )
    ]
    lots[0].id = 1
    result = apply_transfer(
        lots,
        asset_key="IE00",
        quantity=Decimal("4"),
        from_account_id="acc-a",
        to_account_id="acc-b",
        transfer_date=date(2024, 6, 1),
    )
    assert len(result.moves) == 1
    assert result.moves[0].cost_basis == Decimal("400")
    assert lots[0].open_qty == Decimal("6")
    assert lots[0].status == "PARTIAL"
    dest = result.new_lots[0]
    assert dest.account_id == "acc-b"
    assert dest.open_qty == Decimal("4")
    assert dest.cost_basis == Decimal("400")
    assert dest.open_date == date(2023, 1, 1)
    assert dest.activity_id == 1


def test_rebuild_applies_depot_transfer(db_session) -> None:
    _buy(db_session, qty="10", price="100", day=date(2023, 1, 1), account_id="acc-a")
    db_session.add(
        DepotTransfer(
            from_account_id="acc-a",
            to_account_id="acc-b",
            isin="IE00BK5BQT80",
            quantity=Decimal("4"),
            transfer_date=date(2024, 1, 1),
        )
    )
    db_session.flush()

    rebuilt = rebuild_lots(db_session)
    assert rebuilt.transfers_applied == 1
    assert rebuilt.lots_created == 2
    assert rebuilt.consumptions == 0
    assert db_session.scalars(select(LotConsumption)).all() == []

    lots_a = list_open_lots(db_session, account_id="acc-a")
    lots_b = list_open_lots(db_session, account_id="acc-b")
    assert len(lots_a) == 1
    assert Decimal(lots_a[0]["open_qty"]) == Decimal("6")
    assert len(lots_b) == 1
    assert Decimal(lots_b[0]["open_qty"]) == Decimal("4")
    assert lots_b[0]["open_date"] == "2023-01-01"


def test_sell_after_transfer_stays_in_destination(db_session) -> None:
    _buy(db_session, qty="10", price="100", day=date(2023, 1, 1), account_id="acc-a")
    db_session.add(
        DepotTransfer(
            from_account_id="acc-a",
            to_account_id="acc-b",
            isin="IE00BK5BQT80",
            quantity=Decimal("10"),
            transfer_date=date(2024, 1, 1),
        )
    )
    _sell(db_session, qty="3", price="150", day=date(2025, 1, 1), account_id="acc-b")
    db_session.flush()

    rebuilt = rebuild_lots(db_session)
    assert rebuilt.consumptions == 1
    lots_a = list_open_lots(db_session, account_id="acc-a")
    lots_b = list_open_lots(db_session, account_id="acc-b")
    assert lots_a == []
    assert len(lots_b) == 1
    assert Decimal(lots_b[0]["open_qty"]) == Decimal("7")


def test_create_and_delete_transfer_api_flow(db_session) -> None:
    _buy(db_session, qty="10", price="100", day=date(2023, 1, 1), account_id="acc-a")
    rebuild_lots(db_session)

    created = create_transfer(
        db_session,
        from_account_id="acc-a",
        to_account_id="acc-b",
        isin="IE00BK5BQT80",
        quantity=Decimal("2"),
        transfer_date=date(2024, 5, 1),
        comment="Umzug",
    )
    assert created["from_account_id"] == "acc-a"
    assert len(list_transfers(db_session)) == 1
    assert Decimal(
        list_open_lots(db_session, account_id="acc-b")[0]["open_qty"]
    ) == Decimal("2")

    assert delete_transfer(db_session, created["id"]) is True
    assert list_transfers(db_session) == []
    assert list_open_lots(db_session, account_id="acc-b") == []
    assert Decimal(
        list_open_lots(db_session, account_id="acc-a")[0]["open_qty"]
    ) == Decimal("10")


def test_transfer_insufficient_qty(db_session) -> None:
    _buy(db_session, qty="2", price="100", day=date(2023, 1, 1), account_id="acc-a")
    with pytest.raises(FifoError, match="Insufficient"):
        create_transfer(
            db_session,
            from_account_id="acc-a",
            to_account_id="acc-b",
            isin="IE00BK5BQT80",
            quantity=Decimal("5"),
            transfer_date=date(2024, 1, 1),
        )
