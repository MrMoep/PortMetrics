from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

import httpx
import pytest
from sqlalchemy import select

from portmetrics.db.models import PriceSnapshot, SyncState
from portmetrics.ghostfolio.client import GhostfolioActivity, GhostfolioClient, GhostfolioError
from portmetrics.sync.prices import (
    GHOSTFOLIO_PRICES_SOURCE,
    discover_assets,
    sync_ghostfolio_prices,
)


def test_discover_assets_prefers_mapped_symbol(sample_activity_payload: dict) -> None:
    a = GhostfolioActivity.from_api(sample_activity_payload)
    other = GhostfolioActivity.from_api(
        {
            **sample_activity_payload,
            "id": str(UUID(int=3)),
            "SymbolProfile": {
                "symbol": "VWRD.L",
                "isin": "IE00BK5BQT80",
                "dataSource": "YAHOO",
            },
        }
    )
    assets = discover_assets(
        [a, other],
        preferred_by_isin={"IE00BK5BQT80": "VGWL.DE"},
    )
    assert len(assets) == 1
    assert assets[0].symbol == "VGWL.DE"
    assert assets[0].asset_key == "IE00BK5BQT80"


def test_discover_assets_uses_isin_or_symbol(sample_activity_payload: dict) -> None:
    with_isin = GhostfolioActivity.from_api(sample_activity_payload)
    no_isin_payload = {
        **sample_activity_payload,
        "id": str(UUID(int=2)),
        "SymbolProfile": {
            "symbol": "VGWL.DE",
            "isin": None,
            "dataSource": "YAHOO",
        },
    }
    no_isin = GhostfolioActivity.from_api(no_isin_payload)
    assets = discover_assets([with_isin, no_isin])
    assert len(assets) == 2
    by_key = {a.asset_key: a for a in assets}
    assert by_key["IE00BK5BQT80"].symbol == "VWCE.DE"
    assert by_key["VGWL.DE"].symbol == "VGWL.DE"
    assert by_key["VGWL.DE"].data_source == "YAHOO"


def test_get_symbol_parses_historical() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt"})
        if "/symbol/YAHOO/VWCE.DE" in request.url.path:
            assert request.url.params.get("includeHistoricalData") == "30"
            return httpx.Response(
                200,
                json={
                    "currency": "EUR",
                    "dataSource": "YAHOO",
                    "symbol": "VWCE.DE",
                    "marketPrice": 110.5,
                    "historicalData": [
                        {"date": "2024-01-02T00:00:00.000Z", "value": 100.25},
                        {"date": "2024-01-03T00:00:00.000Z", "value": 101.0},
                    ],
                },
            )
        raise AssertionError(request.url.path)

    client = GhostfolioClient(
        "http://ghostfolio.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    data = client.get_symbol("YAHOO", "VWCE.DE", include_historical_data=30)
    assert data.market_price == Decimal("110.5")
    assert len(data.historical) == 2
    assert data.historical[0] == (date(2024, 1, 2), Decimal("100.25"))


def test_get_symbol_failure_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt"})
        return httpx.Response(500, text="boom")

    client = GhostfolioClient(
        "http://ghostfolio.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    with pytest.raises(GhostfolioError):
        client.get_symbol("YAHOO", "MISSING", include_historical_data=10)


def test_sync_ghostfolio_prices_upserts(
    db_session,
    sample_activity_payload: dict,
) -> None:
    activity = GhostfolioActivity.from_api(sample_activity_payload)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt"})
        if "/symbol/YAHOO/VWCE.DE" in request.url.path:
            return httpx.Response(
                200,
                json={
                    "currency": "EUR",
                    "dataSource": "YAHOO",
                    "symbol": "VWCE.DE",
                    "marketPrice": 105,
                    "historicalData": [
                        {"date": "2024-01-02T00:00:00.000Z", "value": 100},
                        {"date": "2024-01-03T00:00:00.000Z", "value": 102},
                    ],
                },
            )
        raise AssertionError(request.url.path)

    client = GhostfolioClient(
        "http://ghostfolio.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = sync_ghostfolio_prices(
        db_session,
        client,
        history_days=30,
        activities=[activity],
        as_of=date(2024, 1, 5),
    )
    db_session.flush()

    assert result.assets == 1
    assert result.upserted == 3  # 2 historical + today marketPrice
    assert result.skipped == 0

    rows = list(db_session.scalars(select(PriceSnapshot).order_by(PriceSnapshot.price_date)).all())
    assert len(rows) == 3
    assert rows[0].isin == "IE00BK5BQT80"
    assert rows[0].symbol == "VWCE.DE"
    assert float(rows[0].close_price) == 100.0
    assert rows[-1].price_date == date(2024, 1, 5)
    assert float(rows[-1].close_price) == 105.0

    state = db_session.scalar(select(SyncState).where(SyncState.source == GHOSTFOLIO_PRICES_SOURCE))
    assert state is not None
    assert state.meta == {"assets": 1, "upserted": 3, "skipped": 0}

    # Idempotent second sync
    result2 = sync_ghostfolio_prices(
        db_session,
        client,
        history_days=30,
        activities=[activity],
        as_of=date(2024, 1, 5),
    )
    db_session.flush()
    assert result2.upserted == 3
    assert len(db_session.scalars(select(PriceSnapshot)).all()) == 3


def test_sync_skips_failed_symbol(
    db_session,
    sample_activity_payload: dict,
) -> None:
    activity = GhostfolioActivity.from_api(sample_activity_payload)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/auth/anonymous"):
            return httpx.Response(200, json={"authToken": "jwt"})
        return httpx.Response(404, text="missing")

    client = GhostfolioClient(
        "http://ghostfolio.test",
        "secret",
        transport=httpx.MockTransport(handler),
    )
    result = sync_ghostfolio_prices(
        db_session,
        client,
        history_days=10,
        activities=[activity],
    )
    assert result.assets == 1
    assert result.upserted == 0
    assert result.skipped == 1


def test_activity_parses_data_source(sample_activity_payload: dict) -> None:
    activity = GhostfolioActivity.from_api(sample_activity_payload)
    assert activity.data_source == "YAHOO"
