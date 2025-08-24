"""Core package for triangular arbitrage utilities."""

from __future__ import annotations

try:  # pragma: no cover - optional dependency
    from .config import Settings
except Exception:  # pragma: no cover - pydantic may be missing
    Settings = None  # type: ignore

from .models import Triangle, OrderSpec, Fill

__all__ = ["Settings", "Triangle", "OrderSpec", "Fill"]
