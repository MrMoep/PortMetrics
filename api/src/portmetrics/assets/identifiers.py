"""ISIN ↔ WKN / preferred Ghostfolio symbol map."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from portmetrics.db.models import Activity, AssetIdentifier, StagingImport

ASSET_ID_PREFERENCES = ("symbol", "wkn", "isin")
DEFAULT_ASSET_ID_PREFERENCE = "symbol"
SETTINGS_ASSETS_HASH = "#settings/assets"


@dataclass(frozen=True)
class SymbolSuggestion:
    symbol: str
    count: int
    last_trade_date: date | None


@dataclass(frozen=True)
class MappingConflict:
    field: str
    table_value: str
    observed_value: str
    message: str


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


def normalize_symbol(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    return text or None


def serialize_identifier(row: AssetIdentifier) -> dict[str, Any]:
    return {
        "isin": row.isin,
        "wkn": row.wkn,
        "preferred_symbol": row.preferred_symbol,
        "paperless_doc_id": row.paperless_doc_id,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_identifiers(session: Session) -> list[dict[str, Any]]:
    rows = session.scalars(select(AssetIdentifier).order_by(AssetIdentifier.isin.asc())).all()
    return [serialize_identifier(row) for row in rows]


def get_identifier(session: Session, isin: str | None) -> AssetIdentifier | None:
    isin_n = normalize_isin(isin)
    if not isin_n or not looks_like_isin(isin_n):
        return None
    return session.get(AssetIdentifier, isin_n)


def preferred_symbol_map(session: Session) -> dict[str, str]:
    rows = session.scalars(
        select(AssetIdentifier).where(AssetIdentifier.preferred_symbol.is_not(None))
    ).all()
    out: dict[str, str] = {}
    for row in rows:
        symbol = normalize_symbol(row.preferred_symbol)
        if symbol:
            out[row.isin] = symbol
    return out


def upsert_mapping(
    session: Session,
    *,
    isin: str,
    wkn: str | None = None,
    preferred_symbol: str | None = None,
    paperless_doc_id: int | None = None,
    clear_missing: bool = False,
) -> AssetIdentifier:
    """Create/update a mapping row. Table values are authoritative when set."""
    isin_n = normalize_isin(isin)
    if not isin_n or not looks_like_isin(isin_n):
        raise ValueError("ISIN must be a 12-character alphanumeric code")

    wkn_n = normalize_wkn(wkn)
    symbol_n = normalize_symbol(preferred_symbol)
    row = session.get(AssetIdentifier, isin_n)
    if row is None:
        row = AssetIdentifier(
            isin=isin_n,
            wkn=wkn_n,
            preferred_symbol=symbol_n,
            paperless_doc_id=paperless_doc_id,
        )
        session.add(row)
    else:
        if clear_missing or wkn_n is not None:
            row.wkn = wkn_n
        if clear_missing or symbol_n is not None:
            row.preferred_symbol = symbol_n
        if paperless_doc_id is not None:
            row.paperless_doc_id = paperless_doc_id
    session.flush()
    return row


def delete_mapping(session: Session, isin: str) -> bool:
    row = get_identifier(session, isin)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    return True


def replace_mappings(session: Session, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Replace all mapping rows with the provided list (full save from Settings UI)."""
    existing = {row.isin: row for row in session.scalars(select(AssetIdentifier)).all()}
    keep: set[str] = set()
    for raw in items:
        isin_n = normalize_isin(raw.get("isin"))
        if not isin_n or not looks_like_isin(isin_n):
            raise ValueError(f"Invalid ISIN: {raw.get('isin')!r}")
        keep.add(isin_n)
        upsert_mapping(
            session,
            isin=isin_n,
            wkn=raw.get("wkn"),
            preferred_symbol=raw.get("preferred_symbol"),
            paperless_doc_id=(
                int(raw["paperless_doc_id"])
                if raw.get("paperless_doc_id") is not None
                else existing.get(isin_n).paperless_doc_id
                if isin_n in existing
                else None
            ),
            clear_missing=True,
        )
    for isin, row in existing.items():
        if isin not in keep:
            session.delete(row)
    session.flush()
    return list_identifiers(session)


def wkn_conflict(
    *,
    table_wkn: str | None,
    observed_wkn: str | None,
) -> MappingConflict | None:
    table_n = normalize_wkn(table_wkn)
    observed_n = normalize_wkn(observed_wkn)
    if not table_n or not observed_n:
        return None
    if table_n == observed_n:
        return None
    return MappingConflict(
        field="wkn",
        table_value=table_n,
        observed_value=observed_n,
        message=(
            f"WKN weicht von der Kennungs-Tabelle ab "
            f"(Tabelle {table_n}, Beleg {observed_n}). "
            f"Tabelle anpassen: {SETTINGS_ASSETS_HASH}"
        ),
    )


def upsert_isin_wkn(
    session: Session,
    *,
    isin: str | None,
    wkn: str | None,
    paperless_doc_id: int | None = None,
) -> AssetIdentifier | None:
    """Learn ISIN→WKN from Paperless without overriding table SoT values.

    - No row: create with WKN, preferred_symbol unset
    - Row without WKN: fill WKN
    - Row with same WKN: refresh paperless_doc_id
    - Row with different WKN: leave table unchanged (caller surfaces conflict)
    """
    isin_n = normalize_isin(isin)
    wkn_n = normalize_wkn(wkn)
    if not isin_n or not wkn_n:
        return None
    if not looks_like_isin(isin_n):
        return None

    row = session.get(AssetIdentifier, isin_n)
    if row is None:
        row = AssetIdentifier(
            isin=isin_n,
            wkn=wkn_n,
            preferred_symbol=None,
            paperless_doc_id=paperless_doc_id,
        )
        session.add(row)
    elif not normalize_wkn(row.wkn):
        row.wkn = wkn_n
        if paperless_doc_id is not None:
            row.paperless_doc_id = paperless_doc_id
    elif normalize_wkn(row.wkn) == wkn_n:
        if paperless_doc_id is not None:
            row.paperless_doc_id = paperless_doc_id
    else:
        # Conflict: table wins — do not overwrite.
        return row
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
    return {row.isin: row.wkn for row in rows if normalize_wkn(row.wkn)}


def paperless_doc_map(session: Session) -> dict[str, int]:
    """ISIN → latest known Paperless document id from asset_identifiers."""
    rows = session.scalars(
        select(AssetIdentifier).where(AssetIdentifier.paperless_doc_id.is_not(None))
    ).all()
    return {row.isin: int(row.paperless_doc_id) for row in rows if row.paperless_doc_id is not None}


def suggest_symbol_from_history(session: Session, isin: str | None) -> SymbolSuggestion | None:
    """Majority symbol for ISIN; ties broken by latest trade_date."""
    isin_n = normalize_isin(isin)
    if not isin_n:
        return None
    rows = session.scalars(
        select(Activity)
        .where(Activity.isin == isin_n)
        .order_by(Activity.trade_date.desc(), Activity.id.desc())
    ).all()
    if not rows:
        return None

    counts: Counter[str] = Counter()
    last_date: dict[str, date] = {}
    for activity in rows:
        symbol = normalize_symbol(activity.symbol)
        if not symbol or looks_like_isin(symbol):
            continue
        counts[symbol] += 1
        if symbol not in last_date:
            last_date[symbol] = activity.trade_date

    if not counts:
        return None

    def sort_key(symbol: str) -> tuple[int, date]:
        return (counts[symbol], last_date.get(symbol) or date.min)

    best = max(counts.keys(), key=sort_key)
    return SymbolSuggestion(
        symbol=best,
        count=counts[best],
        last_trade_date=last_date.get(best),
    )


def apply_symbol_suggestion(
    session: Session,
    *,
    isin: str,
    symbol: str | None = None,
    wkn: str | None = None,
    paperless_doc_id: int | None = None,
) -> AssetIdentifier:
    """Persist a history suggestion (or explicit symbol) into the mapping table."""
    isin_n = normalize_isin(isin)
    if not isin_n:
        raise ValueError("ISIN required")
    chosen = normalize_symbol(symbol)
    if not chosen:
        suggestion = suggest_symbol_from_history(session, isin_n)
        if suggestion is None:
            raise ValueError("No symbol suggestion available for this ISIN")
        chosen = suggestion.symbol
    existing = get_identifier(session, isin_n)
    return upsert_mapping(
        session,
        isin=isin_n,
        wkn=wkn if wkn is not None else (existing.wkn if existing else None),
        preferred_symbol=chosen,
        paperless_doc_id=paperless_doc_id,
        clear_missing=False,
    )


def staging_mapping_status(
    session: Session,
    payload: dict[str, Any] | None,
) -> dict[str, Any]:
    """Enrich staging rows with mapping / suggestion / conflict hints."""
    payload = payload if isinstance(payload, dict) else {}
    isin = normalize_isin(payload.get("isin"))
    observed_wkn = normalize_wkn(payload.get("wkn"))
    row = get_identifier(session, isin) if isin else None
    preferred = normalize_symbol(row.preferred_symbol) if row else None
    suggestion = suggest_symbol_from_history(session, isin) if isin else None
    conflict = wkn_conflict(
        table_wkn=row.wkn if row else None,
        observed_wkn=observed_wkn,
    )
    needs_mapping = bool(isin) and not preferred
    return {
        "isin": isin,
        "preferred_symbol": preferred,
        "table_wkn": normalize_wkn(row.wkn) if row else None,
        "suggested_symbol": suggestion.symbol if suggestion else None,
        "suggested_count": suggestion.count if suggestion else None,
        "suggested_last_trade_date": (
            suggestion.last_trade_date.isoformat()
            if suggestion and suggestion.last_trade_date
            else None
        ),
        "wkn_conflict": (
            {
                "table_value": conflict.table_value,
                "observed_value": conflict.observed_value,
                "message": conflict.message,
            }
            if conflict
            else None
        ),
        "needs_mapping": needs_mapping,
        "mapping_ready": bool(preferred) and conflict is None,
        "settings_href": SETTINGS_ASSETS_HASH,
    }


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
