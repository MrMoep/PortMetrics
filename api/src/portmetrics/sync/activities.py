from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from portmetrics.db.models import Activity, SyncState
from portmetrics.ghostfolio.client import GhostfolioActivity, GhostfolioClient, trade_date_of

GHOSTFOLIO_SOURCE = "ghostfolio"


@dataclass(frozen=True)
class SyncResult:
    fetched: int
    upserted: int
    checksum: str


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


def update_sync_state(
    session: Session,
    *,
    source: str,
    checksum: str,
    fetched: int,
) -> SyncState:
    existing = session.scalar(select(SyncState).where(SyncState.source == source))
    now = datetime.now(UTC)
    if existing is None:
        existing = SyncState(
            source=source,
            last_sync_at=now,
            checksum=checksum,
            meta={"fetched": fetched},
        )
        session.add(existing)
    else:
        existing.last_sync_at = now
        existing.checksum = checksum
        existing.meta = {"fetched": fetched}
    return existing


def sync_ghostfolio_activities(session: Session, client: GhostfolioClient) -> SyncResult:
    activities = client.list_activities()
    checksum = _checksum(activities)
    upserted = upsert_activities(session, activities)
    update_sync_state(
        session,
        source=GHOSTFOLIO_SOURCE,
        checksum=checksum,
        fetched=len(activities),
    )
    return SyncResult(fetched=len(activities), upserted=upserted, checksum=checksum)
