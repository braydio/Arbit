"""Shared data models for arbitrage operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional


@dataclass(frozen=True)
class Triangle:
    """Trading symbols forming a triangular arbitrage path."""

    leg_ab: str
    leg_bc: str
    leg_ac: str


@dataclass(frozen=True)
class OrderSpec:
    """Specification for placing an order on an exchange."""

    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    price: Optional[float] = None
    order_type: Literal["limit", "market"] = "limit"


@dataclass(frozen=True)
class Fill:
    """Execution details of a completed order.

    Optional fields enable richer persistence without breaking callers that
    only care about core execution data.
    """

    order_id: str
    symbol: str
    side: Literal["buy", "sell"]
    price: float
    quantity: float
    fee: float
    timestamp: datetime | None = None
    # Optional metadata (persistence/analysis)
    venue: str | None = None
    leg: str | None = None  # one of {AB, BC, AC}
    tif: str | None = None
    order_type: str | None = None
    fee_rate: float | None = None
    notional: float | None = None
    dry_run: bool | None = None
    attempt_id: int | None = None


@dataclass(frozen=True)
class TriangleAttempt:
    """A single attempt (success or skip) at executing a triangle."""

    venue: str
    leg_ab: str
    leg_bc: str
    leg_ac: str
    ts_iso: str
    ok: bool
    net_est: float | None = None
    realized_usdt: float | None = None
    threshold_bps: float | None = None
    notional_usd: float | None = None
    slippage_bps: float | None = None
    dry_run: bool | None = None
    latency_ms: float | None = None
    skip_reasons: str | None = None  # comma-joined
    # top-of-book snapshot
    ab_bid: float | None = None
    ab_ask: float | None = None
    bc_bid: float | None = None
    bc_ask: float | None = None
    ac_bid: float | None = None
    ac_ask: float | None = None
    qty_base: float | None = None
