"""Match open Paperless staging rows to existing Ghostfolio activities (manual only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from portmetrics.assets.identifiers import looks_like_isin, normalize_isin, upsert_from_payload
from portmetrics.db.models import Activity, DocumentLink, Lot, StagingImport
from portmetrics.paperless.staging import STATUS_IMPORTED, STATUS_PENDING

# Exact auto-match only; no date window (ambiguous cases stay in staging).
PRICE_TOLERANCE = Decimal("0.01")
LINK_TYPE_MATCHED = "matched"


@dataclass(frozen=True)
class MatchResult:
    scanned: int
    matched: int
    ambiguous: int
    unmatched: int
    skipped: int
    items: list[dict[str, Any]]


def _as_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    try:
        if "T" in text:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _activity_isin_keys(activity: Activity) -> set[str]:
    keys: set[str] = set()
    for raw in (activity.isin, activity.symbol):
        normalized = normalize_isin(raw)
        if normalized and looks_like_isin(normalized):
            keys.add(normalized)
        elif raw:
            keys.add(str(raw).strip().upper())
    return keys


def _price_close(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= PRICE_TOLERANCE


def _existing_doc_links(session: Session) -> set[int]:
    rows = session.scalars(select(DocumentLink.paperless_doc_id)).all()
    return {int(doc_id) for doc_id in rows if doc_id is not None}


def _linked_activity_ids(session: Session) -> set[int]:
    rows = session.scalars(
        select(DocumentLink.activity_id).where(DocumentLink.activity_id.is_not(None))
    ).all()
    return {int(activity_id) for activity_id in rows if activity_id is not None}


def _find_candidates(
    activities: list[Activity],
    *,
    isin: str,
    trade_date: date,
    quantity: Decimal,
    wp_typ: str,
    unit_price: Decimal | None,
    linked_activity_ids: set[int],
) -> list[Activity]:
    isin_n = normalize_isin(isin) or isin.strip().upper()
    base: list[Activity] = []
    for activity in activities:
        if activity.id in linked_activity_ids:
            continue
        if str(activity.type).upper() != wp_typ:
            continue
        if activity.trade_date != trade_date:
            continue
        if Decimal(activity.quantity) != quantity:
            continue
        if isin_n not in _activity_isin_keys(activity):
            continue
        base.append(activity)

    if len(base) <= 1 or unit_price is None:
        return base

    priced = [row for row in base if _price_close(Decimal(row.unit_price), unit_price)]
    return priced if priced else base


def _attach_link(
    session: Session,
    row: StagingImport,
    activity: Activity,
) -> dict[str, Any]:
    upsert_from_payload(session, row.payload if isinstance(row.payload, dict) else None)
    lot = session.scalar(select(Lot).where(Lot.activity_id == activity.id))
    session.add(
        DocumentLink(
            paperless_doc_id=row.paperless_doc_id,
            activity_id=activity.id,
            lot_id=lot.id if lot is not None else None,
            link_type=LINK_TYPE_MATCHED,
        )
    )
    row.status = STATUS_IMPORTED
    row.error = None
    row.gf_activity_id = activity.gf_activity_id
    session.flush()
    return {
        "staging_id": row.id,
        "paperless_doc_id": row.paperless_doc_id,
        "outcome": "matched",
        "activity_id": activity.id,
        "lot_id": lot.id if lot is not None else None,
    }


def match_staging_to_activities(session: Session) -> MatchResult:
    """Link open staging rows to existing activities when the match is unique.

    Criteria (auto): type + ISIN + trade_date + quantity; unit_price breaks ties.
    Never imports into Ghostfolio. Intended to be triggered manually only.
    """
    open_rows = session.scalars(
        select(StagingImport)
        .where(StagingImport.status == STATUS_PENDING)
        .order_by(StagingImport.id.asc())
    ).all()
    error_rows = session.scalars(
        select(StagingImport)
        .where(StagingImport.status == "error")
        .order_by(StagingImport.id.asc())
    ).all()
    rows = list(open_rows) + list(error_rows)

    activities = list(session.scalars(select(Activity)).all())
    linked_docs = _existing_doc_links(session)
    linked_activity_ids = _linked_activity_ids(session)

    matched = 0
    ambiguous = 0
    unmatched = 0
    skipped = 0
    items: list[dict[str, Any]] = []

    for row in rows:
        if row.paperless_doc_id in linked_docs:
            skipped += 1
            items.append(
                {
                    "staging_id": row.id,
                    "paperless_doc_id": row.paperless_doc_id,
                    "outcome": "skipped",
                    "reason": "document already linked",
                }
            )
            continue

        payload = row.payload if isinstance(row.payload, dict) else {}
        wp_typ = str(payload.get("wp_typ") or "").strip().upper()
        isin = str(payload.get("isin") or payload.get("symbol") or "").strip()
        trade_date = _as_date(payload.get("trade_date"))
        quantity = _as_decimal(payload.get("quantity"))
        unit_price = _as_decimal(payload.get("unit_price"))

        if not wp_typ or not isin or trade_date is None or quantity is None:
            skipped += 1
            items.append(
                {
                    "staging_id": row.id,
                    "paperless_doc_id": row.paperless_doc_id,
                    "outcome": "skipped",
                    "reason": "incomplete staging payload",
                }
            )
            continue

        candidates = _find_candidates(
            activities,
            isin=isin,
            trade_date=trade_date,
            quantity=quantity,
            wp_typ=wp_typ,
            unit_price=unit_price,
            linked_activity_ids=linked_activity_ids,
        )

        if len(candidates) == 1:
            detail = _attach_link(session, row, candidates[0])
            linked_docs.add(row.paperless_doc_id)
            linked_activity_ids.add(candidates[0].id)
            matched += 1
            items.append(detail)
            continue

        if len(candidates) == 0:
            unmatched += 1
            items.append(
                {
                    "staging_id": row.id,
                    "paperless_doc_id": row.paperless_doc_id,
                    "outcome": "unmatched",
                    "reason": "no activity with same type/ISIN/date/quantity",
                }
            )
            continue

        ambiguous += 1
        items.append(
            {
                "staging_id": row.id,
                "paperless_doc_id": row.paperless_doc_id,
                "outcome": "ambiguous",
                "reason": f"{len(candidates)} candidate activities",
                "activity_ids": [c.id for c in candidates],
            }
        )

    session.flush()
    return MatchResult(
        scanned=len(rows),
        matched=matched,
        ambiguous=ambiguous,
        unmatched=unmatched,
        skipped=skipped,
        items=items,
    )
