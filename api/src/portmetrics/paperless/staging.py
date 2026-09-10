"""Staging queue: Paperless docs → review → Ghostfolio import."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from portmetrics.db.models import DocumentLink, StagingImport
from portmetrics.ghostfolio.client import GhostfolioClient, GhostfolioError
from portmetrics.paperless.client import PaperlessClient
from portmetrics.paperless.mapping import (
    DEFAULT_ROLE_TO_NAME,
    FIELD_ROLES,
    LEGACY_EXTRA_NAMES,
    ensure_required_roles,
    extract_fields_by_roles,
    get_paperless_settings,
    resolve_role_field_map,
)

PAPERLESS_SOURCE = "paperless"
STATUS_PENDING = "pending"
STATUS_IMPORTED = "imported"
STATUS_REJECTED = "rejected"
STATUS_ERROR = "error"

IMPORTABLE_TYPES = frozenset({"BUY", "SELL", "DIVIDEND", "FEE", "INTEREST"})
STAGING_TYPES = IMPORTABLE_TYPES | {"OTHER"}
TYPES_WITHOUT_QTY = frozenset({"FEE", "INTEREST", "OTHER"})

_MONETARY_PREFIX = re.compile(
    r"^([A-Za-z]{3})\s*([+-]?\d+(?:[.,]\d+)?)\s*$"
)
_MONETARY_SUFFIX = re.compile(
    r"^([+-]?\d+(?:[.,]\d+)?)\s*([A-Za-z]{3})\s*$"
)


@dataclass(frozen=True)
class StagingSyncResult:
    scanned: int
    upserted: int
    skipped: int


@dataclass(frozen=True)
class DocumentIngestResult:
    document_id: int
    action: str  # upserted | skipped | error
    reason: str | None = None
    staging_id: int | None = None


def _as_decimal(value: Any, default: str | None = "0") -> Decimal:
    if value is None or value == "":
        if default is None:
            raise ValueError("Missing decimal value")
        return Decimal(default)
    amount, _ = parse_monetary(value)
    return amount


def parse_monetary(value: Any) -> tuple[Decimal, str | None]:
    """Parse plain number or Paperless monetary string (`EUR152.34` / `152.34 EUR`)."""
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value)), None
    if isinstance(value, dict):
        amount = value.get("amount", value.get("value"))
        currency = value.get("currency") or value.get("currency_code")
        if amount is None:
            raise ValueError(f"Invalid monetary object: {value!r}")
        parsed, _ = parse_monetary(amount)
        code = str(currency).strip().upper()[:3] if currency else None
        return parsed, code

    text = str(value).strip()
    if not text:
        raise ValueError("Empty monetary value")

    match = _MONETARY_PREFIX.match(text)
    if match:
        return Decimal(match.group(2).replace(",", ".")), match.group(1).upper()

    match = _MONETARY_SUFFIX.match(text)
    if match:
        return Decimal(match.group(1).replace(",", ".")), match.group(2).upper()

    try:
        return Decimal(text.replace(",", ".")), None
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal: {value!r}") from exc


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text[:10])


def document_trade_date(document: dict[str, Any]) -> date:
    """Paperless document date (`created`) used as Handelsdatum."""
    raw = document.get("created") or document.get("created_date")
    if not raw:
        raise ValueError("Document missing created date")
    return _as_date(raw)


def build_staging_payload(
    document: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    """Build staging payload from role-keyed fields (or legacy name-keyed)."""
    roles = _normalize_to_roles(fields)
    wp_typ = (roles.get("type") or "BUY").strip().upper()
    if wp_typ not in STAGING_TYPES:
        raise ValueError(f"Unsupported wp_typ: {wp_typ}")

    isin = (roles.get("isin") or "").strip() or None
    wkn = (roles.get("wkn") or "").strip() or None
    # Ghostfolio keys on symbol; we use ISIN (no separate ticker field).
    symbol = isin or wkn
    if wp_typ != "OTHER" and not symbol:
        raise ValueError("Document missing isin custom field")
    if not symbol:
        symbol = "OTHER"

    unit_raw = roles.get("unit_price")
    fee_raw = roles.get("fee")
    currency: str | None = None
    if unit_raw is not None and unit_raw != "":
        unit_price, currency = parse_monetary(unit_raw)
    elif wp_typ in TYPES_WITHOUT_QTY:
        unit_price = Decimal("0")
    else:
        raise ValueError("Document missing unit_price (Kurs)")

    if fee_raw is not None and fee_raw != "":
        fee, fee_ccy = parse_monetary(fee_raw)
        if currency is None and fee_ccy:
            currency = fee_ccy
    else:
        fee = Decimal("0")

    legacy_ccy = roles.get("currency")
    if currency is None and legacy_ccy:
        currency = str(legacy_ccy).strip().upper()[:3] or None
    if currency is None:
        currency = "EUR"

    qty_raw = roles.get("quantity")
    if qty_raw is None or qty_raw == "":
        if wp_typ in TYPES_WITHOUT_QTY:
            quantity = Decimal("1")
        else:
            raise ValueError("Document missing quantity (Nennwert)")
    else:
        quantity = _as_decimal(qty_raw, default=None)

    trade_raw = roles.get("trade_date")
    if trade_raw:
        trade_date = _as_date(trade_raw)
    else:
        trade_date = document_trade_date(document)

    return {
        "paperless_doc_id": int(document["id"]),
        "title": document.get("title"),
        "wp_typ": wp_typ,
        "isin": isin,
        "wkn": wkn,
        "symbol": symbol,
        "quantity": str(quantity),
        "unit_price": str(unit_price),
        "fee": str(fee),
        "currency": currency,
        "trade_date": trade_date.isoformat(),
        "importable": wp_typ in IMPORTABLE_TYPES,
        "raw_fields": {role: roles.get(role) for role in FIELD_ROLES},
    }


def _normalize_to_roles(fields: dict[str, Any]) -> dict[str, Any]:
    """Accept role keys or legacy Paperless names."""
    # Unambiguous role keys (isin/wkn exist in both naming schemes).
    role_only = {"type", "quantity", "unit_price", "fee", "trade_date", "currency"}
    legacy_only = {
        "wp_typ",
        "stueckzahl",
        "kurs",
        "gebuehr",
        "handelsdatum",
        "waehrung",
        "gf_import_status",
        "gf_activity_id",
    }
    if any(key in fields for key in role_only):
        out = {role: fields.get(role) for role in FIELD_ROLES}
        for legacy_role in ("trade_date", "currency", "import_status", "activity_id", "symbol"):
            if legacy_role in fields:
                out[legacy_role] = fields.get(legacy_role)
        return out
    if any(key in fields for key in legacy_only):
        out = {role: fields.get(name) for role, name in DEFAULT_ROLE_TO_NAME.items()}
        for role, name in LEGACY_EXTRA_NAMES.items():
            out[role] = fields.get(name)
        return out
    return {role: fields.get(role) for role in FIELD_ROLES}


def _upsert_document_from_fields(
    session: Session,
    document: dict[str, Any],
    fields: dict[str, Any],
) -> DocumentIngestResult:
    doc_id = int(document["id"])
    # Legacy Paperless write-back: skip if previously marked imported.
    status_hint = str(fields.get("import_status") or "").strip().lower()
    if status_hint == STATUS_IMPORTED and fields.get("activity_id"):
        return DocumentIngestResult(doc_id, "skipped", "already imported in Paperless")

    roles = _normalize_to_roles(fields)
    wp_typ = (str(roles.get("type") or "BUY")).strip().upper()
    if wp_typ != "OTHER" and not roles.get("isin") and not roles.get("symbol"):
        return DocumentIngestResult(doc_id, "skipped", "missing isin")

    try:
        payload = build_staging_payload(document, fields)
    except ValueError as exc:
        return DocumentIngestResult(doc_id, "skipped", str(exc))

    row = session.scalar(select(StagingImport).where(StagingImport.paperless_doc_id == doc_id))
    if row and row.status == STATUS_IMPORTED:
        return DocumentIngestResult(doc_id, "skipped", "already imported locally", row.id)
    if row is None:
        row = StagingImport(paperless_doc_id=doc_id, payload=payload, status=STATUS_PENDING)
        session.add(row)
        session.flush()
    else:
        row.payload = payload
        if row.status == STATUS_REJECTED:
            pass
        elif row.status != STATUS_IMPORTED:
            row.status = STATUS_PENDING
            row.error = None
        session.flush()
    return DocumentIngestResult(doc_id, "upserted", staging_id=row.id)


def sync_paperless_documents(
    session: Session,
    client: PaperlessClient,
    *,
    tag: str | None = None,
) -> StagingSyncResult:
    role_map = resolve_role_field_map(session, client)
    ensure_required_roles(role_map)
    paperless_settings = get_paperless_settings(session)
    resolved_tag = tag if tag is not None else paperless_settings.get("tag")

    documents = client.list_documents(tag=resolved_tag)
    upserted = 0
    skipped = 0
    for document in documents:
        fields = extract_fields_by_roles(document, role_map)
        result = _upsert_document_from_fields(session, document, fields)
        if result.action == "upserted":
            upserted += 1
        else:
            skipped += 1
    session.flush()
    return StagingSyncResult(scanned=len(documents), upserted=upserted, skipped=skipped)


def ingest_paperless_document(
    session: Session,
    client: PaperlessClient,
    document_id: int,
) -> DocumentIngestResult:
    """Fetch one Paperless document and upsert into staging_imports."""
    role_map = resolve_role_field_map(session, client)
    ensure_required_roles(role_map)
    document = client.get_document(document_id)
    fields = extract_fields_by_roles(document, role_map)
    result = _upsert_document_from_fields(session, document, fields)
    session.flush()
    return result


def parse_paperless_document_id(payload: Any) -> int | None:
    """Extract document id from webhook JSON / form-like payloads."""
    if payload is None:
        return None
    if isinstance(payload, int):
        return payload
    if isinstance(payload, str):
        text = payload.strip()
        if text.isdigit():
            return int(text)
        return _document_id_from_url(text)
    if not isinstance(payload, dict):
        return None

    for key in ("document_id", "doc_id", "id", "DOCUMENT_ID"):
        raw = payload.get(key)
        if raw is None or raw == "":
            continue
        try:
            return int(raw)
        except (TypeError, ValueError):
            parsed = _document_id_from_url(str(raw))
            if parsed is not None:
                return parsed

    for key in ("doc_url", "document_url", "url"):
        parsed = _document_id_from_url(str(payload.get(key) or ""))
        if parsed is not None:
            return parsed
    return None


def _document_id_from_url(url: str) -> int | None:
    match = re.search(r"/documents/(\d+)", url)
    if match:
        return int(match.group(1))
    match = re.search(r"/api/documents/(\d+)", url)
    if match:
        return int(match.group(1))
    return None


def list_staging(
    session: Session,
    *,
    status: str | None = None,
) -> list[dict[str, Any]]:
    stmt = select(StagingImport).order_by(StagingImport.id.desc())
    if status:
        stmt = stmt.where(StagingImport.status == status)
    rows = session.scalars(stmt).all()
    return [_serialize_staging(row) for row in rows]


def _serialize_staging(row: StagingImport) -> dict[str, Any]:
    payload = dict(row.payload or {})
    wp_typ = str(payload.get("wp_typ") or "").upper()
    payload.setdefault("importable", wp_typ in IMPORTABLE_TYPES)
    return {
        "id": row.id,
        "paperless_doc_id": row.paperless_doc_id,
        "status": row.status,
        "payload": payload,
        "gf_activity_id": str(row.gf_activity_id) if row.gf_activity_id else None,
        "error": row.error,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def reject_staging(session: Session, staging_id: int) -> dict[str, Any]:
    row = session.get(StagingImport, staging_id)
    if row is None:
        raise LookupError(f"staging import {staging_id} not found")
    row.status = STATUS_REJECTED
    row.error = None
    session.flush()
    return _serialize_staging(row)


def confirm_staging(
    session: Session,
    staging_id: int,
    ghostfolio: GhostfolioClient,
    paperless: PaperlessClient | None = None,  # noqa: ARG001 — kept for call-site compat
    *,
    account_id: str | None = None,
) -> dict[str, Any]:
    row = session.get(StagingImport, staging_id)
    if row is None:
        raise LookupError(f"staging import {staging_id} not found")
    if row.status == STATUS_IMPORTED:
        return _serialize_staging(row)

    paperless_settings = get_paperless_settings(session)
    payload = dict(row.payload or {})
    wp_typ = str(payload.get("wp_typ") or "").upper()
    if wp_typ not in IMPORTABLE_TYPES:
        raise ValueError(
            f"Cannot import type {wp_typ or 'UNKNOWN'} — "
            "set Typ to BUY/SELL/DIVIDEND/FEE/INTEREST in Paperless and re-sync"
        )

    resolved_account = (
        account_id
        or paperless_settings.get("ghostfolio_default_account_id")
    )
    data_source = paperless_settings.get("ghostfolio_data_source") or "YAHOO"
    activity = {
        "currency": payload["currency"],
        "dataSource": data_source,
        "date": f"{payload['trade_date']}T00:00:00.000Z",
        "fee": float(payload["fee"]),
        "quantity": float(payload["quantity"]),
        "symbol": payload["symbol"],
        "type": payload["wp_typ"],
        "unitPrice": float(payload["unit_price"]),
        "comment": f"paperless:{row.paperless_doc_id}",
    }
    if resolved_account:
        activity["accountId"] = resolved_account
    if payload.get("isin"):
        # Ghostfolio import primarily keys on symbol; keep ISIN in comment for audit.
        activity["comment"] = f"paperless:{row.paperless_doc_id} isin={payload['isin']}"
    if payload.get("wkn"):
        activity["comment"] = f"{activity['comment']} wkn={payload['wkn']}"

    try:
        imported = ghostfolio.import_activities([activity])
    except GhostfolioError as exc:
        row.status = STATUS_ERROR
        row.error = str(exc)
        session.flush()
        raise

    activity_id = _extract_activity_id(imported)
    row.status = STATUS_IMPORTED
    row.error = None
    if activity_id:
        row.gf_activity_id = activity_id
        local_activity_id = _local_activity_pk(session, activity_id)
        session.add(
            DocumentLink(
                paperless_doc_id=row.paperless_doc_id,
                activity_id=local_activity_id,
                lot_id=None,
                link_type="source",
            )
        )

    session.flush()
    return _serialize_staging(row)


def _extract_activity_id(imported: dict[str, Any]) -> UUID | None:
    activities = imported.get("activities") or []
    if not activities:
        return None
    raw = activities[0].get("id")
    if not raw:
        return None
    return UUID(str(raw))


def _local_activity_pk(session: Session, gf_activity_id: UUID) -> int | None:
    from portmetrics.db.models import Activity

    row = session.scalar(select(Activity).where(Activity.gf_activity_id == gf_activity_id))
    return row.id if row else None
