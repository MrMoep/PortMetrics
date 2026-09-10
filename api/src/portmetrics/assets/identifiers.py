"""ISIN ↔ WKN identifier map (learned from Paperless)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from portmetrics.db.models import AssetIdentifier, StagingImport

ASSET_ID_PREFERENCES = ("symbol", "wkn", "isin")
DEFAULT_ASSET_ID_PREFERENCE = "symbol"


def looks_like_isin(value: str | None) -> bool:
    if not value:
        return False
    text = value.strip().upper()
    if len(text) != 12:
        return False
    return text[:2].isalpha() and text[2:].isalnum()


def normalize_isin(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().upper()
    return text or None


def normalize_wkn(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip().upper()
    return text or None


def upsert_isin_wkn(
    session: Session,
    *,
    isin: str | None,
    wkn: str | None,
    paperless_doc_id: int | None = None,
) -> AssetIdentifier | None:
    """Persist ISIN→WKN when both values are present. Last write wins on conflict."""
    isin_n = normalize_isin(isin)
    wkn_n = normalize_wkn(wkn)
    if not isin_n or not wkn_n:
        return None
    if not looks_like_isin(isin_n):
        return None

    row = session.get(AssetIdentifier, isin_n)
    if row is None:
        row = AssetIdentifier(isin=isin_n, wkn=wkn_n, paperless_doc_id=paperless_doc_id)
        session.add(row)
    else:
        row.wkn = wkn_n
        if paperless_doc_id is not None:
            row.paperless_doc_id = paperless_doc_id
    session.flush()
    return row


def upsert_from_payload(session: Session, payload: dict[str, Any] | None) -> AssetIdentifier | None:
    if not isinstance(payload, dict):
        return None
    doc_id = payload.get("paperless_doc_id")
    return upsert_isin_wkn(
        session,
        isin=payload.get("isin"),
        wkn=payload.get("wkn"),
        paperless_doc_id=int(doc_id) if doc_id is not None else None,
    )


def wkn_map(session: Session) -> dict[str, str]:
    rows = session.scalars(select(AssetIdentifier)).all()
    return {row.isin: row.wkn for row in rows}


def resolve_isin_code(
    *,
    activity_isin: str | None,
    asset_key: str,
    symbol: str | None,
) -> str | None:
    if activity_isin:
        return normalize_isin(activity_isin)
    if looks_like_isin(asset_key):
        return normalize_isin(asset_key)
    if looks_like_isin(symbol):
        return normalize_isin(symbol)
    return None


def pick_display_id(
    *,
    preference: str,
    symbol: str | None,
    wkn: str | None,
    isin: str | None,
    asset_key: str,
) -> str:
    pref = preference if preference in ASSET_ID_PREFERENCES else DEFAULT_ASSET_ID_PREFERENCE
    chains: dict[str, list[str | None]] = {
        "symbol": [symbol, isin, wkn, asset_key],
        "wkn": [wkn, symbol, isin, asset_key],
        "isin": [isin, symbol, wkn, asset_key],
    }
    for value in chains[pref]:
        if value:
            return value
    return asset_key or "—"


def enrich_asset_fields(
    *,
    asset_key: str,
    activity_isin: str | None,
    symbol: str | None,
    wkn_by_isin: dict[str, str],
    preference: str,
) -> dict[str, str | None]:
    isin_code = resolve_isin_code(
        activity_isin=activity_isin,
        asset_key=asset_key,
        symbol=symbol,
    )
    wkn = None
    for key in (isin_code, normalize_isin(asset_key)):
        if key and key in wkn_by_isin:
            wkn = wkn_by_isin[key]
            break
    display_id = pick_display_id(
        preference=preference,
        symbol=symbol,
        wkn=wkn,
        isin=isin_code,
        asset_key=asset_key,
    )
    return {
        "symbol": symbol,
        "wkn": wkn,
        "isin_code": isin_code,
        "display_id": display_id,
    }


def backfill_from_staging(session: Session) -> int:
    """Learn mappings from existing staging payloads that already have both fields."""
    rows = session.scalars(select(StagingImport)).all()
    written = 0
    for row in rows:
        if upsert_from_payload(session, row.payload):
            written += 1
    return written
