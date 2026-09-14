"""Internal depot transfers (PortMetrics-owned, not Ghostfolio)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from portmetrics.db.models import DepotTransfer
from portmetrics.fifo.engine import FifoError, normalize_account_id
from portmetrics.fifo.service import rebuild_lots


def serialize_transfer(row: DepotTransfer) -> dict:
    return {
        "id": row.id,
        "from_account_id": row.from_account_id,
        "to_account_id": row.to_account_id,
        "isin": row.isin,
        "quantity": str(row.quantity),
        "transfer_date": row.transfer_date.isoformat(),
        "comment": row.comment,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def list_transfers(session: Session) -> list[dict]:
    rows = session.scalars(
        select(DepotTransfer).order_by(
            DepotTransfer.transfer_date.desc(), DepotTransfer.id.desc()
        )
    ).all()
    return [serialize_transfer(row) for row in rows]


def create_transfer(
    session: Session,
    *,
    from_account_id: str,
    to_account_id: str,
    isin: str,
    quantity: Decimal,
    transfer_date: date,
    comment: str | None = None,
) -> dict:
    src = normalize_account_id(from_account_id)
    dst = normalize_account_id(to_account_id)
    if src == dst:
        raise FifoError("Transfer requires distinct source and destination accounts")
    if quantity <= 0:
        raise FifoError("Transfer quantity must be positive")
    asset = (isin or "").strip()
    if not asset:
        raise FifoError("Transfer requires an asset key (isin)")

    row = DepotTransfer(
        from_account_id=src,
        to_account_id=dst,
        isin=asset,
        quantity=quantity,
        transfer_date=transfer_date,
        comment=comment,
    )
    session.add(row)
    session.flush()
    rebuild_lots(session)
    session.refresh(row)
    return serialize_transfer(row)


def delete_transfer(session: Session, transfer_id: int) -> bool:
    row = session.get(DepotTransfer, transfer_id)
    if row is None:
        return False
    session.delete(row)
    session.flush()
    rebuild_lots(session)
    return True
