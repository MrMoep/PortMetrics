from __future__ import annotations

from collections.abc import Generator
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from portmetrics.config import settings
from portmetrics.db.models import Activity, SyncState
from portmetrics.db.session import get_session_factory
from portmetrics.fifo.engine import FifoError
from portmetrics.fifo.service import list_open_lots, rebuild_lots, simulate_sell
from portmetrics.ghostfolio.client import GhostfolioClient, GhostfolioError
from portmetrics.metrics.periods import (
    cagr,
    compute_standard_periods,
    load_activities,
    nav_series,
    overview_payload,
    position_simple_return,
    price_map,
    rebuild_metrics_daily,
)
from portmetrics.sync.activities import GHOSTFOLIO_SOURCE, sync_ghostfolio_activities

app = FastAPI(title="PortMetrics", version="0.1.0")

WEB_DIST = Path(settings.web_dist_dir)


def get_db() -> Generator[Session]:
    factory = get_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "env": settings.app_env}


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return health()


@app.get("/api/sync/status")
def sync_status(db: Session = Depends(get_db)) -> dict:
    state = db.scalar(select(SyncState).where(SyncState.source == GHOSTFOLIO_SOURCE))
    activity_count = db.scalar(select(func.count()).select_from(Activity)) or 0
    return {
        "source": GHOSTFOLIO_SOURCE,
        "activity_count": activity_count,
        "last_sync_at": state.last_sync_at.isoformat() if state and state.last_sync_at else None,
        "checksum": state.checksum if state else None,
        "meta": state.meta if state else None,
    }


@app.post("/api/sync/ghostfolio")
def sync_ghostfolio(db: Session = Depends(get_db)) -> dict:
    if not settings.ghostfolio_url or not settings.ghostfolio_access_token:
        raise HTTPException(
            status_code=400,
            detail="GHOSTFOLIO_URL and GHOSTFOLIO_ACCESS_TOKEN must be configured",
        )
    client = GhostfolioClient(settings.ghostfolio_url, settings.ghostfolio_access_token)
    try:
        result = sync_ghostfolio_activities(db, client)
        fifo = rebuild_lots(db)
        metrics_days = rebuild_metrics_daily(db)
    except GhostfolioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except FifoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "fetched": result.fetched,
        "upserted": result.upserted,
        "checksum": result.checksum,
        "lots_created": fifo.lots_created,
        "consumptions": fifo.consumptions,
        "metrics_days": metrics_days,
    }


@app.post("/api/fifo/rebuild")
def fifo_rebuild(db: Session = Depends(get_db)) -> dict:
    try:
        result = rebuild_lots(db)
    except FifoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "lots_created": result.lots_created,
        "consumptions": result.consumptions,
        "activities_processed": result.activities_processed,
    }


@app.get("/api/lots")
def get_lots(
    isin: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    lots = list_open_lots(db, asset_key=isin)
    return {"count": len(lots), "lots": lots}


@app.post("/api/simulate/sell")
def post_simulate_sell(payload: dict, db: Session = Depends(get_db)) -> dict:
    try:
        isin = payload["isin"]
        quantity = Decimal(str(payload["quantity"]))
        unit_price = (
            Decimal(str(payload["unit_price"])) if payload.get("unit_price") is not None else None
        )
        fee = Decimal(str(payload.get("fee", "0")))
        tax_rate = Decimal(str(payload.get("tax_rate", settings.default_tax_rate)))
    except (KeyError, Exception) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid payload: {exc}") from exc
    try:
        return simulate_sell(
            db,
            asset_key=isin,
            quantity=quantity,
            unit_price=unit_price,
            fee=fee,
            tax_rate=tax_rate,
        )
    except FifoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.get("/api/metrics/overview")
def metrics_overview(db: Session = Depends(get_db)) -> dict:
    return overview_payload(db)


@app.get("/api/metrics/periods")
def metrics_periods(db: Session = Depends(get_db)) -> dict:
    activities = load_activities(db)
    prices = price_map(db)
    periods = compute_standard_periods(activities, prices)
    return {
        "periods": [
            {
                "label": p.label,
                "start_date": p.start_date.isoformat(),
                "end_date": p.end_date.isoformat(),
                "start_nav": str(p.start_nav),
                "end_nav": str(p.end_nav),
                "contributions": str(p.contributions),
                "withdrawals": str(p.withdrawals),
                "period_return": str(p.period_return) if p.period_return is not None else None,
            }
            for p in periods
        ],
        "cagr": cagr(activities, prices),
    }


@app.get("/api/metrics/nav")
def metrics_nav(
    start: str | None = None,
    end: str | None = None,
    db: Session = Depends(get_db),
) -> dict:
    activities = load_activities(db)
    prices = price_map(db)
    start_d = date.fromisoformat(start) if start else None
    end_d = date.fromisoformat(end) if end else None
    series = nav_series(activities, prices, start=start_d, end=end_d)
    return {"count": len(series), "points": series}


@app.get("/api/positions")
def positions(isin: str | None = None, db: Session = Depends(get_db)) -> dict:
    return {"positions": position_simple_return(db, asset_key=isin)}


@app.post("/api/metrics/rebuild")
def metrics_rebuild(db: Session = Depends(get_db)) -> dict:
    count = rebuild_metrics_daily(db)
    return {"days_written": count}


if WEB_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/")
    def spa_index() -> FileResponse:
        return FileResponse(WEB_DIST / "index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        candidate = WEB_DIST / full_path
        if candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
