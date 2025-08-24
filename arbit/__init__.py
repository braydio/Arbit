"""Core package for triangular arbitrage utilities."""

from __future__ import annotations

try:  # pragma: no cover - optional dependency
    from .config import Settings
except Exception:  # pragma: no cover - pydantic may be missing
    Settings = None  # type: ignore

from .engine import try_triangle
from .models import Fill, OrderSpec, Triangle

__all__ = ["Settings", "Triangle", "OrderSpec", "Fill", "try_triangle"]
