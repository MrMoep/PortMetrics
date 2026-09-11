from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Thread

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from portmetrics import __version__
from portmetrics.build_info import built_at, display_version, git_sha, image_channel
from portmetrics.config import settings, webhook_secret_matches
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
from portmetrics.paperless.mapping import (
    FIELD_ROLE_META,
    FIELD_ROLES,
    get_paperless_settings,
    has_sync_filters,
    save_paperless_settings,
)
from portmetrics.paperless.match import match_staging_to_activities
from portmetrics.paperless.staging import (
    SYNC_MODE_FULL,
    SYNC_MODE_PARTIAL,
    confirm_staging,
    ingest_paperless_document,
    list_staging,
    parse_paperless_document_id,
    reject_staging,
    sync_paperless_documents,
)
from portmetrics.scheduler import start_scheduler, stop_scheduler
from portmetrics.settings.portfolio import get_portfolio_settings, save_portfolio_settings
from portmetrics.sync.activities import GHOSTFOLIO_SOURCE, sync_ghostfolio_activities
from portmetrics.sync.prices import (
    GHOSTFOLIO_PRICES_SOURCE,
    price_snapshot_count,
    sync_ghostfolio_prices,
)


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
    return {"status": "ok", "env": settings.app_env, "version": display_version()}


@app.get("/api/health")
def api_health() -> dict[str, str]:
    return health()


@app.get("/api/version")
def api_version() -> dict[str, str]:
    payload = {
        "name": "PortMetrics",
        "version": display_version(),
        "repository": "https://github.com/MrMoep/PortMetrics",
    }
    channel = image_channel()
    if channel:
        payload["channel"] = channel
    stamp = built_at()
    if stamp:
        payload["built_at"] = stamp
    sha = git_sha()
    if sha:
        payload["git_sha"] = sha
    # Keep package semver available for tooling; UI uses `version`.
    payload["package_version"] = __version__
    return payload


@app.get("/api/sync/status")
def sync_status(db: Session = Depends(get_db)) -> dict:
    state = db.scalar(select(SyncState).where(SyncState.source == GHOSTFOLIO_SOURCE))
    price_state = db.scalar(select(SyncState).where(SyncState.source == GHOSTFOLIO_PRICES_SOURCE))
    activity_count = db.scalar(select(func.count()).select_from(Activity)) or 0
    return {
        "source": GHOSTFOLIO_SOURCE,
        "activity_count": activity_count,
        "price_snapshot_count": price_snapshot_count(db),
        "last_sync_at": state.last_sync_at.isoformat() if state and state.last_sync_at else None,
        "checksum": state.checksum if state else None,
        "meta": state.meta if state else None,
        "prices": {
            "last_sync_at": (
                price_state.last_sync_at.isoformat()
                if price_state and price_state.last_sync_at
                else None
            ),
            "meta": price_state.meta if price_state else None,
        },
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
        prices = sync_ghostfolio_prices(
            db,
            client,
            history_days=settings.ghostfolio_price_history_days,
            default_data_source=settings.ghostfolio_data_source,
        )
        fifo = rebuild_lots(db)
        metrics_days = rebuild_metrics_daily(db)
    except GhostfolioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except FifoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "fetched": result.fetched,
        "upserted": result.upserted,
        "deleted": result.deleted,
        "prune_skipped": result.prune_skipped,
        "checksum": result.checksum,
        "price_assets": prices.assets,
        "price_upserted": prices.upserted,
        "price_skipped": prices.skipped,
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


@app.post("/api/staging/sync", response_model=None)
def staging_sync(
    mode: str = Query(default=SYNC_MODE_PARTIAL),
    db: Session = Depends(get_db),
):
    """Pull Paperless → staging.

    ``mode=partial`` (default): newest ≤100 docs, JSON result.
    ``mode=full``: all pages matching filters, NDJSON progress stream.
    """
    resolved = (mode or SYNC_MODE_PARTIAL).strip().lower()
    if resolved not in {SYNC_MODE_PARTIAL, SYNC_MODE_FULL}:
        raise HTTPException(status_code=400, detail="mode must be 'partial' or 'full'")

    client = _paperless_client()
    cfg = get_paperless_settings(db)
    filters_active = has_sync_filters(cfg)

    if resolved == SYNC_MODE_PARTIAL:
        try:
            result = sync_paperless_documents(db, client, mode=SYNC_MODE_PARTIAL)
        except (PaperlessError, ValueError) as exc:
            raise HTTPException(
                status_code=502 if isinstance(exc, PaperlessError) else 400,
                detail=str(exc),
            ) from exc
        return {
            "event": "done",
            "scanned": result.scanned,
            "upserted": result.upserted,
            "skipped": result.skipped,
            "mode": result.mode,
            "filters_active": result.filters_active,
        }

    # Full sync: stream progress so the UI can show work is ongoing.
    queue: SimpleQueue[dict | None] = SimpleQueue()
    SessionLocal = get_session_factory()
    paperless_url = settings.paperless_url
    paperless_token = settings.paperless_token

    def worker() -> None:
        session = SessionLocal()
        local_client = PaperlessClient(paperless_url or "", paperless_token or "", timeout=120.0)
        try:
            def on_progress(event: dict) -> None:
                queue.put(event)

            try:
                result = sync_paperless_documents(
                    session,
                    local_client,
                    mode=SYNC_MODE_FULL,
                    on_progress=on_progress,
                )
                session.commit()
                queue.put(
                    {
                        "event": "done",
                        "scanned": result.scanned,
                        "upserted": result.upserted,
                        "skipped": result.skipped,
                        "mode": result.mode,
                        "filters_active": result.filters_active,
                        "warning": (
                            None
                            if filters_active
                            else "Full sync without tag/document-type filter"
                        ),
                    }
                )
            except Exception as exc:  # noqa: BLE001 - stream error to client
                session.rollback()
                queue.put({"event": "error", "detail": str(exc)})
        finally:
            session.close()
            queue.put(None)

    Thread(target=worker, daemon=True).start()

    def generate() -> Generator[str, None, None]:
        yield json.dumps(
            {
                "event": "start",
                "mode": SYNC_MODE_FULL,
                "filters_active": filters_active,
                "warning": (
                    None
                    if filters_active
                    else "Full sync without filters — large archives may take minutes"
                ),
            }
        ) + "\n"
        while True:
            try:
                item = queue.get(timeout=300)
            except Empty:
                yield json.dumps({"event": "error", "detail": "Sync timed out"}) + "\n"
                break
            if item is None:
                break
            yield json.dumps(item) + "\n"

    return StreamingResponse(
        generate(),
        media_type="application/x-ndjson",
        headers={
            # Discourage intermediary buffering so progress arrives promptly.
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
        },
    )


def _paperless_document_base_url(cfg: dict) -> str | None:
    public = cfg.get("public_url")
    if public:
        return str(public).rstrip("/")
    if settings.paperless_url:
        return settings.paperless_url.rstrip("/")
    return None


def _paperless_settings_payload(cfg: dict) -> dict:
    return {
        "roles": list(FIELD_ROLES),
        "role_meta": list(FIELD_ROLE_META),
        "field_map": cfg["field_map"],
        "tag": cfg["tag"],
        "sync_tags": cfg.get("sync_tags") or [],
        "sync_document_types": cfg.get("sync_document_types") or [],
        "ghostfolio_default_account_id": cfg["ghostfolio_default_account_id"],
        "ghostfolio_data_source": cfg["ghostfolio_data_source"],
        "public_url": cfg.get("public_url"),
        "document_base_url": _paperless_document_base_url(cfg),
        "paperless_configured": bool(settings.paperless_url and settings.paperless_token),
        "webhook_secret_configured": bool(settings.paperless_webhook_secret),
        "webhook_path": "/api/webhooks/paperless",
        "paperless_sync_interval_minutes": settings.paperless_sync_interval_minutes,
        "notes": {
            "trade_date": "Handelsdatum = Paperless-Dokumentdatum (created), kein Custom Field.",
            "currency": "Währung aus Monetary-Feldern Kurs/Entgelte (z.B. EUR152.34).",
            "symbol": "Ghostfolio-Symbol = ISIN (kein separates Symbol-Feld).",
            "public_url": "Browser-URL für Doc-Links; Fallback PAPERLESS_URL (Env).",
            "sync_filters": (
                "Teilsync: neueste ≤100 Docs. Full Sync: alle Seiten. "
                "Filter: mehrere Tags = ODER, mehrere Dokumententypen = ODER; "
                "Tags und Typen zusammen = UND. Webhook nutzt den Filter nicht, "
                "prüft aber weiterhin Pflichtfelder."
            ),
        },
    }


@app.get("/api/settings/paperless")
def settings_paperless_get(db: Session = Depends(get_db)) -> dict:
    return _paperless_settings_payload(get_paperless_settings(db))


@app.put("/api/settings/paperless")
def settings_paperless_put(payload: dict, db: Session = Depends(get_db)) -> dict:
    try:
        cfg = save_paperless_settings(db, payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _paperless_settings_payload(cfg)


@app.get("/api/settings/portfolio")
def settings_portfolio_get(db: Session = Depends(get_db)) -> dict:
    return get_portfolio_settings(db)


@app.put("/api/settings/portfolio")
def settings_portfolio_put(payload: dict, db: Session = Depends(get_db)) -> dict:
    try:
        return save_portfolio_settings(db, payload)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/settings/paperless/custom-fields")
def settings_paperless_custom_fields() -> dict:
    client = _paperless_client()
    try:
        fields = client.list_custom_fields()
    except PaperlessError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "count": len(fields),
        "fields": [
            {
                "id": int(item["id"]),
                "name": item.get("name"),
                "data_type": item.get("data_type"),
            }
            for item in fields
            if item.get("id") is not None
        ],
    }


def _id_name_list(items: list[dict]) -> list[dict]:
    return [
        {"id": int(item["id"]), "name": item.get("name") or f"#{item['id']}"}
        for item in items
        if item.get("id") is not None
    ]


@app.get("/api/settings/paperless/tags")
def settings_paperless_tags() -> dict:
    client = _paperless_client()
    try:
        tags = client.list_tags()
    except PaperlessError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    rows = _id_name_list(tags)
    return {"count": len(rows), "tags": rows}


@app.get("/api/settings/paperless/document-types")
def settings_paperless_document_types() -> dict:
    client = _paperless_client()
    try:
        types = client.list_document_types()
    except PaperlessError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    rows = _id_name_list(types)
    return {"count": len(rows), "document_types": rows}


@app.post("/api/settings/paperless/test")
def settings_paperless_test() -> dict:
    client = _paperless_client()
    try:
        fields = client.list_custom_fields()
        tags = client.list_tags()
        doc_types = client.list_document_types()
    except PaperlessError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "ok": True,
        "custom_field_count": len(fields),
        "tag_count": len(tags),
        "document_type_count": len(doc_types),
        "url": settings.paperless_url,
    }


@app.post("/api/webhooks/paperless")
async def webhook_paperless(
    request: Request,
    db: Session = Depends(get_db),
    x_portmetrics_secret: str | None = Header(default=None, alias="X-PortMetrics-Secret"),
) -> dict:
    if not settings.paperless_webhook_secret:
        raise HTTPException(
            status_code=503,
            detail="PAPERLESS_WEBHOOK_SECRET is not configured",
        )
    provided = x_portmetrics_secret or request.query_params.get("secret")
    if not webhook_secret_matches(provided, settings.paperless_webhook_secret):
        raise HTTPException(status_code=401, detail="Invalid webhook secret")

    content_type = (request.headers.get("content-type") or "").lower()
    payload: object
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
    elif (
        "application/x-www-form-urlencoded" in content_type or "multipart/form-data" in content_type
    ):
        form = await request.form()
        payload = dict(form)
    else:
        raw = (await request.body()).decode("utf-8", errors="replace").strip()
        payload = raw if raw else {}

    document_id = parse_paperless_document_id(payload)
    if document_id is None and isinstance(payload, dict):
        # Nested body used by some webhook templates
        document_id = parse_paperless_document_id(payload.get("document"))
    if document_id is None:
        raise HTTPException(
            status_code=400,
            detail="Could not resolve document id (send document_id or doc_url)",
        )

    client = _paperless_client()
    try:
        result = ingest_paperless_document(db, client, document_id)
    except PaperlessError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "document_id": result.document_id,
        "action": result.action,
        "reason": result.reason,
        "staging_id": result.staging_id,
        "hint": (
            "Dokument übersprungen — Pflichtfelder prüfen (ISIN/Typ/Kurs) oder Mapping."
            if result.action == "skipped"
            else None
        ),
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
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except GhostfolioError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/staging/{staging_id}/reject")
def staging_reject(staging_id: int, db: Session = Depends(get_db)) -> dict:
    try:
        return reject_staging(db, staging_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/staging/match-activities")
def staging_match_activities(db: Session = Depends(get_db)) -> dict:
    """Manually link open staging docs to existing Ghostfolio activities (no GF import)."""
    result = match_staging_to_activities(db)
    return {
        "scanned": result.scanned,
        "matched": result.matched,
        "ambiguous": result.ambiguous,
        "unmatched": result.unmatched,
        "skipped": result.skipped,
        "items": result.items,
    }


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
