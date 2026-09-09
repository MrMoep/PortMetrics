"""Staging queue: Paperless docs → review → Ghostfolio import."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from portmetrics.config import settings
from portmetrics.db.models import DocumentLink, StagingImport
from portmetrics.ghostfolio.client import GhostfolioClient, GhostfolioError
from portmetrics.paperless.client import (
    CUSTOM_FIELD_NAMES,
    PaperlessClient,
    PaperlessError,
    extract_custom_fields,
)

PAPERLESS_SOURCE = "paperless"
STATUS_PENDING = "pending"
STATUS_IMPORTED = "imported"
STATUS_REJECTED = "rejected"
STATUS_ERROR = "error"


@dataclass(frozen=True)
class StagingSyncResult:
    scanned: int
    upserted: int
    skipped: int


def _as_decimal(value: Any, default: str = "0") -> Decimal:
    if value is None or value == "":
        return Decimal(default)
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal: {value!r}") from exc


def _as_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if "T" in text:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    return date.fromisoformat(text[:10])


def build_staging_payload(
    document: dict[str, Any],
    fields: dict[str, Any],
) -> dict[str, Any]:
    isin = (fields.get("isin") or "").strip() or None
    symbol = (fields.get("symbol") or "").strip() or isin
    if not symbol:
        raise ValueError("Document missing symbol/isin custom field")
    wp_typ = (fields.get("wp_typ") or "BUY").strip().upper()
    if wp_typ not in {"BUY", "SELL", "DIVIDEND", "FEE", "INTEREST"}:
        raise ValueError(f"Unsupported wp_typ: {wp_typ}")
    handelsdatum = fields.get("handelsdatum")
    if not handelsdatum:
        raise ValueError("Document missing handelsdatum")
    return {
        "paperless_doc_id": int(document["id"]),
        "title": document.get("title"),
        "wp_typ": wp_typ,
        "isin": isin,
        "symbol": symbol,
        "quantity": str(_as_decimal(fields.get("stueckzahl"))),
        "unit_price": str(_as_decimal(fields.get("kurs"))),
        "fee": str(_as_decimal(fields.get("gebuehr"), "0")),
        "currency": (fields.get("waehrung") or "EUR").strip().upper()[:3],
        "trade_date": _as_date(handelsdatum).isoformat(),
        "gf_import_status": fields.get("gf_import_status"),
        "gf_activity_id": fields.get("gf_activity_id"),
        "raw_fields": {name: fields.get(name) for name in CUSTOM_FIELD_NAMES},
    }


def sync_paperless_documents(
    session: Session,
    client: PaperlessClient,
    *,
    tag: str | None = None,
) -> StagingSyncResult:
    field_map = client.custom_field_map()
    required = ("isin", "stueckzahl", "kurs", "handelsdatum")
    missing = [name for name in required if name not in field_map]
    if missing:
        raise PaperlessError("Paperless custom fields missing: " + ", ".join(missing))

    documents = client.list_documents(tag=tag)
    upserted = 0
    skipped = 0
    for document in documents:
        fields = extract_custom_fields(document, field_map)
        status_hint = str(fields.get("gf_import_status") or "").strip().lower()
        if status_hint == STATUS_IMPORTED and fields.get("gf_activity_id"):
            skipped += 1
            continue
        if not fields.get("isin") and not fields.get("symbol"):
            skipped += 1
            continue
        try:
            payload = build_staging_payload(document, fields)
        except ValueError:
            skipped += 1
            continue

        doc_id = int(document["id"])
        row = session.scalar(
            select(StagingImport).where(StagingImport.paperless_doc_id == doc_id)
        )
        if row and row.status == STATUS_IMPORTED:
            skipped += 1
            continue
        if row is None:
            row = StagingImport(paperless_doc_id=doc_id, payload=payload, status=STATUS_PENDING)
            session.add(row)
        else:
            row.payload = payload
            if row.status == STATUS_REJECTED:
                pass
            elif row.status != STATUS_IMPORTED:
                row.status = STATUS_PENDING
                row.error = None
        upserted += 1
    session.flush()
    return StagingSyncResult(scanned=len(documents), upserted=upserted, skipped=skipped)


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
    return {
        "id": row.id,
        "paperless_doc_id": row.paperless_doc_id,
        "status": row.status,
        "payload": row.payload,
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
    paperless: PaperlessClient | None = None,
    *,
    account_id: str | None = None,
) -> dict[str, Any]:
    row = session.get(StagingImport, staging_id)
    if row is None:
        raise LookupError(f"staging import {staging_id} not found")
    if row.status == STATUS_IMPORTED:
        return _serialize_staging(row)

    payload = dict(row.payload or {})
    resolved_account = account_id or settings.ghostfolio_default_account_id
    activity = {
        "currency": payload["currency"],
        "dataSource": settings.ghostfolio_data_source,
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

    if paperless is not None:
        try:
            paperless.patch_document_custom_fields(
                row.paperless_doc_id,
                {
                    "gf_import_status": STATUS_IMPORTED,
                    "gf_activity_id": str(activity_id) if activity_id else "",
                },
            )
        except PaperlessError as exc:
            row.error = f"imported but paperless update failed: {exc}"

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
