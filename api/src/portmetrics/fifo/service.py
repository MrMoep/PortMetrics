from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from portmetrics.assets.identifiers import enrich_asset_fields, paperless_doc_map, wkn_map
from portmetrics.db.models import (
    Activity,
    DocumentLink,
    Lot,
    LotConsumption,
    LotStatus,
    PriceSnapshot,
)
from portmetrics.fifo.engine import (
    FifoError,
    LotState,
    SellResult,
    apply_sell,
    create_lot_from_buy,
    estimate_tax,
)
from portmetrics.settings.portfolio import get_portfolio_settings

_PAPERLESS_COMMENT_RE = re.compile(r"paperless:(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class RebuildResult:
    lots_created: int
    consumptions: int
    activities_processed: int


def asset_key_for(activity: Activity) -> str:
    return activity.isin or activity.symbol


def rebuild_lots(session: Session) -> RebuildResult:
    """Full rebuild of lots/consumptions from activities (deterministic)."""
    session.execute(delete(LotConsumption))
    session.execute(delete(Lot))
    session.flush()

    activities = session.scalars(
        select(Activity).order_by(Activity.trade_date.asc(), Activity.id.asc())
    ).all()

    open_lots: list[LotState] = []
    lot_rows: dict[int, Lot] = {}  # activity_id -> Lot ORM for open buys
    consumptions = 0

    for activity in activities:
        key = asset_key_for(activity)
        if activity.type == "BUY":
            state = create_lot_from_buy(
                activity_id=activity.id,
                asset_key=key,
                quantity=activity.quantity,
                unit_price=activity.unit_price,
                fee=activity.fee,
                trade_date=activity.trade_date,
            )
            row = Lot(
                activity_id=activity.id,
                isin=key,
                open_qty=state.open_qty,
                original_qty=state.original_qty,
                cost_basis=state.cost_basis,
                open_date=state.open_date,
                status=LotStatus.OPEN,
            )
            session.add(row)
            session.flush()
            state.id = row.id
            open_lots.append(state)
            lot_rows[activity.id] = row
        elif activity.type == "SELL":
            result = apply_sell(
                open_lots,
                asset_key=key,
                quantity=activity.quantity,
                unit_price=activity.unit_price,
                fee=activity.fee,
                trade_date=activity.trade_date,
            )
            for c in result.consumptions:
                # find lot row by activity_id of the buy
                buy_lot = lot_rows.get(c.lot_activity_id)
                if buy_lot is None:
                    raise FifoError(f"Missing lot for buy activity {c.lot_activity_id}")
                session.add(
                    LotConsumption(
                        sell_activity_id=activity.id,
                        lot_id=buy_lot.id,
                        qty_consumed=c.qty_consumed,
                        proceeds=c.proceeds,
                        realized_gain=c.realized_gain,
                    )
                )
                buy_lot.open_qty = next(
                    lot.open_qty for lot in open_lots if lot.activity_id == c.lot_activity_id
                )
                buy_lot.status = next(
                    lot.status for lot in open_lots if lot.activity_id == c.lot_activity_id
                )
                buy_lot.closed_at = next(
                    lot.closed_at for lot in open_lots if lot.activity_id == c.lot_activity_id
                )
                consumptions += 1
        # DIVIDEND/FEE/INTEREST ignored for lot tracking in v1

    session.flush()
    return RebuildResult(
        lots_created=len(lot_rows),
        consumptions=consumptions,
        activities_processed=len(activities),
    )


def latest_mark_price(session: Session, asset_key: str) -> Decimal | None:
    snap = session.scalar(
        select(PriceSnapshot)
        .where(PriceSnapshot.isin == asset_key)
        .order_by(PriceSnapshot.price_date.desc())
        .limit(1)
    )
    if snap is not None:
        return Decimal(snap.close_price)
    activity = session.scalar(
        select(Activity)
        .where((Activity.isin == asset_key) | (Activity.symbol == asset_key))
        .order_by(Activity.trade_date.desc(), Activity.id.desc())
        .limit(1)
    )
    if activity is None:
        return None
    return Decimal(activity.unit_price)


def _paperless_doc_from_comment(comment: str | None) -> int | None:
    if not comment:
        return None
    match = _PAPERLESS_COMMENT_RE.search(comment)
    return int(match.group(1)) if match else None


def _lot_paperless_docs(
    session: Session,
    lots: list[Lot],
    activities: dict[int, Activity],
) -> dict[int, int]:
    """Resolve paperless_doc_id per lot: DocumentLink → comment → asset map."""
    if not lots:
        return {}

    lot_ids = {lot.id for lot in lots}
    activity_ids = {lot.activity_id for lot in lots}
    by_lot: dict[int, int] = {}
    by_activity: dict[int, int] = {}

    links = session.scalars(
        select(DocumentLink).where(
            or_(
                DocumentLink.lot_id.in_(lot_ids),
                DocumentLink.activity_id.in_(activity_ids),
            )
        )
    ).all()
    for link in links:
        if link.lot_id is not None and link.lot_id in lot_ids:
            by_lot[link.lot_id] = int(link.paperless_doc_id)
        if link.activity_id is not None:
            by_activity[link.activity_id] = int(link.paperless_doc_id)

    doc_by_isin = paperless_doc_map(session)
    resolved: dict[int, int] = {}
    for lot in lots:
        doc_id = by_lot.get(lot.id) or by_activity.get(lot.activity_id)
        if doc_id is None:
            activity = activities.get(lot.activity_id)
            doc_id = _paperless_doc_from_comment(activity.comment if activity else None)
        if doc_id is None:
            activity = activities.get(lot.activity_id)
            for key in (
                activity.isin if activity else None,
                lot.isin,
            ):
                if key and key in doc_by_isin:
                    doc_id = doc_by_isin[key]
                    break
        if doc_id is not None:
            resolved[lot.id] = doc_id
    return resolved


def list_open_lots(
    session: Session,
    *,
    asset_key: str | None = None,
    mark_prices: dict[str, Decimal] | None = None,
) -> list[dict]:
    stmt = select(Lot).where(Lot.status.in_([LotStatus.OPEN, LotStatus.PARTIAL]))
    if asset_key:
        stmt = stmt.where(Lot.isin == asset_key)
    stmt = stmt.order_by(Lot.isin.asc(), Lot.open_date.asc(), Lot.id.asc())
    rows = session.scalars(stmt).all()
    activity_ids = {lot.activity_id for lot in rows}
    activities = {
        row.id: row
        for row in session.scalars(select(Activity).where(Activity.id.in_(activity_ids))).all()
    } if activity_ids else {}
    wkn_by_isin = wkn_map(session)
    paperless_by_lot = _lot_paperless_docs(session, rows, activities)
    preference = get_portfolio_settings(session)["asset_id_preference"]
    out: list[dict] = []
    for lot in rows:
        unit_cost = (
            Decimal(lot.cost_basis) / Decimal(lot.original_qty)
            if lot.original_qty
            else Decimal("0")
        )
        mark = None
        if mark_prices and lot.isin in mark_prices:
            mark = mark_prices[lot.isin]
        else:
            mark = latest_mark_price(session, lot.isin)
        market_value = (Decimal(lot.open_qty) * mark) if mark is not None else None
        invested_open = Decimal(lot.open_qty) * unit_cost
        unrealized = (market_value - invested_open) if market_value is not None else None
        unrealized_pct = (
            (unrealized / invested_open * Decimal("100"))
            if unrealized is not None and invested_open != 0
            else None
        )
        activity = activities.get(lot.activity_id)
        ids = enrich_asset_fields(
            asset_key=lot.isin,
            activity_isin=activity.isin if activity else None,
            symbol=activity.symbol if activity else None,
            wkn_by_isin=wkn_by_isin,
            preference=preference,
        )
        out.append(
            {
                "id": lot.id,
                "activity_id": lot.activity_id,
                "isin": lot.isin,
                "symbol": ids["symbol"],
                "wkn": ids["wkn"],
                "isin_code": ids["isin_code"],
                "display_id": ids["display_id"],
                "paperless_doc_id": paperless_by_lot.get(lot.id),
                "open_qty": str(lot.open_qty),
                "original_qty": str(lot.original_qty),
                "cost_basis": str(lot.cost_basis),
                "unit_cost": str(unit_cost.quantize(Decimal("0.00000001"))),
                "open_date": lot.open_date.isoformat(),
                "status": lot.status,
                "mark_price": str(mark) if mark is not None else None,
                "market_value": str(market_value) if market_value is not None else None,
                "unrealized_gain": str(unrealized) if unrealized is not None else None,
                "unrealized_gain_pct": (
                    str(unrealized_pct.quantize(Decimal("0.01")))
                    if unrealized_pct is not None
                    else None
                ),
            }
        )
    return out


def load_open_lot_states(session: Session, asset_key: str) -> list[LotState]:
    rows = session.scalars(
        select(Lot)
        .where(
            Lot.isin == asset_key,
            Lot.status.in_([LotStatus.OPEN, LotStatus.PARTIAL]),
        )
        .order_by(Lot.open_date.asc(), Lot.id.asc())
    ).all()
    return [
        LotState(
            id=row.id,
            activity_id=row.activity_id,
            asset_key=row.isin,
            open_qty=Decimal(row.open_qty),
            original_qty=Decimal(row.original_qty),
            cost_basis=Decimal(row.cost_basis),
            open_date=row.open_date,
            status=row.status,
            closed_at=row.closed_at,
        )
        for row in rows
    ]


def simulate_sell(
    session: Session,
    *,
    asset_key: str,
    quantity: Decimal,
    unit_price: Decimal | None = None,
    fee: Decimal = Decimal("0"),
    tax_rate: Decimal = Decimal("0.26375"),
) -> dict:
    mark = unit_price if unit_price is not None else latest_mark_price(session, asset_key)
    if mark is None:
        raise FifoError(f"No mark price available for {asset_key}")

    lots = load_open_lot_states(session, asset_key)
    # work on copies so DB lots are untouched
    working = [
        LotState(
            id=lot.id,
            activity_id=lot.activity_id,
            asset_key=lot.asset_key,
            open_qty=lot.open_qty,
            original_qty=lot.original_qty,
            cost_basis=lot.cost_basis,
            open_date=lot.open_date,
            status=lot.status,
        )
        for lot in lots
    ]
    result: SellResult = apply_sell(
        working,
        asset_key=asset_key,
        quantity=quantity,
        unit_price=mark,
        fee=fee,
        trade_date=date.today(),
    )
    tax = estimate_tax(result.realized_gain, tax_rate)
    return {
        "isin": asset_key,
        "quantity": str(quantity),
        "unit_price": str(mark),
        "fee": str(fee),
        "proceeds": str(result.proceeds),
        "realized_gain": str(result.realized_gain),
        "estimated_tax": str(tax),
        "tax_rate": str(tax_rate),
        "net_after_tax": str(result.realized_gain - tax),
        "lots": [
            {
                "lot_id": c.lot_id,
                "buy_activity_id": c.lot_activity_id,
                "open_date": c.lot_open_date.isoformat(),
                "qty_consumed": str(c.qty_consumed),
                "unit_cost": str(c.unit_cost),
                "proceeds": str(c.proceeds),
                "realized_gain": str(c.realized_gain),
            }
            for c in result.consumptions
        ],
    }
