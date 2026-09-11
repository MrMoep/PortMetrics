"""Match Paperless documents to existing Ghostfolio lots/activities (manual only)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from portmetrics.assets.identifiers import (
    IdentifierLookups,
    load_identifier_lookups,
    looks_like_isin,
    normalize_isin,
    normalize_wkn,
    upsert_from_payload,
)
from portmetrics.db.models import Activity, DocumentLink, Lot, StagingImport
from portmetrics.paperless.client import PaperlessClient
from portmetrics.paperless.mapping import (
    ensure_required_roles,
    extract_fields_by_roles,
    get_paperless_settings,
    has_sync_filters,
    resolve_role_field_map,
    select_option_maps_by_field_id,
    sync_filter_ids,
)
from portmetrics.paperless.staging import (
    STATUS_IMPORTED,
    STATUS_PENDING,
    build_staging_payload,
    resolve_legacy_tag_id,
)

# Exact auto-match only; no date window (ambiguous cases stay unmatched).
PRICE_TOLERANCE = Decimal("0.01")
LINK_TYPE_MATCHED = "matched"
LINK_TYPE_MANUAL = "manual"
WARN_DOCUMENT_COUNT = 100


@dataclass(frozen=True)
class MatchResult:
    scanned: int
    matched: int
    ambiguous: int
    unmatched: int
    skipped: int
    items: list[dict[str, Any]]


@dataclass(frozen=True)
class LinkPreview:
    document_count: int
    unlinked_lots: int
    filters_active: bool
    warn_no_filter: bool
    warn_large: bool
    warning: str | None = None


@dataclass(frozen=True)
class _DocCandidate:
    paperless_doc_id: int
    wp_typ: str
    isin: str
    trade_date: date
    quantity: Decimal
    unit_price: Decimal | None
    payload: dict[str, Any]
    wkn: str | None = None


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


def _token_keys(raw: str | None) -> set[str]:
    if not raw:
        return set()
    text = str(raw).strip()
    if not text:
        return set()
    normalized = normalize_isin(text)
    if normalized and looks_like_isin(normalized):
        return {normalized}
    return {text.upper()}


def _expand_identity_keys(keys: set[str], lookups: IdentifierLookups) -> set[str]:
    """Bridge ISIN ↔ preferred_symbol ↔ WKN via asset_identifiers."""
    if not keys:
        return set()

    symbol_to_isin = {
        symbol.upper(): isin for symbol, isin in lookups.isin_by_symbol.items()
    }
    isin_to_symbols: dict[str, set[str]] = {}
    for symbol, isin in lookups.isin_by_symbol.items():
        isin_to_symbols.setdefault(isin, set()).add(symbol.upper())

    wkn_to_isins: dict[str, set[str]] = {}
    for isin, wkn in lookups.wkn_by_isin.items():
        wkn_n = normalize_wkn(wkn)
        if wkn_n:
            wkn_to_isins.setdefault(wkn_n, set()).add(isin)
    for symbol, wkn in lookups.wkn_by_symbol.items():
        wkn_n = normalize_wkn(wkn)
        isin = symbol_to_isin.get(symbol.upper())
        if wkn_n and isin:
            wkn_to_isins.setdefault(wkn_n, set()).add(isin)

    out = set(keys)
    for key in list(keys):
        if looks_like_isin(key):
            out.update(isin_to_symbols.get(key, ()))
            wkn = normalize_wkn(lookups.wkn_by_isin.get(key))
            if wkn:
                out.add(wkn)
            continue

        mapped_isin = symbol_to_isin.get(key)
        if mapped_isin:
            out.add(mapped_isin)
            out.update(isin_to_symbols.get(mapped_isin, ()))
            wkn = normalize_wkn(lookups.wkn_by_isin.get(mapped_isin))
            if wkn:
                out.add(wkn)
            continue

        for mapped_isin in wkn_to_isins.get(key, ()):
            out.add(mapped_isin)
            out.update(isin_to_symbols.get(mapped_isin, ()))
            wkn = normalize_wkn(lookups.wkn_by_isin.get(mapped_isin))
            if wkn:
                out.add(wkn)
    return out


def _activity_identity_keys(
    activity: Activity, lookups: IdentifierLookups
) -> set[str]:
    keys: set[str] = set()
    for raw in (activity.isin, activity.symbol):
        keys |= _token_keys(raw)
    return _expand_identity_keys(keys, lookups)


def _doc_identity_keys(
    isin: str,
    lookups: IdentifierLookups,
    *,
    wkn: str | None = None,
) -> set[str]:
    keys = _token_keys(isin)
    keys |= _token_keys(wkn)
    return _expand_identity_keys(keys, lookups)


def _identities_overlap(
    doc_isin: str,
    activity: Activity,
    lookups: IdentifierLookups,
    *,
    doc_wkn: str | None = None,
) -> bool:
    return bool(
        _doc_identity_keys(doc_isin, lookups, wkn=doc_wkn)
        & _activity_identity_keys(activity, lookups)
    )


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


def _linked_lot_ids(session: Session) -> set[int]:
    rows = session.scalars(
        select(DocumentLink.lot_id).where(DocumentLink.lot_id.is_not(None))
    ).all()
    return {int(lot_id) for lot_id in rows if lot_id is not None}


def _sync_filter_context(
    session: Session,
    client: PaperlessClient,
) -> tuple[list[int], list[int], str | None, bool]:
    paperless_settings = get_paperless_settings(session)
    tag_ids, type_ids = sync_filter_ids(paperless_settings)
    legacy_tag = paperless_settings.get("tag")
    if not tag_ids and legacy_tag:
        tag_ids = resolve_legacy_tag_id(client, str(legacy_tag))
    filters_active = bool(tag_ids or type_ids) or has_sync_filters(paperless_settings)
    legacy_name = str(legacy_tag) if legacy_tag and not tag_ids else None
    return tag_ids, type_ids, legacy_name, filters_active


def count_unlinked_lots(session: Session) -> int:
    linked_lots = _linked_lot_ids(session)
    linked_activities = _linked_activity_ids(session)
    lots = list(session.scalars(select(Lot)).all())
    n = 0
    for lot in lots:
        if lot.id in linked_lots or lot.activity_id in linked_activities:
            continue
        n += 1
    return n


def preview_link_scope(session: Session, client: PaperlessClient) -> LinkPreview:
    """Cheap preview: filtered Paperless doc count + unlinked lot count."""
    tag_ids, type_ids, legacy_tag, filters_active = _sync_filter_context(session, client)
    document_count = client.count_documents(
        tag_ids=tag_ids or None,
        document_type_ids=type_ids or None,
        tag=legacy_tag,
    )
    unlinked = count_unlinked_lots(session)
    warn_no_filter = not filters_active
    warn_large = document_count >= WARN_DOCUMENT_COUNT
    warning: str | None = None
    if warn_no_filter:
        warning = (
            f"Keine Tag-/Dokumententyp-Filter. {document_count} Docs, "
            f"{unlinked} unverknüpfte Lots — kann länger dauern."
        )
    elif warn_large:
        warning = (
            f"{document_count} Docs im Filter, {unlinked} unverknüpfte Lots — "
            "Lauf kann etwas dauern."
        )
    return LinkPreview(
        document_count=document_count,
        unlinked_lots=unlinked,
        filters_active=filters_active,
        warn_no_filter=warn_no_filter,
        warn_large=warn_large,
        warning=warning,
    )


def _find_candidate_activities(
    activities: list[Activity],
    *,
    isin: str,
    trade_date: date,
    quantity: Decimal,
    wp_typ: str,
    unit_price: Decimal | None,
    linked_activity_ids: set[int],
    lookups: IdentifierLookups,
    wkn: str | None = None,
) -> list[Activity]:
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
        if not _identities_overlap(isin, activity, lookups, doc_wkn=wkn):
            continue
        base.append(activity)

    if len(base) <= 1 or unit_price is None:
        return base

    priced = [row for row in base if _price_close(Decimal(row.unit_price), unit_price)]
    return priced if priced else base


def _doc_matches_activity(
    doc: _DocCandidate,
    activity: Activity,
    lookups: IdentifierLookups,
) -> bool:
    if str(activity.type).upper() != doc.wp_typ:
        return False
    if activity.trade_date != doc.trade_date:
        return False
    if Decimal(activity.quantity) != doc.quantity:
        return False
    if not _identities_overlap(doc.isin, activity, lookups, doc_wkn=doc.wkn):
        return False
    return True


def _mark_staging_imported(
    session: Session,
    *,
    paperless_doc_id: int,
    activity: Activity,
    payload: dict[str, Any] | None,
) -> int | None:
    """Mark staging row imported so it leaves the open queue (create none)."""
    if payload:
        upsert_from_payload(session, payload)
    row = session.scalar(
        select(StagingImport).where(StagingImport.paperless_doc_id == paperless_doc_id)
    )
    if row is None:
        return None
    row.status = STATUS_IMPORTED
    row.error = None
    row.gf_activity_id = activity.gf_activity_id
    if payload:
        row.payload = payload
    session.flush()
    return row.id


def _attach_lot_link(
    session: Session,
    *,
    doc: _DocCandidate,
    lot: Lot,
    activity: Activity,
    link_type: str = LINK_TYPE_MATCHED,
) -> dict[str, Any]:
    session.add(
        DocumentLink(
            paperless_doc_id=doc.paperless_doc_id,
            activity_id=activity.id,
            lot_id=lot.id,
            link_type=link_type,
        )
    )
    staging_id = _mark_staging_imported(
        session,
        paperless_doc_id=doc.paperless_doc_id,
        activity=activity,
        payload=doc.payload,
    )
    session.flush()
    return {
        "staging_id": staging_id,
        "paperless_doc_id": doc.paperless_doc_id,
        "outcome": "matched",
        "activity_id": activity.id,
        "lot_id": lot.id,
        "link_type": link_type,
    }


def _load_doc_candidates(
    session: Session,
    client: PaperlessClient,
) -> list[_DocCandidate]:
    role_map = resolve_role_field_map(session, client)
    ensure_required_roles(role_map)
    select_maps = select_option_maps_by_field_id(client.list_custom_fields())
    tag_ids, type_ids, legacy_tag, _ = _sync_filter_context(session, client)
    documents = client.list_documents(
        page_size=100,
        tag_ids=tag_ids or None,
        document_type_ids=type_ids or None,
        tag=legacy_tag,
        paginate=True,
        request_timeout=120.0,
    )
    out: list[_DocCandidate] = []
    for document in documents:
        fields = extract_fields_by_roles(document, role_map, select_maps=select_maps)
        try:
            payload = build_staging_payload(document, fields)
        except (ValueError, TypeError, AttributeError):
            continue
        wp_typ = str(payload.get("wp_typ") or "").strip().upper()
        isin = str(payload.get("isin") or payload.get("symbol") or "").strip()
        wkn = str(payload.get("wkn") or "").strip() or None
        trade_date = _as_date(payload.get("trade_date"))
        quantity = _as_decimal(payload.get("quantity"))
        unit_price = _as_decimal(payload.get("unit_price"))
        if not wp_typ or not isin or trade_date is None or quantity is None:
            continue
        out.append(
            _DocCandidate(
                paperless_doc_id=int(document["id"]),
                wp_typ=wp_typ,
                isin=isin,
                trade_date=trade_date,
                quantity=quantity,
                unit_price=unit_price,
                payload=payload,
                wkn=wkn,
            )
        )
    return out


def match_lots_to_documents(session: Session, client: PaperlessClient) -> MatchResult:
    """Link unlinked FIFO lots to filtered Paperless docs when the match is unique.

    For each unlinked lot, find docs with same type + identity + date + quantity
    (unit_price breaks ties). Identity bridges Paperless ISIN/WKN to Ghostfolio
    symbols via asset_identifiers. Only links when the lot has exactly one doc and
    that doc has exactly one lot. Marks existing staging rows imported.
    """
    docs = _load_doc_candidates(session, client)
    linked_docs = _existing_doc_links(session)
    linked_activity_ids = _linked_activity_ids(session)
    linked_lot_ids = _linked_lot_ids(session)
    lookups = load_identifier_lookups(session)

    activities_by_id = {
        row.id: row for row in session.scalars(select(Activity)).all()
    }
    lots = list(session.scalars(select(Lot).order_by(Lot.id.asc())).all())
    unlinked: list[tuple[Lot, Activity]] = []
    for lot in lots:
        if lot.id in linked_lot_ids or lot.activity_id in linked_activity_ids:
            continue
        activity = activities_by_id.get(lot.activity_id)
        if activity is None:
            continue
        unlinked.append((lot, activity))

    # lot_id → matching doc candidates (not yet linked)
    lot_to_docs: dict[int, list[_DocCandidate]] = {}
    doc_to_lots: dict[int, list[int]] = {}
    for lot, activity in unlinked:
        matches: list[_DocCandidate] = []
        for doc in docs:
            if doc.paperless_doc_id in linked_docs:
                continue
            if not _doc_matches_activity(doc, activity, lookups):
                continue
            matches.append(doc)
        if len(matches) > 1 and matches[0].unit_price is not None:
            priced = [
                d
                for d in matches
                if d.unit_price is not None
                and _price_close(d.unit_price, Decimal(activity.unit_price))
            ]
            if priced:
                matches = priced
        lot_to_docs[lot.id] = matches
        for doc in matches:
            doc_to_lots.setdefault(doc.paperless_doc_id, []).append(lot.id)

    matched = 0
    ambiguous = 0
    unmatched = 0
    skipped = 0
    items: list[dict[str, Any]] = []

    for lot, activity in unlinked:
        matches = lot_to_docs.get(lot.id) or []
        if not matches:
            unmatched += 1
            items.append(
                {
                    "lot_id": lot.id,
                    "activity_id": activity.id,
                    "outcome": "unmatched",
                    "reason": "no document with same type/ISIN/date/quantity",
                }
            )
            continue

        unique_docs = [
            doc
            for doc in matches
            if len(doc_to_lots.get(doc.paperless_doc_id) or []) == 1
        ]
        if len(unique_docs) == 1:
            detail = _attach_lot_link(
                session, doc=unique_docs[0], lot=lot, activity=activity
            )
            linked_docs.add(unique_docs[0].paperless_doc_id)
            linked_activity_ids.add(activity.id)
            linked_lot_ids.add(lot.id)
            matched += 1
            items.append(detail)
            continue

        ambiguous += 1
        items.append(
            {
                "lot_id": lot.id,
                "activity_id": activity.id,
                "outcome": "ambiguous",
                "reason": f"{len(matches)} candidate documents",
                "paperless_doc_ids": [d.paperless_doc_id for d in matches],
            }
        )

    session.flush()
    return MatchResult(
        scanned=len(unlinked),
        matched=matched,
        ambiguous=ambiguous,
        unmatched=unmatched,
        skipped=skipped,
        items=items,
    )


def parse_paperless_doc_ref(value: Any) -> int | None:
    """Parse a Paperless document id from an int, digits, or document URL."""
    if value is None or value == "":
        return None
    if isinstance(value, int):
        return value if value > 0 else None
    text = str(value).strip()
    if text.isdigit():
        return int(text)
    # .../documents/123/ or .../documents/123
    marker = "/documents/"
    if marker in text:
        tail = text.split(marker, 1)[1]
        digits = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            elif digits:
                break
        if digits:
            return int(digits)
    return None


def link_lot_to_document(
    session: Session,
    client: PaperlessClient,
    *,
    lot_id: int,
    paperless_doc_id: int | None = None,
    paperless_ref: str | int | None = None,
) -> dict[str, Any]:
    """Manually attach a Paperless document to a lot; mark staging imported if present."""
    doc_id = paperless_doc_id
    if doc_id is None:
        doc_id = parse_paperless_doc_ref(paperless_ref)
    if doc_id is None:
        raise ValueError("paperless_doc_id or document URL/id required")

    lot = session.get(Lot, lot_id)
    if lot is None:
        raise LookupError(f"Lot {lot_id} not found")
    activity = session.get(Activity, lot.activity_id)
    if activity is None:
        raise LookupError(f"Activity for lot {lot_id} not found")

    if lot.id in _linked_lot_ids(session) or activity.id in _linked_activity_ids(session):
        raise ValueError("Lot or activity already has a document link")
    if doc_id in _existing_doc_links(session):
        raise ValueError(f"Document {doc_id} is already linked")

    document = client.get_document(doc_id)
    role_map = resolve_role_field_map(session, client)
    ensure_required_roles(role_map)
    select_maps = select_option_maps_by_field_id(client.list_custom_fields())
    fields = extract_fields_by_roles(document, role_map, select_maps=select_maps)
    try:
        payload = build_staging_payload(document, fields)
    except (ValueError, TypeError, AttributeError):
        payload = {
            "paperless_doc_id": doc_id,
            "wp_typ": str(activity.type).upper(),
            "isin": activity.isin,
            "symbol": activity.symbol or activity.isin,
            "quantity": str(activity.quantity),
            "unit_price": str(activity.unit_price),
            "trade_date": activity.trade_date.isoformat(),
        }

    doc = _DocCandidate(
        paperless_doc_id=doc_id,
        wp_typ=str(payload.get("wp_typ") or activity.type).upper(),
        isin=str(payload.get("isin") or activity.isin or ""),
        trade_date=_as_date(payload.get("trade_date")) or activity.trade_date,
        quantity=_as_decimal(payload.get("quantity")) or Decimal(activity.quantity),
        unit_price=_as_decimal(payload.get("unit_price")),
        payload=payload,
        wkn=str(payload.get("wkn") or "").strip() or None,
    )
    detail = _attach_lot_link(
        session, doc=doc, lot=lot, activity=activity, link_type=LINK_TYPE_MANUAL
    )
    session.flush()
    return detail


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
    """Legacy: link open staging rows to existing activities when unique.

    Prefer ``match_lots_to_documents`` for historical linking.
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
    lookups = load_identifier_lookups(session)

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
        wkn = str(payload.get("wkn") or "").strip() or None
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

        candidates = _find_candidate_activities(
            activities,
            isin=isin,
            trade_date=trade_date,
            quantity=quantity,
            wp_typ=wp_typ,
            unit_price=unit_price,
            linked_activity_ids=linked_activity_ids,
            lookups=lookups,
            wkn=wkn,
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
