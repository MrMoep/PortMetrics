from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from portmetrics.db.models import (
    Activity,
    DocumentLink,
    Lot,
    LotConsumption,
    StagingImport,
    SyncState,
)
from portmetrics.ghostfolio.client import GhostfolioActivity, GhostfolioClient, trade_date_of
from portmetrics.paperless.staging import STATUS_IMPORTED, STATUS_PENDING

GHOSTFOLIO_SOURCE = "ghostfolio"
# Matches activities.type CHECK constraint (Ghostfolio also has LIABILITY).
SUPPORTED_ACTIVITY_TYPES = frozenset({"BUY", "SELL", "DIVIDEND", "FEE", "INTEREST"})


@dataclass(frozen=True)
class SyncResult:
    fetched: int
    upserted: int
    deleted: int
    checksum: str
    prune_skipped: bool = False


def _checksum(activities: list[GhostfolioActivity]) -> str:
    digest = sha256()
    for item in sorted(activities, key=lambda a: str(a.id)):
        digest.update(str(item.id).encode())
        digest.update(str(item.quantity).encode())
        digest.update(str(item.unit_price).encode())
        digest.update(item.type.encode())
    return digest.hexdigest()


def upsert_activities(session: Session, activities: list[GhostfolioActivity]) -> int:
    if not activities:
        return 0

    rows = [
        {
            "gf_activity_id": item.id,
            "account_id": item.account_id,
            "isin": item.isin,
            "symbol": item.symbol,
            "type": item.type.upper(),
            "quantity": Decimal(item.quantity),
            "unit_price": Decimal(item.unit_price),
            "fee": Decimal(item.fee or 0),
            "currency": item.currency.upper()[:3],
            "trade_date": trade_date_of(item),
            "comment": item.comment,
            "synced_at": datetime.now(UTC),
        }
        for item in activities
    ]

    stmt = insert(Activity).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Activity.gf_activity_id],
        set_={
            "account_id": stmt.excluded.account_id,
            "isin": stmt.excluded.isin,
            "symbol": stmt.excluded.symbol,
            "type": stmt.excluded.type,
            "quantity": stmt.excluded.quantity,
            "unit_price": stmt.excluded.unit_price,
            "fee": stmt.excluded.fee,
            "currency": stmt.excluded.currency,
            "trade_date": stmt.excluded.trade_date,
            "comment": stmt.excluded.comment,
            "synced_at": stmt.excluded.synced_at,
        },
    )
    session.execute(stmt)
    return len(rows)


def prune_orphan_activities(
    session: Session,
    *,
    remote_gf_ids: set[UUID],
    fetched: int,
) -> tuple[int, bool]:
    """Delete local activities missing from Ghostfolio.

    Guardrail: if Ghostfolio returned an empty activity list but we still have
    local rows, skip prune (avoids wiping the mirror on a bad/empty API reply).
    Legitimate "delete everything in GF" therefore needs at least one remaining
    remote activity, or a later explicit cleanup.

    Returns ``(deleted_count, prune_skipped)``.
    """
    local_count = session.scalar(select(Activity.id).limit(1)) is not None
    if fetched == 0 and local_count:
        return 0, True

    orphans = session.scalars(
        select(Activity).where(Activity.gf_activity_id.notin_(remote_gf_ids))
        if remote_gf_ids
        else select(Activity)
    ).all()
    if not orphans:
        return 0, False

    orphan_pks = [row.id for row in orphans]
    orphan_gf_ids = [row.gf_activity_id for row in orphans]

    lot_ids = list(
        session.scalars(select(Lot.id).where(Lot.activity_id.in_(orphan_pks))).all()
    )

    link_stmt = select(DocumentLink).where(DocumentLink.activity_id.in_(orphan_pks))
    if lot_ids:
        link_stmt = select(DocumentLink).where(
            DocumentLink.activity_id.in_(orphan_pks)
            | DocumentLink.lot_id.in_(lot_ids)
        )
    linked_docs = session.scalars(link_stmt).all()
    doc_ids_from_links = {link.paperless_doc_id for link in linked_docs}

    # Staging reset before dropping links (imported → pending for re-confirm).
    staging_filter = StagingImport.gf_activity_id.in_(orphan_gf_ids)
    if doc_ids_from_links:
        staging_filter = staging_filter | StagingImport.paperless_doc_id.in_(
            doc_ids_from_links
        )
    staging_rows = session.scalars(select(StagingImport).where(staging_filter)).all()
    for row in staging_rows:
        if row.status == STATUS_IMPORTED:
            row.status = STATUS_PENDING
            row.gf_activity_id = None
            row.error = None

    for link in linked_docs:
        session.delete(link)

    if lot_ids:
        session.execute(
            delete(LotConsumption).where(
                LotConsumption.sell_activity_id.in_(orphan_pks)
                | LotConsumption.lot_id.in_(lot_ids)
            )
        )
    else:
        session.execute(
            delete(LotConsumption).where(
                LotConsumption.sell_activity_id.in_(orphan_pks)
            )
        )

    session.execute(delete(Lot).where(Lot.activity_id.in_(orphan_pks)))
    session.execute(delete(Activity).where(Activity.id.in_(orphan_pks)))

    session.flush()
    return len(orphan_pks), False


def update_sync_state(
    session: Session,
    *,
    source: str,
    checksum: str,
    fetched: int,
    deleted: int = 0,
    prune_skipped: bool = False,
) -> SyncState:
    existing = session.scalar(select(SyncState).where(SyncState.source == source))
    now = datetime.now(UTC)
    meta = {
        "fetched": fetched,
        "deleted": deleted,
        "prune_skipped": prune_skipped,
    }
    if existing is None:
        existing = SyncState(
            source=source,
            last_sync_at=now,
            checksum=checksum,
            meta=meta,
        )
        session.add(existing)
    else:
        existing.last_sync_at = now
        existing.checksum = checksum
        existing.meta = meta
    return existing


def sync_ghostfolio_activities(session: Session, client: GhostfolioClient) -> SyncResult:
    fetched = client.list_activities()
    activities = [a for a in fetched if a.type.upper() in SUPPORTED_ACTIVITY_TYPES]
    checksum = _checksum(activities)
    upserted = upsert_activities(session, activities)
    remote_ids = {item.id for item in activities}
    deleted, prune_skipped = prune_orphan_activities(
        session,
        remote_gf_ids=remote_ids,
        fetched=len(fetched),
    )
    update_sync_state(
        session,
        source=GHOSTFOLIO_SOURCE,
        checksum=checksum,
        fetched=len(fetched),
        deleted=deleted,
        prune_skipped=prune_skipped,
    )
    return SyncResult(
        fetched=len(fetched),
        upserted=upserted,
        deleted=deleted,
        checksum=checksum,
        prune_skipped=prune_skipped,
    )
