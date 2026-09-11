from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import uuid4

from sqlalchemy.orm import Session

from portmetrics.db.models import Activity, PriceSnapshot


def _buy(
    session: Session,
    *,
    qty: str,
    price: str,
    day: date,
    isin: str = "IE00BK5BQT80",
    symbol: str = "VWCE.DE",
    fee: str = "0",
) -> Activity:
    row = Activity(
        gf_activity_id=uuid4(),
        account_id="acc",
        isin=isin,
        symbol=symbol,
        type="BUY",
        quantity=Decimal(qty),
        unit_price=Decimal(price),
        fee=Decimal(fee),
        currency="EUR",
        trade_date=day,
    )
    session.add(row)
    session.flush()
    return row


def _price(
    session: Session,
    *,
    isin: str,
    day: date,
    close: str,
    symbol: str = "VWCE.DE",
) -> None:
    session.add(
        PriceSnapshot(
            isin=isin,
            symbol=symbol,
            price_date=day,
            close_price=Decimal(close),
            currency="EUR",
            source="test",
        )
    )


def _seed_portfolio(session: Session) -> None:
    _buy(session, qty="10", price="100", day=date(2026, 1, 2))
    _buy(session, qty="10", price="120", day=date(2026, 2, 1))
    _price(session, isin="IE00BK5BQT80", day=date(2026, 3, 1), close="150")
    session.commit()


def test_fifo_rebuild_lots_and_simulate(api_db) -> None:
    client, SessionLocal = api_db
    with SessionLocal() as session:
        _seed_portfolio(session)

    rebuild = client.post("/api/fifo/rebuild")
    assert rebuild.status_code == 200
    body = rebuild.json()
    assert body["lots_created"] == 2
    assert body["consumptions"] == 0
    assert body["activities_processed"] == 2

    lots = client.get("/api/lots")
    assert lots.status_code == 200
    lots_body = lots.json()
    assert lots_body["count"] == 2
    assert {lot["status"] for lot in lots_body["lots"]} == {"OPEN"}
    assert lots_body["lots"][0]["isin"] == "IE00BK5BQT80"
    assert "open_qty" in lots_body["lots"][0]
    assert "display_id" in lots_body["lots"][0]

    filtered = client.get("/api/lots", params={"isin": "IE00BK5BQT80"})
    assert filtered.json()["count"] == 2

    sim = client.post(
        "/api/simulate/sell",
        json={
            "isin": "IE00BK5BQT80",
            "quantity": "5",
            "unit_price": "160",
            "tax_rate": "0.25",
        },
    )
    assert sim.status_code == 200
    sim_body = sim.json()
    assert sim_body["isin"] == "IE00BK5BQT80"
    assert sim_body["quantity"] == "5"
    assert Decimal(sim_body["realized_gain"]) == Decimal("300")  # 5*(160-100)
    assert Decimal(sim_body["estimated_tax"]) == Decimal("75.00")
    assert len(sim_body["lots"]) == 1
    assert sim_body["lots"][0]["buy_activity_id"] is not None


def test_simulate_sell_invalid_payload_and_insufficient(api_db) -> None:
    client, SessionLocal = api_db
    with SessionLocal() as session:
        _buy(session, qty="2", price="100", day=date(2026, 1, 2))
        session.commit()

    assert client.post("/api/fifo/rebuild").status_code == 200

    bad = client.post("/api/simulate/sell", json={"quantity": "1"})
    assert bad.status_code == 400

    oversell = client.post(
        "/api/simulate/sell",
        json={"isin": "IE00BK5BQT80", "quantity": "10", "unit_price": "120"},
    )
    assert oversell.status_code == 409


def test_metrics_overview_periods_nav_positions(api_db) -> None:
    client, SessionLocal = api_db
    with SessionLocal() as session:
        _seed_portfolio(session)

    assert client.post("/api/fifo/rebuild").status_code == 200

    overview = client.get("/api/metrics/overview")
    assert overview.status_code == 200
    body = overview.json()
    assert "as_of" in body
    assert Decimal(body["nav"]) > 0
    assert Decimal(body["invested"]) == Decimal("2200")  # 10*100 + 10*120
    assert "periods" in body and len(body["periods"]) > 0
    assert "annual_returns" in body and len(body["annual_returns"]) > 0
    assert body["annual_returns"][0]["label"] == "ytd"
    assert "cagr" in body
    assert "mwr" in body
    assert "risk" in body
    assert "tax_allowance" in body
    assert "dividends" in body
    assert len(body["positions"]) == 1
    assert body["positions"][0]["isin"] == "IE00BK5BQT80"

    periods = client.get("/api/metrics/periods")
    assert periods.status_code == 200
    periods_body = periods.json()
    assert "periods" in periods_body
    assert "cagr" in periods_body
    assert periods_body["periods"][0]["label"]

    nav = client.get(
        "/api/metrics/nav",
        params={"start": "2026-01-02", "end": "2026-01-04"},
    )
    assert nav.status_code == 200
    nav_body = nav.json()
    assert nav_body["count"] == 3
    assert nav_body["points"][0]["date"] == "2026-01-02"
    assert "nav" in nav_body["points"][0]

    positions = client.get("/api/positions")
    assert positions.status_code == 200
    pos = positions.json()["positions"]
    assert len(pos) == 1
    assert Decimal(pos[0]["open_qty"]) == Decimal("20")
    assert pos[0]["simple_return"] is not None


def test_metrics_overview_empty(api_db) -> None:
    client, _SessionLocal = api_db
    response = client.get("/api/metrics/overview")
    assert response.status_code == 200
    body = response.json()
    assert body["nav"] == "0"
    assert body["invested"] == "0"
    assert body["positions"] == []
    assert body["dividends"]["total"] == "0"


def test_metrics_rebuild_writes_days(api_db) -> None:
    client, SessionLocal = api_db
    with SessionLocal() as session:
        _buy(session, qty="5", price="100", day=date(2026, 9, 1))
        _price(session, isin="IE00BK5BQT80", day=date(2026, 9, 1), close="110")
        session.commit()

    response = client.post("/api/metrics/rebuild")
    assert response.status_code == 200
    assert response.json()["days_written"] >= 1


def test_portfolio_settings_api_roundtrip(api_db) -> None:
    client, _SessionLocal = api_db

    get_resp = client.get("/api/settings/portfolio")
    assert get_resp.status_code == 200
    defaults = get_resp.json()
    assert "tax_allowance_eur" in defaults
    assert "asset_id_preference" in defaults

    put_resp = client.put(
        "/api/settings/portfolio",
        json={
            "tax_allowance_eur": "2500",
            "tax_warn_pct": "0.8",
            "risk_free_rate": "0.015",
            "asset_id_preference": "isin",
        },
    )
    assert put_resp.status_code == 200
    saved = put_resp.json()
    assert saved["tax_allowance_eur"] == "2500"
    assert saved["tax_warn_pct"] == "0.8"
    assert saved["risk_free_rate"] == "0.015"
    assert saved["asset_id_preference"] == "isin"
    assert client.get("/api/settings/portfolio").json()["tax_allowance_eur"] == "2500"

    bad = client.put("/api/settings/portfolio", json={"tax_warn_pct": "2"})
    assert bad.status_code == 400


def test_staging_confirm_runs_silent_mirror(api_db, monkeypatch) -> None:
    """Confirm imports to GF, then best-effort mirrors so Lots refresh without manual Sync."""
    from unittest.mock import MagicMock

    import portmetrics.main as main_module
    from portmetrics.config import Settings
    from portmetrics.ghostfolio.client import GhostfolioError

    client, _SessionLocal = api_db
    mirror_calls: list[int] = []
    relink_calls: list[int] = []

    monkeypatch.setattr(
        main_module,
        "settings",
        Settings(
            ghostfolio_url="http://ghostfolio.test",
            ghostfolio_access_token="tok",
        ),
    )
    monkeypatch.setattr(
        main_module,
        "_ghostfolio_client",
        lambda: MagicMock(),
    )
    monkeypatch.setattr(
        main_module,
        "confirm_staging",
        lambda *_a, **_k: {"id": 1, "status": "imported"},
    )

    def fake_mirror(_db, _client):
        mirror_calls.append(1)
        return MagicMock()

    def fake_relink(_db, staging_id: int):
        relink_calls.append(staging_id)
        return True

    monkeypatch.setattr(main_module, "sync_ghostfolio_mirror", fake_mirror)
    monkeypatch.setattr(main_module, "relink_staging_document", fake_relink)

    ok = client.post("/api/staging/1/confirm")
    assert ok.status_code == 200
    assert ok.json()["status"] == "imported"
    assert mirror_calls == [1]
    assert relink_calls == [1]

    def boom_mirror(_db, _client):
        mirror_calls.append(2)
        raise GhostfolioError("gf down")

    monkeypatch.setattr(main_module, "sync_ghostfolio_mirror", boom_mirror)
    still_ok = client.post("/api/staging/1/confirm")
    assert still_ok.status_code == 200
    assert still_ok.json()["status"] == "imported"
    assert mirror_calls == [1, 2]


def test_paperless_settings_api_roundtrip(api_db) -> None:
    client, _SessionLocal = api_db

    get_resp = client.get("/api/settings/paperless")
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert "roles" in body
    assert "field_map" in body
    assert "webhook_path" in body
    assert body["webhook_path"] == "/api/webhooks/paperless"

    put_resp = client.put(
        "/api/settings/paperless",
        json={
            "field_map": {"type": 1, "isin": 2, "quantity": 4, "unit_price": 5},
            "tag": "wertpapier",
            "ghostfolio_default_account_id": "acc-api",
            "ghostfolio_data_source": "MANUAL",
            "public_url": "https://paperless.example/",
        },
    )
    assert put_resp.status_code == 200
    saved = put_resp.json()
    assert saved["tag"] == "wertpapier"
    assert saved["field_map"]["isin"] == 2
    assert saved["ghostfolio_data_source"] == "MANUAL"
    assert saved["public_url"] == "https://paperless.example"
    assert saved["document_base_url"] == "https://paperless.example"

    bad = client.put(
        "/api/settings/paperless",
        json={"field_map": {"not_a_role": 99}},
    )
    assert bad.status_code == 400
