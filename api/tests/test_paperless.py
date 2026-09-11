from __future__ import annotations

import json
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
    SYNC_MODE_FULL,
    build_staging_payload,
    confirm_staging,
    list_staging,
    parse_monetary,
    reject_staging,
    sync_paperless_documents,
)

FIELD_MAP = {
    "wp_typ": 1,
    "isin": 2,
    "wkn": 3,
    "stueckzahl": 4,
    "kurs": 5,
    "gebuehr": 6,
}

ROLE_MAP = {
    "type": 1,
    "isin": 2,
    "wkn": 3,
    "quantity": 4,
    "unit_price": 5,
    "fee": 6,
}


def _doc(doc_id: int = 42, **overrides) -> dict:
    base = {
        "id": doc_id,
        "title": "Kauf VWCE",
        "created": "2024-06-01T12:00:00.000Z",
        "custom_fields": [
            {"field": 1, "value": "BUY"},
            {"field": 2, "value": "IE00BK5BQT80"},
            {"field": 3, "value": "A1JX52"},
            {"field": 4, "value": "10"},
            {"field": 5, "value": "EUR100.50"},
            {"field": 6, "value": "EUR1.50"},
        ],
    }
    base.update(overrides)
    return base


def _fields_handler(request: httpx.Request) -> httpx.Response | None:
    if request.url.path.endswith("/custom_fields/"):
        results = []
        for name, fid in FIELD_MAP.items():
            item: dict = {"id": fid, "name": name, "data_type": "string"}
            if name == "wp_typ":
                item["data_type"] = "select"
                item["extra_data"] = {
                    "select_options": [
                        {"id": "SXXGAXZIVEH4OXSZ", "label": "BUY"},
                        {"id": "J6QQIILJAHMITXKE", "label": "SELL"},
                        {"id": "7AMU4HWVPJEVCFUK", "label": "DIVIDEND"},
                    ]
                }
            results.append(item)
        return httpx.Response(200, json={"results": results})
    return None


def test_extract_custom_fields() -> None:
    fields = extract_custom_fields(_doc(), FIELD_MAP)
    assert fields["isin"] == "IE00BK5BQT80"
    assert fields["stueckzahl"] == "10"


def test_extract_fields_by_roles() -> None:
    fields = extract_fields_by_roles(_doc(), ROLE_MAP)
    assert fields["isin"] == "IE00BK5BQT80"
    assert fields["quantity"] == "10"
    assert fields["wkn"] == "A1JX52"


def test_select_option_id_resolves_to_label() -> None:
    from portmetrics.paperless.mapping import (
        resolve_select_value,
        select_option_map,
        select_option_maps_by_field_id,
    )

    field = {
        "id": 17,
        "name": "Typ",
        "data_type": "select",
        "extra_data": {
            "select_options": [
                {"id": "SXXGAXZIVEH4OXSZ", "label": "BUY"},
                {"id": "J6QQIILJAHMITXKE", "label": "SELL"},
            ]
        },
    }
    option_map = select_option_map(field)
    assert option_map["SXXGAXZIVEH4OXSZ"] == "BUY"
    assert resolve_select_value("SXXGAXZIVEH4OXSZ", option_map) == "BUY"
    assert resolve_select_value({"id": "J6QQIILJAHMITXKE"}, option_map) == "SELL"

    maps = select_option_maps_by_field_id([field])
    doc = _doc(
        99,
        custom_fields=[
            {"field": 17, "value": "SXXGAXZIVEH4OXSZ"},
            {"field": 2, "value": "IE00BK5BQT80"},
            {"field": 4, "value": "1"},
            {"field": 5, "value": "EUR10"},
        ],
    )
    roles = extract_fields_by_roles(doc, {"type": 17, "isin": 2, "quantity": 4, "unit_price": 5}, select_maps=maps)
    assert roles["type"] == "BUY"
    payload = build_staging_payload(doc, roles)
    assert payload["wp_typ"] == "BUY"


def test_parse_monetary() -> None:
    assert parse_monetary("EUR100.50") == (__import__("decimal").Decimal("100.50"), "EUR")
    assert parse_monetary("CHF42.00")[1] == "CHF"
    assert parse_monetary("12,5")[0] == __import__("decimal").Decimal("12.5")


def test_build_staging_payload_legacy_names() -> None:
    payload = build_staging_payload(_doc(), extract_custom_fields(_doc(), FIELD_MAP))
    assert payload["symbol"] == "IE00BK5BQT80"
    assert payload["wp_typ"] == "BUY"
    assert payload["trade_date"] == "2024-06-01"
    assert payload["quantity"] == "10"
    assert payload["currency"] == "EUR"
    assert payload["wkn"] == "A1JX52"
    assert payload["importable"] is True


def test_build_staging_payload_roles() -> None:
    payload = build_staging_payload(_doc(), extract_fields_by_roles(_doc(), ROLE_MAP))
    assert payload["symbol"] == "IE00BK5BQT80"
    assert payload["quantity"] == "10"
    assert payload["unit_price"] == "100.50"


def test_build_staging_payload_other_not_importable() -> None:
    doc = _doc(
        7,
        custom_fields=[
            {"field": 1, "value": "OTHER"},
            {"field": 2, "value": "IE00BK5BQT80"},
            {"field": 5, "value": "EUR0.00"},
        ],
    )
    payload = build_staging_payload(doc, extract_fields_by_roles(doc, ROLE_MAP))
    assert payload["wp_typ"] == "OTHER"
    assert payload["importable"] is False
    assert payload["quantity"] == "1"


def test_build_staging_payload_fee_defaults_quantity() -> None:
    doc = _doc(
        8,
        custom_fields=[
            {"field": 1, "value": "FEE"},
            {"field": 2, "value": "IE00BK5BQT80"},
            {"field": 5, "value": "EUR9.90"},
        ],
    )
    payload = build_staging_payload(doc, extract_fields_by_roles(doc, ROLE_MAP))
    assert payload["wp_typ"] == "FEE"
    assert payload["quantity"] == "1"
    assert payload["unit_price"] == "9.90"
    assert payload["currency"] == "EUR"


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


def test_list_tags_and_document_types() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tags/"):
            return httpx.Response(200, json={"results": [{"id": 1, "name": "wp"}]})
        if request.url.path.endswith("/document_types/"):
            return httpx.Response(200, json=[{"id": 2, "name": "Trade"}])
        raise AssertionError(request.url.path)

    client = PaperlessClient(
        "http://paperless.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    assert client.list_tags()[0]["id"] == 1
    assert client.list_document_types()[0]["name"] == "Trade"


def test_list_documents_paginates_and_filters(db_session) -> None:
    pages = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tags/"):
            return httpx.Response(200, json={"results": [{"id": 9, "name": "wertpapier"}]})
        if request.url.path.endswith("/document_types/"):
            return httpx.Response(200, json={"results": [{"id": 3, "name": "Abrechnung"}]})
        if request.url.path.endswith("/documents/"):
            params = request.url.params
            pages["n"] += 1
            if pages["n"] == 1:
                assert params.get("document_type__id") == "3"
                assert "9" in params.get_list("tags__id")
                return httpx.Response(
                    200,
                    json={
                        "results": [_doc(1), _doc(2)],
                        "next": (
                            "http://paperless.test/api/documents/"
                            "?page=2&page_size=100&ordering=-created"
                            "&tags__id=9&document_type__id=3"
                        ),
                    },
                )
            assert params.get("page") == "2"
            assert params.get("document_type__id") == "3"
            return httpx.Response(200, json={"results": [_doc(3)], "next": None})
        raise AssertionError(request.url.path)

    client = PaperlessClient(
        "http://paperless.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    partial = client.list_documents(tag_ids=[9], document_type_ids=[3], paginate=False)
    assert len(partial) == 2
    assert pages["n"] == 1

    pages["n"] = 0
    events: list[dict] = []
    full = client.list_documents(
        tag_ids=[9],
        document_type_ids=[3],
        paginate=True,
        on_progress=events.append,
    )
    assert {d["id"] for d in full} == {1, 2, 3}
    assert pages["n"] == 2
    assert any(e.get("event") == "page" for e in events)

    save_paperless_settings(
        db_session,
        {
            "sync_tags": [{"id": 9, "name": "wertpapier"}],
            "sync_document_types": [{"id": 3, "name": "Abrechnung"}],
        },
    )
    cfg = get_paperless_settings(db_session)
    assert cfg["sync_tags"][0]["id"] == 9
    from portmetrics.paperless.mapping import has_sync_filters, sync_filter_ids

    assert has_sync_filters(cfg) is True
    assert sync_filter_ids(cfg) == ([9], [3])


def test_sync_full_mode_paginates_with_progress(db_session) -> None:
    save_paperless_settings(
        db_session,
        {
            "field_map": ROLE_MAP,
            "sync_tags": [{"id": 9, "name": "wertpapier"}],
        },
    )
    pages = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/custom_fields/"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"id": 1, "name": "TradeType"},
                        {"id": 2, "name": "ISIN"},
                        {"id": 3, "name": "WKN"},
                        {"id": 4, "name": "Qty"},
                        {"id": 5, "name": "Price"},
                        {"id": 6, "name": "Fee"},
                    ]
                },
            )
        if request.url.path.endswith("/documents/"):
            pages["n"] += 1
            if pages["n"] == 1:
                return httpx.Response(
                    200,
                    json={
                        "results": [_doc(101), _doc(102)],
                        "next": "http://paperless.test/api/documents/?page=2",
                    },
                )
            return httpx.Response(200, json={"results": [_doc(103)], "next": None})
        raise AssertionError(request.url.path)

    client = PaperlessClient(
        "http://paperless.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    events: list[dict] = []
    result = sync_paperless_documents(
        db_session,
        client,
        mode=SYNC_MODE_FULL,
        on_progress=events.append,
    )
    assert result.mode == "full"
    assert result.scanned == 3
    assert result.upserted == 3
    assert result.filters_active is True
    assert result.skip_reasons == {}
    assert pages["n"] == 2
    assert any(e.get("event") == "page" for e in events)
    assert any(e.get("event") == "ingest" for e in events)
    rows = db_session.scalars(select(StagingImport)).all()
    assert {row.paperless_doc_id for row in rows} == {101, 102, 103}


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
                        {"id": 3, "name": "WKN"},
                        {"id": 4, "name": "Qty"},
                        {"id": 5, "name": "Price"},
                        {"id": 6, "name": "Fee"},
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
    assert row.payload["symbol"] == "IE00BK5BQT80"
    assert row.payload["currency"] == "EUR"


def test_save_and_resolve_mapping(db_session) -> None:
    saved = save_paperless_settings(
        db_session,
        {
            "field_map": {"type": 1, "isin": 2, "quantity": 4, "unit_price": 5},
            "tag": "wertpapier",
            "ghostfolio_default_account_id": "acc-9",
            "ghostfolio_data_source": "MANUAL",
        },
    )
    assert saved["tag"] == "wertpapier"
    assert saved["field_map"]["isin"] == 2
    assert get_paperless_settings(db_session)["ghostfolio_data_source"] == "MANUAL"

    saved_url = save_paperless_settings(
        db_session,
        {
            "field_map": saved["field_map"],
            "public_url": "https://paperless.example.com/",
        },
    )
    assert saved_url["public_url"] == "https://paperless.example.com"

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
    assert "symbol" not in resolved
    assert "currency" not in resolved


def test_save_rejects_removed_roles(db_session) -> None:
    with pytest.raises(ValueError, match="Unknown field role"):
        save_paperless_settings(db_session, {"field_map": {"symbol": 3}})


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

    from portmetrics.assets.identifiers import upsert_mapping

    upsert_mapping(
        db_session,
        isin="IE00BK5BQT80",
        wkn="A1JX52",
        preferred_symbol="VWCE.DE",
    )

    def gf_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt"})
        if request.url.path.endswith("/import"):
            body = json.loads(request.content.decode())
            activity = body["activities"][0]
            assert activity["symbol"] == "VWCE.DE"
            assert "IE00BK5BQT80" in activity["comment"]
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
    assert confirmed["mapping"]["preferred_symbol"] == "VWCE.DE"
    assert confirmed["can_confirm"] is False  # already imported
    links = db_session.scalars(select(DocumentLink)).all()
    assert len(links) == 1
    assert links[0].paperless_doc_id == 99
    from portmetrics.db.models import AssetIdentifier

    ident = db_session.get(AssetIdentifier, "IE00BK5BQT80")
    assert ident is not None
    assert ident.wkn == "A1JX52"
    assert ident.preferred_symbol == "VWCE.DE"


def test_confirm_blocked_without_preferred_symbol(db_session) -> None:
    row = StagingImport(
        paperless_doc_id=88,
        payload=build_staging_payload(_doc(88), extract_custom_fields(_doc(88), FIELD_MAP)),
        status=STATUS_PENDING,
    )
    db_session.add(row)
    db_session.flush()
    ghostfolio = GhostfolioClient(
        "http://ghostfolio.test",
        "tok",
        transport=httpx.MockTransport(lambda _r: httpx.Response(500)),
    )
    with pytest.raises(ValueError, match="preferred Symbol"):
        confirm_staging(db_session, row.id, ghostfolio)


def test_confirm_other_rejected(db_session) -> None:
    doc = _doc(
        11,
        custom_fields=[
            {"field": 1, "value": "OTHER"},
            {"field": 2, "value": "IE00BK5BQT80"},
            {"field": 5, "value": "EUR1.00"},
        ],
    )
    row = StagingImport(
        paperless_doc_id=11,
        payload=build_staging_payload(doc, extract_fields_by_roles(doc, ROLE_MAP)),
        status=STATUS_PENDING,
    )
    db_session.add(row)
    db_session.flush()
    ghostfolio = GhostfolioClient(
        "http://ghostfolio.test",
        "tok",
        transport=httpx.MockTransport(lambda _r: httpx.Response(500)),
    )
    with pytest.raises(ValueError, match="Cannot import type OTHER"):
        confirm_staging(db_session, row.id, ghostfolio)


def test_confirm_missing_raises(db_session) -> None:
    bad = httpx.MockTransport(lambda _r: httpx.Response(500))
    ghostfolio = GhostfolioClient("http://ghostfolio.test", "tok", transport=bad)
    with pytest.raises(LookupError):
        confirm_staging(db_session, 99999, ghostfolio)


def test_relink_staging_document_after_sync(db_session) -> None:
    from datetime import date
    from decimal import Decimal

    from portmetrics.db.models import Activity, Lot
    from portmetrics.paperless.staging import relink_staging_document

    gf_id = uuid4()
    row = StagingImport(
        paperless_doc_id=77,
        payload=build_staging_payload(_doc(77), extract_custom_fields(_doc(77), FIELD_MAP)),
        status=STATUS_IMPORTED,
        gf_activity_id=gf_id,
    )
    db_session.add(row)
    db_session.add(
        DocumentLink(
            paperless_doc_id=77,
            activity_id=None,
            lot_id=None,
            link_type="source",
        )
    )
    db_session.flush()

    assert relink_staging_document(db_session, row.id) is False

    activity = Activity(
        gf_activity_id=gf_id,
        account_id="acc",
        isin="IE00BK5BQT80",
        symbol="VWCE.DE",
        type="BUY",
        quantity=Decimal("10"),
        unit_price=Decimal("100"),
        fee=Decimal("1"),
        currency="EUR",
        trade_date=date(2024, 6, 1),
    )
    db_session.add(activity)
    db_session.flush()
    lot = Lot(
        activity_id=activity.id,
        isin="IE00BK5BQT80",
        open_qty=Decimal("10"),
        original_qty=Decimal("10"),
        cost_basis=Decimal("1001"),
        open_date=date(2024, 6, 1),
        status="OPEN",
    )
    db_session.add(lot)
    db_session.flush()

    assert relink_staging_document(db_session, row.id) is True
    link = db_session.scalar(select(DocumentLink).where(DocumentLink.paperless_doc_id == 77))
    assert link is not None
    assert link.activity_id == activity.id
    assert link.lot_id == lot.id


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


def test_reingest_skips_imported_and_rejected(db_session) -> None:
    from portmetrics.paperless.staging import ingest_paperless_document

    imported = StagingImport(
        paperless_doc_id=10,
        payload=build_staging_payload(_doc(10), extract_custom_fields(_doc(10), FIELD_MAP)),
        status=STATUS_IMPORTED,
    )
    rejected = StagingImport(
        paperless_doc_id=11,
        payload=build_staging_payload(_doc(11), extract_custom_fields(_doc(11), FIELD_MAP)),
        status=STATUS_REJECTED,
    )
    pending = StagingImport(
        paperless_doc_id=12,
        payload=build_staging_payload(_doc(12), extract_custom_fields(_doc(12), FIELD_MAP)),
        status=STATUS_PENDING,
    )
    db_session.add_all([imported, rejected, pending])
    db_session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        handled = _fields_handler(request)
        if handled:
            return handled
        for doc_id in (10, 11, 12):
            if request.url.path.endswith(f"/documents/{doc_id}/"):
                return httpx.Response(200, json=_doc(doc_id))
        raise AssertionError(request.url.path)

    client = PaperlessClient(
        "http://paperless.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )

    skip_imported = ingest_paperless_document(db_session, client, 10)
    skip_rejected = ingest_paperless_document(db_session, client, 11)
    upsert_pending = ingest_paperless_document(db_session, client, 12)

    assert skip_imported.action == "skipped"
    assert "imported" in (skip_imported.reason or "")
    assert skip_rejected.action == "skipped"
    assert "rejected" in (skip_rejected.reason or "")
    assert upsert_pending.action == "upserted"

    db_session.refresh(imported)
    db_session.refresh(rejected)
    assert imported.status == STATUS_IMPORTED
    assert rejected.status == STATUS_REJECTED

    all_items = list_staging(db_session, status="all")
    open_items = list_staging(db_session)
    pending_items = list_staging(db_session, status=STATUS_PENDING)
    assert {item["paperless_doc_id"] for item in all_items} == {10, 11, 12}
    assert {item["paperless_doc_id"] for item in open_items} == {12}
    assert {item["paperless_doc_id"] for item in pending_items} == {12}


def test_sync_aggregates_skip_reasons(db_session) -> None:
    imported = StagingImport(
        paperless_doc_id=10,
        payload=build_staging_payload(_doc(10), extract_custom_fields(_doc(10), FIELD_MAP)),
        status=STATUS_IMPORTED,
    )
    db_session.add(imported)
    db_session.flush()

    def handler(request: httpx.Request) -> httpx.Response:
        handled = _fields_handler(request)
        if handled:
            return handled
        if request.url.path.endswith("/documents/"):
            bare = _doc(20, custom_fields=[{"field": 1, "value": "BUY"}])
            select_typ = _doc(
                21,
                custom_fields=[
                    {"field": 1, "value": "SXXGAXZIVEH4OXSZ"},
                    {"field": 2, "value": "IE00BK5BQT80"},
                    {"field": 3, "value": "A1JX52"},
                    {"field": 4, "value": "10"},
                    {"field": 5, "value": "EUR100.50"},
                    {"field": 6, "value": "EUR1.50"},
                ],
            )
            return httpx.Response(200, json={"results": [_doc(10), bare, select_typ]})
        raise AssertionError(request.url.path)

    client = PaperlessClient(
        "http://paperless.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = sync_paperless_documents(db_session, client)
    assert result.scanned == 3
    assert result.upserted == 1
    assert result.skipped == 2
    assert result.skip_reasons["already imported locally"] == 1
    assert result.skip_reasons["missing isin"] == 1
    row = db_session.scalar(select(StagingImport).where(StagingImport.paperless_doc_id == 21))
    assert row is not None
    assert row.payload["wp_typ"] == "BUY"
