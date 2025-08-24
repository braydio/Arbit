"""Exchange adapter interfaces and implementations."""

from .base import ExchangeAdapter

try:  # pragma: no cover - optional dependency
    from .ccxt_adapter import CCXTAdapter
except Exception:  # pragma: no cover
    CCXTAdapter = None  # type: ignore

__all__ = ["ExchangeAdapter", "CCXTAdapter"]
