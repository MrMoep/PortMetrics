"""Tests for manual Paperless staging → activity matching."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import select

from portmetrics.db.models import Activity, DocumentLink, Lot, LotStatus, StagingImport
from portmetrics.paperless.match import match_staging_to_activities
from portmetrics.paperless.staging import STATUS_IMPORTED, STATUS_PENDING


def _activity(**overrides) -> Activity:
    base = dict(
        gf_activity_id=uuid4(),
        account_id="acc",
        isin="IE00BK5BQT80",
        symbol="VWCE.DE",
        type="BUY",
        quantity=Decimal("10"),
        unit_price=Decimal("100.50"),
        fee=Decimal("1.50"),
        currency="EUR",
        trade_date=date(2024, 6, 1),
    )
    base.update(overrides)
    return Activity(**base)


def _staging(doc_id: int = 42, **payload_overrides) -> StagingImport:
    payload = {
        "paperless_doc_id": doc_id,
        "wp_typ": "BUY",
        "isin": "IE00BK5BQT80",
        "symbol": "IE00BK5BQT80",
        "quantity": "10",
        "unit_price": "100.50",
        "fee": "1.50",
        "currency": "EUR",
        "trade_date": "2024-06-01",
    }
    payload.update(payload_overrides)
    return StagingImport(paperless_doc_id=doc_id, payload=payload, status=STATUS_PENDING)


def test_match_unique_activity(db_session) -> None:
    activity = _activity()
    staging = _staging()
    db_session.add_all([activity, staging])
    db_session.flush()
    db_session.add(
        Lot(
            activity_id=activity.id,
            isin="IE00BK5BQT80",
            open_qty=Decimal("10"),
            original_qty=Decimal("10"),
            cost_basis=Decimal("1006.50"),
            open_date=date(2024, 6, 1),
            status=LotStatus.OPEN,
        )
    )
    db_session.flush()

    result = match_staging_to_activities(db_session)
    assert result.scanned == 1
    assert result.matched == 1
    assert result.unmatched == 0

    db_session.refresh(staging)
    assert staging.status == STATUS_IMPORTED
    assert staging.gf_activity_id == activity.gf_activity_id
    link = db_session.scalar(
        select(DocumentLink).where(DocumentLink.paperless_doc_id == 42)
    )
    assert link is not None
    assert link.activity_id == activity.id
    assert link.lot_id is not None
    assert link.link_type == "matched"


def test_match_ambiguous_and_unmatched(db_session) -> None:
    a1 = _activity(unit_price=Decimal("100.00"))
    a2 = _activity(unit_price=Decimal("101.00"))
    staging_ambiguous = _staging(42, unit_price="100.50")
    staging_miss = _staging(
        43,
        isin="US0378331005",
        symbol="US0378331005",
    )
    db_session.add_all([a1, a2, staging_ambiguous, staging_miss])
    db_session.flush()

    result = match_staging_to_activities(db_session)
    assert result.matched == 0
    assert result.ambiguous == 1
    assert result.unmatched == 1
    assert staging_ambiguous.status == STATUS_PENDING
    assert staging_miss.status == STATUS_PENDING


def test_match_price_breaks_tie(db_session) -> None:
    a1 = _activity(unit_price=Decimal("100.50"))
    a2 = _activity(unit_price=Decimal("101.00"))
    staging = _staging(unit_price="100.50")
    db_session.add_all([a1, a2, staging])
    db_session.flush()

    result = match_staging_to_activities(db_session)
    assert result.matched == 1
    assert result.ambiguous == 0
    link = db_session.scalar(select(DocumentLink))
    assert link is not None
    assert link.activity_id == a1.id


def test_match_skips_already_linked_activity(db_session) -> None:
    activity = _activity()
    staging = _staging()
    other = _staging(99)
    db_session.add_all([activity, staging, other])
    db_session.flush()
    db_session.add(
        DocumentLink(
            paperless_doc_id=7,
            activity_id=activity.id,
            lot_id=None,
            link_type="source",
        )
    )
    db_session.flush()

    result = match_staging_to_activities(db_session)
    # Linked activity is excluded; both staging rows stay unmatched.
    assert result.matched == 0
    assert result.unmatched >= 1


def test_match_staging_bridges_preferred_symbol(db_session) -> None:
    from portmetrics.assets.identifiers import upsert_mapping

    activity = _activity(isin="VGWL.DE", symbol="VGWL.DE")
    staging = _staging(isin="IE00BK5BQT80", symbol="IE00BK5BQT80", wkn="A1JX52")
    db_session.add_all([activity, staging])
    upsert_mapping(
        db_session,
        isin="IE00BK5BQT80",
        preferred_symbol="VGWL.DE",
        wkn="A1JX52",
    )
    db_session.flush()

    result = match_staging_to_activities(db_session)
    assert result.matched == 1
    assert result.unmatched == 0
    db_session.refresh(staging)
    assert staging.status == STATUS_IMPORTED
