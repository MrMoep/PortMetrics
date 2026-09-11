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
    assert (
        pick_display_id(
            preference="name",
            symbol="VWCE.DE",
            wkn="A1JX52",
            isin="IE00BK5BQT80",
            asset_key="IE00BK5BQT80",
            display_name="Vanguard FTSE All-World",
        )
        == "Vanguard FTSE All-World"
    )
    assert (
        pick_display_id(
            preference="name",
            symbol="VWCE.DE",
            wkn="A1JX52",
            isin="IE00BK5BQT80",
            asset_key="IE00BK5BQT80",
            display_name=None,
        )
        == "VWCE.DE"
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
    assert list_open_lots(db_session)[0]["paperless_doc_id"] == 42


def test_lot_paperless_from_activity_comment(db_session: Session) -> None:
    row = Activity(
        gf_activity_id=uuid4(),
        account_id="acc",
        isin="IE00BK5BQT80",
        symbol="VWCE.DE",
        type="BUY",
        quantity=Decimal("5"),
        unit_price=Decimal("90"),
        fee=Decimal("0"),
        currency="EUR",
        trade_date=date(2024, 2, 1),
        comment="paperless:99 isin=IE00BK5BQT80",
    )
    db_session.add(row)
    db_session.flush()
    rebuild_lots(db_session)
    lots = list_open_lots(db_session)
    assert len(lots) == 1
    assert lots[0]["paperless_doc_id"] == 99


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


def test_suggest_symbol_majority_and_wkn_conflict(db_session: Session) -> None:
    from portmetrics.assets.identifiers import (
        apply_symbol_suggestion,
        suggest_symbol_from_history,
        upsert_mapping,
        wkn_conflict,
    )

    for i, symbol in enumerate(["VGWL.DE", "VGWL.DE", "VWRD.L"]):
        db_session.add(
            Activity(
                gf_activity_id=uuid4(),
                account_id="acc",
                isin="IE00BK5BQT80",
                symbol=symbol,
                type="BUY",
                quantity=Decimal("1"),
                unit_price=Decimal("100"),
                fee=Decimal("0"),
                currency="EUR",
                trade_date=date(2024, 1, i + 1),
            )
        )
    db_session.flush()
    suggestion = suggest_symbol_from_history(db_session, "IE00BK5BQT80")
    assert suggestion is not None
    assert suggestion.symbol == "VGWL.DE"
    assert suggestion.count == 2

    apply_symbol_suggestion(
        db_session,
        isin="IE00BK5BQT80",
        wkn="A1JX52",
    )
    row = db_session.get(AssetIdentifier, "IE00BK5BQT80")
    assert row is not None
    assert row.preferred_symbol == "VGWL.DE"
    assert row.wkn == "A1JX52"

    conflict = wkn_conflict(table_wkn="A1JX52", observed_wkn="WRONG1")
    assert conflict is not None
    assert "WRONG1" in conflict.message

    # Learning must not overwrite table WKN
    upsert_isin_wkn(db_session, isin="IE00BK5BQT80", wkn="WRONG1")
    db_session.refresh(row)
    assert row.wkn == "A1JX52"

    upsert_mapping(
        db_session,
        isin="IE00B4L5YC18",
        preferred_symbol="SXR8.DE",
        clear_missing=True,
    )
    bare = db_session.get(AssetIdentifier, "IE00B4L5YC18")
    assert bare is not None
    assert bare.wkn is None
    assert bare.preferred_symbol == "SXR8.DE"


def test_portfolio_asset_id_preference_default(db_session: Session) -> None:
    cfg = get_portfolio_settings(db_session)
    assert cfg["asset_id_preference"] == "symbol"
    saved = save_portfolio_settings(db_session, {"asset_id_preference": "isin"})
    assert saved["asset_id_preference"] == "isin"
    named = save_portfolio_settings(db_session, {"asset_id_preference": "name"})
    assert named["asset_id_preference"] == "name"


def test_display_name_in_lots(db_session: Session) -> None:
    from portmetrics.assets.identifiers import upsert_mapping

    upsert_mapping(
        db_session,
        isin="IE00BK5BQT80",
        wkn="A1JX52",
        preferred_symbol="VWCE.DE",
        display_name="Vanguard FTSE All-World",
    )
    db_session.add(
        Activity(
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
    )
    db_session.flush()
    rebuild_lots(db_session)
    save_portfolio_settings(db_session, {"asset_id_preference": "name"})
    lots = list_open_lots(db_session)
    assert lots[0]["display_name"] == "Vanguard FTSE All-World"
    assert lots[0]["display_id"] == "Vanguard FTSE All-World"
