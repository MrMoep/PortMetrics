from __future__ import annotations

from uuid import uuid4

import httpx
import pytest
from sqlalchemy import select

from portmetrics.db.models import DocumentLink, StagingImport
from portmetrics.ghostfolio.client import GhostfolioClient
from portmetrics.paperless.client import PaperlessClient, extract_custom_fields
from portmetrics.paperless.mapping import (
    extract_fields_by_roles,
    get_paperless_settings,
    resolve_role_field_map,
    save_paperless_settings,
)
from portmetrics.paperless.staging import (
    STATUS_IMPORTED,
    STATUS_PENDING,
    STATUS_REJECTED,
    build_staging_payload,
    confirm_staging,
    reject_staging,
    sync_paperless_documents,
)

FIELD_MAP = {
    "wp_typ": 1,
    "isin": 2,
    "symbol": 3,
    "stueckzahl": 4,
    "kurs": 5,
    "gebuehr": 6,
    "handelsdatum": 7,
    "waehrung": 8,
    "gf_import_status": 9,
    "gf_activity_id": 10,
}

ROLE_MAP = {
    "type": 1,
    "isin": 2,
    "symbol": 3,
    "quantity": 4,
    "unit_price": 5,
    "fee": 6,
    "trade_date": 7,
    "currency": 8,
    "import_status": 9,
    "activity_id": 10,
}


def _doc(doc_id: int = 42) -> dict:
    return {
        "id": doc_id,
        "title": "Kauf VWCE",
        "custom_fields": [
            {"field": 1, "value": "BUY"},
            {"field": 2, "value": "IE00BK5BQT80"},
            {"field": 3, "value": "VWCE.DE"},
            {"field": 4, "value": "10"},
            {"field": 5, "value": "100.5"},
            {"field": 6, "value": "1.5"},
            {"field": 7, "value": "2024-06-01"},
            {"field": 8, "value": "EUR"},
            {"field": 9, "value": "pending"},
        ],
    }


def _fields_handler(request: httpx.Request) -> httpx.Response | None:
    if request.url.path.endswith("/custom_fields/"):
        return httpx.Response(
            200,
            json={"results": [{"id": fid, "name": name} for name, fid in FIELD_MAP.items()]},
        )
    return None


def test_extract_custom_fields() -> None:
    fields = extract_custom_fields(_doc(), FIELD_MAP)
    assert fields["isin"] == "IE00BK5BQT80"
    assert fields["stueckzahl"] == "10"


def test_extract_fields_by_roles() -> None:
    fields = extract_fields_by_roles(_doc(), ROLE_MAP)
    assert fields["isin"] == "IE00BK5BQT80"
    assert fields["quantity"] == "10"


def test_build_staging_payload_legacy_names() -> None:
    payload = build_staging_payload(_doc(), extract_custom_fields(_doc(), FIELD_MAP))
    assert payload["symbol"] == "VWCE.DE"
    assert payload["wp_typ"] == "BUY"
    assert payload["trade_date"] == "2024-06-01"
    assert payload["quantity"] == "10"


def test_build_staging_payload_roles() -> None:
    payload = build_staging_payload(_doc(), extract_fields_by_roles(_doc(), ROLE_MAP))
    assert payload["symbol"] == "VWCE.DE"
    assert payload["quantity"] == "10"


def test_paperless_list_documents_and_fields() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Token secret"
        handled = _fields_handler(request)
        if handled:
            return handled
        if request.url.path.endswith("/documents/"):
            return httpx.Response(200, json={"results": [_doc()]})
        raise AssertionError(request.url.path)

    transport = httpx.MockTransport(handler)
    client = PaperlessClient("http://paperless.test", "secret", transport=transport)
    assert client.custom_field_map()["isin"] == 2
    assert len(client.list_documents()) == 1


def test_sync_uses_legacy_name_fallback(db_session) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        handled = _fields_handler(request)
        if handled:
            return handled
        if request.url.path.endswith("/documents/"):
            return httpx.Response(200, json={"results": [_doc(), _doc(43)]})
        raise AssertionError(request.url.path)

    transport = httpx.MockTransport(handler)
    client = PaperlessClient("http://paperless.test", "secret", transport=transport)
    first = sync_paperless_documents(db_session, client)
    assert first.upserted == 2
    second = sync_paperless_documents(db_session, client)
    assert second.upserted == 2
    rows = db_session.scalars(select(StagingImport)).all()
    assert len(rows) == 2
    assert all(row.status == STATUS_PENDING for row in rows)


def test_sync_uses_stored_role_mapping(db_session) -> None:
    # Map roles to ids but use different Paperless names than legacy defaults.
    save_paperless_settings(
        db_session,
        {
            "field_map": ROLE_MAP,
            "tag": None,
        },
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/custom_fields/"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": 1, "name": "TradeType"},
                        {"id": 2, "name": "ISIN"},
                        {"id": 3, "name": "Ticker"},
                        {"id": 4, "name": "Qty"},
                        {"id": 5, "name": "Price"},
                        {"id": 6, "name": "Fee"},
                        {"id": 7, "name": "TradeDate"},
                        {"id": 8, "name": "CCY"},
                        {"id": 9, "name": "ImportStatus"},
                        {"id": 10, "name": "ActivityId"},
                    ]
                },
            )
        if request.url.path.endswith("/documents/"):
            return httpx.Response(200, json={"results": [_doc(55)]})
        raise AssertionError(request.url.path)

    client = PaperlessClient(
        "http://paperless.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = sync_paperless_documents(db_session, client)
    assert result.upserted == 1
    row = db_session.scalar(select(StagingImport).where(StagingImport.paperless_doc_id == 55))
    assert row is not None
    assert row.payload["symbol"] == "VWCE.DE"


def test_save_and_resolve_mapping(db_session) -> None:
    saved = save_paperless_settings(
        db_session,
        {
            "field_map": {"isin": 2, "quantity": 4, "unit_price": 5, "trade_date": 7},
            "tag": "wertpapier",
            "ghostfolio_default_account_id": "acc-9",
            "ghostfolio_data_source": "MANUAL",
        },
    )
    assert saved["tag"] == "wertpapier"
    assert saved["field_map"]["isin"] == 2
    assert get_paperless_settings(db_session)["ghostfolio_data_source"] == "MANUAL"

    def handler(request: httpx.Request) -> httpx.Response:
        handled = _fields_handler(request)
        if handled:
            return handled
        raise AssertionError(request.url.path)

    client = PaperlessClient(
        "http://paperless.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    resolved = resolve_role_field_map(db_session, client)
    assert resolved["isin"] == 2
    assert resolved["quantity"] == 4


def test_reject_and_confirm_staging(db_session, monkeypatch) -> None:
    monkeypatch.setattr(
        "portmetrics.paperless.mapping.settings.ghostfolio_default_account_id",
        "acc-1",
    )
    monkeypatch.setattr(
        "portmetrics.paperless.mapping.settings.ghostfolio_data_source",
        "YAHOO",
    )

    row = StagingImport(
        paperless_doc_id=99,
        payload=build_staging_payload(_doc(99), extract_custom_fields(_doc(99), FIELD_MAP)),
        status=STATUS_PENDING,
    )
    db_session.add(row)
    db_session.flush()

    rejected = reject_staging(db_session, row.id)
    assert rejected["status"] == STATUS_REJECTED

    row.status = STATUS_PENDING
    gf_id = uuid4()

    def gf_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt"})
        if request.url.path.endswith("/import"):
            body = request.read()
            assert b"VWCE.DE" in body
            return httpx.Response(201, json={"activities": [{"id": str(gf_id)}]})
        raise AssertionError(request.url.path)

    ghostfolio = GhostfolioClient(
        "http://ghostfolio.test",
        "tok",
        transport=httpx.MockTransport(gf_handler),
    )
    confirmed = confirm_staging(db_session, row.id, ghostfolio, paperless=None)
    assert confirmed["status"] == STATUS_IMPORTED
    assert confirmed["gf_activity_id"] == str(gf_id)
    links = db_session.scalars(select(DocumentLink)).all()
    assert len(links) == 1
    assert links[0].paperless_doc_id == 99


def test_confirm_missing_raises(db_session) -> None:
    bad = httpx.MockTransport(lambda _r: httpx.Response(500))
    ghostfolio = GhostfolioClient("http://ghostfolio.test", "tok", transport=bad)
    with pytest.raises(LookupError):
        confirm_staging(db_session, 99999, ghostfolio)


def test_parse_paperless_document_id() -> None:
    from portmetrics.paperless.staging import parse_paperless_document_id

    assert parse_paperless_document_id({"document_id": 42}) == 42
    assert parse_paperless_document_id({"doc_url": "https://p.example/documents/99/details"}) == 99
    assert parse_paperless_document_id("https://p.example/api/documents/7/") == 7
    assert parse_paperless_document_id({"id": "nope"}) is None


def test_ingest_paperless_document(db_session) -> None:
    from portmetrics.paperless.staging import ingest_paperless_document

    def handler(request: httpx.Request) -> httpx.Response:
        handled = _fields_handler(request)
        if handled:
            return handled
        if request.url.path.endswith("/documents/77/"):
            return httpx.Response(200, json=_doc(77))
        raise AssertionError(request.url.path)

    client = PaperlessClient(
        "http://paperless.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = ingest_paperless_document(db_session, client, 77)
    assert result.action == "upserted"
    assert result.document_id == 77
    row = db_session.scalar(select(StagingImport).where(StagingImport.paperless_doc_id == 77))
    assert row is not None
    assert row.status == STATUS_PENDING
