from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

# Pseudo-depot for activities/lots without Ghostfolio accountId.
UNASSIGNED_ACCOUNT_ID = "__unassigned__"


def normalize_account_id(account_id: str | None) -> str:
    """Map NULL/empty account to the unassigned pseudo-depot."""
    if account_id is None:
        return UNASSIGNED_ACCOUNT_ID
    stripped = account_id.strip()
    return stripped if stripped else UNASSIGNED_ACCOUNT_ID


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
    account_id: str = UNASSIGNED_ACCOUNT_ID
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
    account_id: str | None = None,
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
        account_id=normalize_account_id(account_id),
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
    account_id: str | None = None,
) -> SellResult:
    """Consume oldest open lots first within the same account (FIFO)."""
    remaining = Decimal(quantity)
    if remaining <= 0:
        raise FifoError("Sell quantity must be positive")

    scope = normalize_account_id(account_id)
    sell_price = Decimal(unit_price)
    fee_dec = Decimal(fee or 0)
    result = SellResult()
    eligible = sorted(
        (
            lot
            for lot in lots
            if lot.asset_key == asset_key
            and lot.account_id == scope
            and lot.open_qty > 0
        ),
        key=lambda lot: (lot.open_date, lot.activity_id),
    )

    for lot in eligible:
        if remaining <= 0:
            break
        take = min(remaining, lot.open_qty)
        unit_cost = lot.unit_cost
        proceeds = take * sell_price
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
            f"Insufficient open lots for {asset_key} in account {scope}: "
            f"short by {remaining}"
        )
    return result


@dataclass
class TransferMove:
    source_lot_activity_id: int
    source_open_date: date
    qty: Decimal
    cost_basis: Decimal
    unit_cost: Decimal
    source_lot_id: int | None = None


@dataclass
class TransferResult:
    moves: list[TransferMove] = field(default_factory=list)
    new_lots: list[LotState] = field(default_factory=list)


def apply_transfer(
    lots: list[LotState],
    *,
    asset_key: str,
    quantity: Decimal,
    from_account_id: str | None,
    to_account_id: str | None,
    transfer_date: date | None = None,
) -> TransferResult:
    """Move quantity FIFO from one account to another without realized gain."""
    remaining = Decimal(quantity)
    if remaining <= 0:
        raise FifoError("Transfer quantity must be positive")

    src = normalize_account_id(from_account_id)
    dst = normalize_account_id(to_account_id)
    if src == dst:
        raise FifoError("Transfer requires distinct source and destination accounts")

    result = TransferResult()
    eligible = sorted(
        (
            lot
            for lot in lots
            if lot.asset_key == asset_key and lot.account_id == src and lot.open_qty > 0
        ),
        key=lambda lot: (lot.open_date, lot.activity_id),
    )

    for lot in eligible:
        if remaining <= 0:
            break
        take = min(remaining, lot.open_qty)
        unit_cost = lot.unit_cost
        cost = take * unit_cost
        result.moves.append(
            TransferMove(
                source_lot_activity_id=lot.activity_id,
                source_lot_id=lot.id,
                source_open_date=lot.open_date,
                qty=take,
                cost_basis=cost,
                unit_cost=unit_cost,
            )
        )
        lot.open_qty -= take
        if lot.open_qty == 0:
            lot.status = "CLOSED"
            lot.closed_at = transfer_date
        else:
            lot.status = "PARTIAL"
            lot.closed_at = None

        dest = LotState(
            activity_id=lot.activity_id,
            asset_key=asset_key,
            open_qty=take,
            original_qty=take,
            cost_basis=cost,
            open_date=lot.open_date,
            account_id=dst,
            status="OPEN",
        )
        result.new_lots.append(dest)
        lots.append(dest)
        remaining -= take

    if remaining > 0:
        raise FifoError(
            f"Insufficient open lots for transfer of {asset_key} from {src}: "
            f"short by {remaining}"
        )
    return result


def estimate_tax(realized_gain: Decimal, tax_rate: Decimal) -> Decimal:
    if realized_gain <= 0:
        return Decimal("0")
    return (realized_gain * tax_rate).quantize(Decimal("0.01"))
