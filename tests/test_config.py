"""Configuration model tests."""

from __future__ import annotations

import importlib
import os
import sys


def _load_with_exchanges(monkeypatch, value: str):
    """Reload the config module with ``EXCHANGES`` set to *value*."""
    original = sys.modules.get("arbit.config")
    sys.modules.pop("arbit.config", None)
    monkeypatch.setenv("EXCHANGES", value)
    cfg = importlib.import_module("arbit.config")
    if original is not None:
        sys.modules["arbit.config"] = original
    else:
        sys.modules.pop("arbit.config", None)
    return cfg


def test_exchanges_json(monkeypatch):
    cfg = _load_with_exchanges(monkeypatch, '["alpaca", "kraken"]')
    assert cfg.settings.exchanges == ["alpaca", "kraken"]


def test_exchanges_csv(monkeypatch):
    cfg = _load_with_exchanges(monkeypatch, "alpaca, kraken")
    assert cfg.settings.exchanges == ["alpaca", "kraken"]


def test_load_env_file_strips_quotes(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text('FOO="bar"\n')
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("FOO", raising=False)
    original = sys.modules.get("arbit.config")
    sys.modules.pop("arbit.config", None)
    importlib.import_module("arbit.config")
    assert os.environ["FOO"] == "bar"
    if original is not None:
        sys.modules["arbit.config"] = original
    else:
        sys.modules.pop("arbit.config", None)
    monkeypatch.delenv("FOO", raising=False)
