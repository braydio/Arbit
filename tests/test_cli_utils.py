"""Tests for CLI utility helpers."""

from __future__ import annotations

from types import SimpleNamespace

from arbit.cli import utils as cli_utils
from arbit.models import Triangle


def test_triangles_for_respects_explicit_empty_list(monkeypatch) -> None:
    """An explicit empty list should disable fallback defaults."""

    monkeypatch.setattr(
        cli_utils,
        "settings",
        SimpleNamespace(triangles_by_venue={"alpaca": []}),
    )

    assert cli_utils._triangles_for("alpaca") == []


def test_triangles_for_missing_venue_uses_fallback(monkeypatch) -> None:
    """Missing venue definitions should still return the default templates."""

    monkeypatch.setattr(
        cli_utils,
        "settings",
        SimpleNamespace(triangles_by_venue={}),
    )

    triangles = cli_utils._triangles_for("kraken")

    assert triangles  # default fallback templates
    assert all(isinstance(tri, Triangle) for tri in triangles)
    assert triangles[0].leg_ab == "ETH/USDT"
