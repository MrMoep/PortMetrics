from __future__ import annotations

import json
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from portmetrics.db.models import Activity, SyncState
from portmetrics.ghostfolio.client import GhostfolioActivity, GhostfolioClient, GhostfolioError
from portmetrics.sync.activities import (
    GHOSTFOLIO_SOURCE,
    sync_ghostfolio_activities,
    upsert_activities,
)


def test_ghostfolio_activity_from_api(sample_activity_payload: dict) -> None:
    activity = GhostfolioActivity.from_api(sample_activity_payload)
    assert activity.symbol == "VWCE.DE"
    assert activity.isin == "IE00BK5BQT80"
    assert activity.account_id == "acc-1"
    assert activity.type == "BUY"


def test_ghostfolio_activity_requires_symbol() -> None:
    with pytest.raises(GhostfolioError):
        GhostfolioActivity.from_api(
            {
                "id": str(UUID(int=1)),
                "accountId": "acc",
                "currency": "EUR",
                "date": "2024-01-01T00:00:00Z",
                "quantity": 1,
                "type": "BUY",
                "unitPrice": 1,
            }
        )


def test_ghostfolio_activity_allows_null_account_id(sample_activity_payload: dict) -> None:
    sample_activity_payload["accountId"] = None
    activity = GhostfolioActivity.from_api(sample_activity_payload)
    assert activity.account_id is None


def test_upsert_activities_with_null_account_id(
    db_session,
    sample_activity_payload: dict,
) -> None:
    sample_activity_payload["accountId"] = None
    activity = GhostfolioActivity.from_api(sample_activity_payload)
    assert upsert_activities(db_session, [activity]) == 1
    db_session.flush()

    row = db_session.scalars(select(Activity)).one()
    assert row.account_id is None
    assert row.symbol == "VWCE.DE"


def test_list_activities_uses_activities_endpoint(sample_activity_payload: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt-test"})
        if request.url.path.endswith("/activities"):
            assert request.headers["Authorization"] == "Bearer jwt-test"
            return httpx.Response(200, json={"activities": [sample_activity_payload]})
        raise AssertionError(request.url.path)

    transport = httpx.MockTransport(handler)
    client = GhostfolioClient("http://ghostfolio.test", "secret", transport=transport)
    activities = client.list_activities()
    assert len(activities) == 1
    assert activities[0].symbol == "VWCE.DE"


def test_list_activities_falls_back_to_order(sample_activity_payload: dict) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt-test"})
        if request.url.path.endswith("/activities"):
            return httpx.Response(404, json={"message": "not found"})
        if request.url.path.endswith("/order"):
            return httpx.Response(200, json={"activities": [sample_activity_payload]})
        raise AssertionError(request.url.path)

    transport = httpx.MockTransport(handler)
    client = GhostfolioClient("http://ghostfolio.test", "secret", transport=transport)
    activities = client.list_activities()
    assert len(activities) == 1


def test_upsert_activities_idempotent(db_session, sample_activity_payload: dict) -> None:
    activity = GhostfolioActivity.from_api(sample_activity_payload)
    assert upsert_activities(db_session, [activity]) == 1
    db_session.flush()

    # mutate price and upsert again
    sample_activity_payload["unitPrice"] = 110
    updated = GhostfolioActivity.from_api(sample_activity_payload)
    assert upsert_activities(db_session, [updated]) == 1
    db_session.flush()

    rows = db_session.scalars(select(Activity)).all()
    assert len(rows) == 1
    assert float(rows[0].unit_price) == 110.0
    assert rows[0].gf_activity_id == activity.id


def test_sync_ghostfolio_activities_updates_sync_state(
    db_session,
    sample_activity_payload: dict,
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt-test"})
        if request.url.path.endswith("/activities"):
            return httpx.Response(200, json={"activities": [sample_activity_payload]})
        raise AssertionError(request.url.path)

    client = GhostfolioClient(
        "http://ghostfolio.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = sync_ghostfolio_activities(db_session, client)
    db_session.flush()

    assert result.fetched == 1
    assert result.upserted == 1
    state = db_session.scalar(select(SyncState).where(SyncState.source == GHOSTFOLIO_SOURCE))
    assert state is not None
    assert state.checksum == result.checksum
    assert state.meta == {"fetched": 1}


def test_sync_skips_unsupported_activity_types(
    db_session,
    sample_activity_payload: dict,
) -> None:
    liability = {
        **sample_activity_payload,
        "id": str(UUID(int=2)),
        "type": "LIABILITY",
        "accountId": None,
        "SymbolProfile": {
            "symbol": "RENT",
            "isin": None,
            "dataSource": "MANUAL",
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt-test"})
        if request.url.path.endswith("/activities"):
            return httpx.Response(
                200,
                json={"activities": [sample_activity_payload, liability]},
            )
        raise AssertionError(request.url.path)

    client = GhostfolioClient(
        "http://ghostfolio.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = sync_ghostfolio_activities(db_session, client)
    db_session.flush()

    assert result.fetched == 2
    assert result.upserted == 1
    rows = db_session.scalars(select(Activity)).all()
    assert len(rows) == 1
    assert rows[0].type == "BUY"


def test_auth_failure_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = GhostfolioClient(
        "http://ghostfolio.test",
        "bad",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GhostfolioError):
        client.authenticate()


def test_import_activities() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt"})
        if request.url.path.endswith("/import"):
            assert request.headers["Authorization"] == "Bearer jwt"
            return httpx.Response(
                201,
                json={"activities": [{"id": "11111111-1111-1111-1111-111111111111"}]},
            )
        raise AssertionError(request.url.path)

    client = GhostfolioClient(
        "http://ghostfolio.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = client.import_activities(
        [
            {
                "currency": "EUR",
                "dataSource": "YAHOO",
                "date": "2024-01-01T00:00:00.000Z",
                "fee": 0,
                "quantity": 1,
                "symbol": "VWCE.DE",
                "type": "BUY",
                "unitPrice": 100,
            }
        ]
    )
    assert result["activities"][0]["id"].startswith("11111111")


def test_unused_json_roundtrip(sample_activity_payload: dict) -> None:
    # sanity: payload remains JSON-serializable for fixtures
    assert json.loads(json.dumps(sample_activity_payload))["type"] == "BUY"
