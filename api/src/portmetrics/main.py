from __future__ import annotations

from collections.abc import Generator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from portmetrics import __version__
from portmetrics.config import settings
from portmetrics.db.models import Activity, SyncState
from portmetrics.db.session import get_session_factory
from portmetrics.fifo.engine import FifoError
from portmetrics.fifo.service import list_open_lots, rebuild_lots, simulate_sell
from portmetrics.ghostfolio.client import GhostfolioClient, GhostfolioError
from portmetrics.logging_setup import configure_logging
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
from portmetrics.paperless.client import PaperlessClient, PaperlessError
from portmetrics.paperless.staging import (
    confirm_staging,
    list_staging,
    reject_staging,
    sync_paperless_documents,
)
from portmetrics.scheduler import start_scheduler, stop_scheduler
from portmetrics.sync.activities import GHOSTFOLIO_SOURCE, sync_ghostfolio_activities


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="PortMetrics", version=__version__, lifespan=lifespan)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

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
    return {"status": "ok", "env": settings.app_env, "version": __version__}


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return health()


@app.get("/api/version")
def api_version() -> dict[str, str]:
    return {
        "name": "PortMetrics",
        "version": __version__,
        "repository": "https://github.com/MrMoep/PortMetrics",
    }


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


def _paperless_client() -> PaperlessClient:
    if not settings.paperless_url or not settings.paperless_token:
        raise HTTPException(
            status_code=400,
            detail="PAPERLESS_URL and PAPERLESS_TOKEN must be configured",
        )
    return PaperlessClient(settings.paperless_url, settings.paperless_token)


def _ghostfolio_client() -> GhostfolioClient:
    if not settings.ghostfolio_url or not settings.ghostfolio_access_token:
        raise HTTPException(
            status_code=400,
            detail="GHOSTFOLIO_URL and GHOSTFOLIO_ACCESS_TOKEN must be configured",
        )
    return GhostfolioClient(settings.ghostfolio_url, settings.ghostfolio_access_token)


@app.get("/api/staging")
def staging_list(status: str | None = None, db: Session = Depends(get_db)) -> dict:
    items = list_staging(db, status=status)
    return {"count": len(items), "items": items}


@app.post("/api/staging/sync")
def staging_sync(db: Session = Depends(get_db)) -> dict:
    client = _paperless_client()
    try:
        result = sync_paperless_documents(db, client, tag=settings.paperless_tag)
    except PaperlessError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "scanned": result.scanned,
        "upserted": result.upserted,
        "skipped": result.skipped,
    }


@app.post("/api/staging/{staging_id}/confirm")
def staging_confirm(staging_id: int, db: Session = Depends(get_db)) -> dict:
    ghostfolio = _ghostfolio_client()
    paperless = None
    if settings.paperless_url and settings.paperless_token:
        paperless = PaperlessClient(settings.paperless_url, settings.paperless_token)
    try:
        return confirm_staging(db, staging_id, ghostfolio, paperless)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GhostfolioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/staging/{staging_id}/reject")
def staging_reject(staging_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        return reject_staging(db, staging_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


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
