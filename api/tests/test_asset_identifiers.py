from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from portmetrics.assets.identifiers import (
    backfill_from_staging,
    pick_display_id,
    upsert_isin_wkn,
    wkn_map,
)
from portmetrics.db.models import Activity, AssetIdentifier, StagingImport
from portmetrics.fifo.service import list_open_lots, rebuild_lots
from portmetrics.settings.portfolio import get_portfolio_settings, save_portfolio_settings


def test_pick_display_id_fallback_chain() -> None:
    assert (
        pick_display_id(
            preference="wkn",
            symbol="VWCE.DE",
            wkn=None,
            isin="IE00BK5BQT80",
            asset_key="IE00BK5BQT80",
        )
        == "VWCE.DE"
    )
    assert (
        pick_display_id(
            preference="symbol",
            symbol=None,
            wkn="A1JX52",
            isin="IE00BK5BQT80",
            asset_key="IE00BK5BQT80",
        )
        == "IE00BK5BQT80"
    )


def test_upsert_isin_wkn_and_lots_display(db_session: Session) -> None:
    upsert_isin_wkn(
        db_session,
        isin="IE00BK5BQT80",
        wkn="A1JX52",
        paperless_doc_id=42,
    )
    assert wkn_map(db_session)["IE00BK5BQT80"] == "A1JX52"

    row = Activity(
        gf_activity_id=uuid4(),
        account_id="acc",
        isin="IE00BK5BQT80",
        symbol="VWCE.DE",
        type="BUY",
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
        fee=Decimal("0"),
        currency="EUR",
        trade_date=date(2024, 1, 1),
    )
    db_session.add(row)
    db_session.flush()
    rebuild_lots(db_session)

    save_portfolio_settings(db_session, {"asset_id_preference": "wkn"})
    lots = list_open_lots(db_session)
    assert len(lots) == 1
    assert lots[0]["wkn"] == "A1JX52"
    assert lots[0]["symbol"] == "VWCE.DE"
    assert lots[0]["isin_code"] == "IE00BK5BQT80"
    assert lots[0]["display_id"] == "A1JX52"

    save_portfolio_settings(db_session, {"asset_id_preference": "symbol"})
    assert list_open_lots(db_session)[0]["display_id"] == "VWCE.DE"


def test_backfill_from_staging(db_session: Session) -> None:
    db_session.add(
        StagingImport(
            paperless_doc_id=7,
            payload={
                "paperless_doc_id": 7,
                "isin": "IE00BK5BQT80",
                "wkn": "A1JX52",
                "symbol": "IE00BK5BQT80",
            },
            status="pending",
        )
    )
    db_session.flush()
    assert backfill_from_staging(db_session) == 1
    row = db_session.get(AssetIdentifier, "IE00BK5BQT80")
    assert row is not None
    assert row.wkn == "A1JX52"


def test_portfolio_asset_id_preference_default(db_session: Session) -> None:
    cfg = get_portfolio_settings(db_session)
    assert cfg["asset_id_preference"] == "symbol"
    saved = save_portfolio_settings(db_session, {"asset_id_preference": "isin"})
    assert saved["asset_id_preference"] == "isin"
