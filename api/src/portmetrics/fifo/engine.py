from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal


class FifoError(ValueError):
    """Raised when FIFO cannot consume enough quantity."""


@dataclass
class LotState:
    activity_id: int
    asset_key: str
    open_qty: Decimal
    original_qty: Decimal
    cost_basis: Decimal
    open_date: date
    status: str = "OPEN"
    closed_at: date | None = None
    id: int | None = None

    @property
    def unit_cost(self) -> Decimal:
        if self.original_qty == 0:
            return Decimal("0")
        return self.cost_basis / self.original_qty


@dataclass
class Consumption:
    lot_activity_id: int
    lot_open_date: date
    qty_consumed: Decimal
    proceeds: Decimal
    realized_gain: Decimal
    unit_cost: Decimal
    lot_id: int | None = None


@dataclass
class SellResult:
    consumptions: list[Consumption] = field(default_factory=list)
    realized_gain: Decimal = Decimal("0")
    proceeds: Decimal = Decimal("0")
    qty_sold: Decimal = Decimal("0")


def create_lot_from_buy(
    *,
    activity_id: int,
    asset_key: str,
    quantity: Decimal,
    unit_price: Decimal,
    fee: Decimal,
    trade_date: date,
) -> LotState:
    qty = Decimal(quantity)
    fee_dec = Decimal(fee or 0)
    price = Decimal(unit_price)
    return LotState(
        activity_id=activity_id,
        asset_key=asset_key,
        open_qty=qty,
        original_qty=qty,
        cost_basis=qty * price + fee_dec,
        open_date=trade_date,
        status="OPEN",
    )


def apply_sell(
    lots: list[LotState],
    *,
    asset_key: str,
    quantity: Decimal,
    unit_price: Decimal,
    fee: Decimal = Decimal("0"),
    trade_date: date | None = None,
) -> SellResult:
    """Consume oldest open lots first (FIFO). Mutates `lots` in place."""
    remaining = Decimal(quantity)
    if remaining <= 0:
        raise FifoError("Sell quantity must be positive")

    sell_price = Decimal(unit_price)
    fee_dec = Decimal(fee or 0)
    # Allocate fee proportionally across consumed qty for proceeds netting
    result = SellResult()
    eligible = sorted(
        (lot for lot in lots if lot.asset_key == asset_key and lot.open_qty > 0),
        key=lambda lot: (lot.open_date, lot.activity_id),
    )

    for lot in eligible:
        if remaining <= 0:
            break
        take = min(remaining, lot.open_qty)
        unit_cost = lot.unit_cost
        proceeds = take * sell_price
        # fee share proportional to qty
        fee_share = (take / Decimal(quantity)) * fee_dec if quantity else Decimal("0")
        net_proceeds = proceeds - fee_share
        gain = net_proceeds - take * unit_cost
        result.consumptions.append(
            Consumption(
                lot_activity_id=lot.activity_id,
                lot_open_date=lot.open_date,
                qty_consumed=take,
                proceeds=net_proceeds,
                realized_gain=gain,
                unit_cost=unit_cost,
                lot_id=lot.id,
            )
        )
        lot.open_qty -= take
        if lot.open_qty == 0:
            lot.status = "CLOSED"
            lot.closed_at = trade_date
        else:
            lot.status = "PARTIAL"
            lot.closed_at = None
        remaining -= take
        result.qty_sold += take
        result.proceeds += net_proceeds
        result.realized_gain += gain

    if remaining > 0:
        raise FifoError(
            f"Insufficient open lots for {asset_key}: short by {remaining}"
        )
    return result


def estimate_tax(realized_gain: Decimal, tax_rate: Decimal) -> Decimal:
    if realized_gain <= 0:
        return Decimal("0")
    return (realized_gain * tax_rate).quantize(Decimal("0.01"))
