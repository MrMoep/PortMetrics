"""Tests for lot ↔ Paperless document matching and preview."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

import httpx
from sqlalchemy import select

from portmetrics.db.models import Activity, DocumentLink, Lot, LotStatus, StagingImport
from portmetrics.paperless.client import PaperlessClient
from portmetrics.paperless.mapping import save_paperless_settings
from portmetrics.paperless.match import (
    link_lot_to_document,
    match_lots_to_documents,
    parse_paperless_doc_ref,
    preview_link_scope,
)
from portmetrics.paperless.staging import STATUS_IMPORTED, STATUS_PENDING, STATUS_REJECTED

FIELD_RESULTS = [
    {
        "id": 1,
        "name": "wp_typ",
        "data_type": "select",
        "extra_data": {
            "select_options": [
                {"id": "SXXGAXZIVEH4OXSZ", "label": "BUY"},
                {"id": "J6QQIILJAHMITXKE", "label": "SELL"},
            ]
        },
    },
    {"id": 2, "name": "isin", "data_type": "string"},
    {"id": 3, "name": "wkn", "data_type": "string"},
    {"id": 4, "name": "stueckzahl", "data_type": "float"},
    {"id": 5, "name": "kurs", "data_type": "monetary"},
    {"id": 6, "name": "gebuehr", "data_type": "monetary"},
]


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


def _doc(doc_id: int = 42, **field_overrides) -> dict:
    fields = {
        1: "SXXGAXZIVEH4OXSZ",
        2: "IE00BK5BQT80",
        3: "A1JX52",
        4: "10",
        5: "EUR100.50",
        6: "EUR1.50",
    }
    fields.update(field_overrides)
    return {
        "id": doc_id,
        "title": "Kauf",
        "created": "2024-06-01T12:00:00.000Z",
        "custom_fields": [{"field": fid, "value": val} for fid, val in fields.items()],
    }


def _client(docs: list[dict], *, count: int | None = None) -> PaperlessClient:
    total = count if count is not None else len(docs)

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/custom_fields/"):
            return httpx.Response(200, json={"results": FIELD_RESULTS})
        if path.rstrip("/").endswith("/documents") or path.endswith("/documents/"):
            return httpx.Response(
                200,
                json={"count": total, "results": docs, "next": None},
            )
        for doc in docs:
            if path.endswith(f"/documents/{doc['id']}/"):
                return httpx.Response(200, json=doc)
        raise AssertionError(path)

    return PaperlessClient(
        "http://paperless.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )


def test_parse_paperless_doc_ref() -> None:
    assert parse_paperless_doc_ref(42) == 42
    assert parse_paperless_doc_ref("99") == 99
    assert parse_paperless_doc_ref("https://paperless.example/documents/123/") == 123
    assert parse_paperless_doc_ref("https://paperless.example/documents/456") == 456
    assert parse_paperless_doc_ref("") is None


def test_preview_link_scope(db_session) -> None:
    activity = _activity()
    db_session.add(activity)
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
    save_paperless_settings(
        db_session,
        {"field_map": {"type": 1, "isin": 2, "wkn": 3, "quantity": 4, "unit_price": 5, "fee": 6}},
    )

    preview = preview_link_scope(db_session, _client([_doc()], count=126))
    assert preview.document_count == 126
    assert preview.unlinked_lots == 1
    assert preview.warn_large is True


def test_match_lots_links_and_clears_staging(db_session) -> None:
    activity = _activity()
    staging = StagingImport(
        paperless_doc_id=42,
        payload={"wp_typ": "BUY", "isin": "IE00BK5BQT80"},
        status=STATUS_REJECTED,
    )
    db_session.add_all([activity, staging])
    db_session.flush()
    lot = Lot(
        activity_id=activity.id,
        isin="IE00BK5BQT80",
        open_qty=Decimal("10"),
        original_qty=Decimal("10"),
        cost_basis=Decimal("1006.50"),
        open_date=date(2024, 6, 1),
        status=LotStatus.OPEN,
    )
    db_session.add(lot)
    db_session.flush()
    save_paperless_settings(
        db_session,
        {"field_map": {"type": 1, "isin": 2, "wkn": 3, "quantity": 4, "unit_price": 5, "fee": 6}},
    )

    result = match_lots_to_documents(db_session, _client([_doc(42)]))
    assert result.scanned == 1
    assert result.matched == 1
    db_session.refresh(staging)
    assert staging.status == STATUS_IMPORTED
    assert staging.gf_activity_id == activity.gf_activity_id
    link = db_session.scalar(select(DocumentLink).where(DocumentLink.lot_id == lot.id))
    assert link is not None
    assert link.paperless_doc_id == 42


def test_link_lot_manual(db_session) -> None:
    activity = _activity()
    db_session.add(activity)
    db_session.flush()
    lot = Lot(
        activity_id=activity.id,
        isin="IE00BK5BQT80",
        open_qty=Decimal("10"),
        original_qty=Decimal("10"),
        cost_basis=Decimal("1006.50"),
        open_date=date(2024, 6, 1),
        status=LotStatus.OPEN,
    )
    pending = StagingImport(
        paperless_doc_id=42,
        payload={},
        status=STATUS_PENDING,
    )
    db_session.add_all([lot, pending])
    db_session.flush()
    save_paperless_settings(
        db_session,
        {"field_map": {"type": 1, "isin": 2, "wkn": 3, "quantity": 4, "unit_price": 5, "fee": 6}},
    )

    detail = link_lot_to_document(
        db_session,
        _client([_doc(42)]),
        lot_id=lot.id,
        paperless_ref="https://paperless.test/documents/42/",
    )
    assert detail["paperless_doc_id"] == 42
    assert detail["link_type"] == "manual"
    db_session.refresh(pending)
    assert pending.status == STATUS_IMPORTED
