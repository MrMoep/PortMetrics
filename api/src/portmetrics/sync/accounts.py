"""Mirror Ghostfolio accounts (depots / Konten) into PostgreSQL."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from portmetrics.db.models import Account, SyncState
from portmetrics.ghostfolio.client import GhostfolioAccount, GhostfolioClient

GHOSTFOLIO_ACCOUNTS_SOURCE = "ghostfolio_accounts"


@dataclass(frozen=True)
class AccountSyncResult:
    fetched: int
    upserted: int
    deleted: int


def upsert_accounts(session: Session, accounts: list[GhostfolioAccount]) -> int:
    if not accounts:
        return 0

    now = datetime.now(UTC)
    rows = [
        {
            "id": item.id,
            "name": item.name,
            "currency": (item.currency or "EUR").upper()[:3],
            "balance": Decimal(item.balance or 0),
            "comment": item.comment,
            "platform_id": item.platform_id,
            "platform_name": item.platform_name,
            "synced_at": now,
        }
        for item in accounts
    ]

    stmt = insert(Account).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Account.id],
        set_={
            "name": stmt.excluded.name,
            "currency": stmt.excluded.currency,
            "balance": stmt.excluded.balance,
            "comment": stmt.excluded.comment,
            "platform_id": stmt.excluded.platform_id,
            "platform_name": stmt.excluded.platform_name,
            "synced_at": stmt.excluded.synced_at,
        },
    )
    session.execute(stmt)
    return len(rows)


def prune_orphan_accounts(session: Session, *, remote_ids: set[str]) -> int:
    """Delete local accounts missing from Ghostfolio."""
    if not remote_ids:
        # Guard: empty remote list with local rows → skip wipe (same as activities).
        has_local = session.scalar(select(Account.id).limit(1)) is not None
        if has_local:
            return 0
        return 0

    orphans = session.scalars(select(Account).where(Account.id.notin_(remote_ids))).all()
    if not orphans:
        return 0
    orphan_ids = [row.id for row in orphans]
    session.execute(delete(Account).where(Account.id.in_(orphan_ids)))
    session.flush()
    return len(orphan_ids)


def update_accounts_sync_state(
    session: Session,
    *,
    fetched: int,
    upserted: int,
    deleted: int,
) -> SyncState:
    existing = session.scalar(
        select(SyncState).where(SyncState.source == GHOSTFOLIO_ACCOUNTS_SOURCE)
    )
    now = datetime.now(UTC)
    meta = {"fetched": fetched, "upserted": upserted, "deleted": deleted}
    if existing is None:
        existing = SyncState(
            source=GHOSTFOLIO_ACCOUNTS_SOURCE,
            last_sync_at=now,
            meta=meta,
        )
        session.add(existing)
    else:
        existing.last_sync_at = now
        existing.meta = meta
    return existing


def list_accounts(session: Session) -> list[dict]:
    rows = session.scalars(select(Account).order_by(Account.name.asc(), Account.id.asc())).all()
    return [
        {
            "id": row.id,
            "name": row.name,
            "currency": row.currency,
            "balance": str(row.balance),
            "comment": row.comment,
            "platform_id": row.platform_id,
            "platform_name": row.platform_name,
            "synced_at": row.synced_at.isoformat() if row.synced_at else None,
        }
        for row in rows
    ]


def sync_ghostfolio_accounts(session: Session, client: GhostfolioClient) -> AccountSyncResult:
    accounts = client.list_accounts()
    upserted = upsert_accounts(session, accounts)
    deleted = prune_orphan_accounts(session, remote_ids={a.id for a in accounts})
    update_accounts_sync_state(
        session,
        fetched=len(accounts),
        upserted=upserted,
        deleted=deleted,
    )
    return AccountSyncResult(fetched=len(accounts), upserted=upserted, deleted=deleted)
