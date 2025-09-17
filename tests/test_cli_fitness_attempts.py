from __future__ import annotations

from types import SimpleNamespace

import arbit.cli.commands.fitness as fitness_mod


class _FakeClock:
    """Simple monotonic clock used to control time progression in tests."""

    def __init__(self) -> None:
        self.value = 0.0

    def time(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def test_fitness_attempt_logs_include_counters(monkeypatch, caplog):
    """Per-attempt Discord and CLI logs should include attempt counters."""

    clock = _FakeClock()
    monkeypatch.setattr(fitness_mod.time, "time", clock.time)
    monkeypatch.setattr(fitness_mod.time, "sleep", clock.sleep)

    class DummyAdapter:
        def fetch_orderbook(self, _symbol: str, _depth: int) -> dict:
            return {"bids": [[1.0, 1.0]], "asks": [[1.01, 1.0]]}

    monkeypatch.setattr(
        fitness_mod,
        "_build_adapter",
        lambda _venue, _settings: DummyAdapter(),
    )
    monkeypatch.setattr(
        fitness_mod,
        "_triangles_for",
        lambda _venue: [fitness_mod.Triangle("A/B", "B/C", "A/C")],
    )
    monkeypatch.setattr(fitness_mod, "_log_balances", lambda *_a, **_k: None)

    def fake_try_triangle(_adapter, _tri, _books, _threshold, _reasons):
        clock.value = 1.0
        return {
            "net_est": 0.123,
            "realized_usdt": 2.5,
            "fills": [{"qty": 0.01}],
        }

    monkeypatch.setattr(fitness_mod, "try_triangle", fake_try_triangle)

    dummy_settings = SimpleNamespace(
        dry_run=True,
        sqlite_path=":memory:",
        net_threshold_bps=0.0,
        notional_per_trade_usd=0.0,
        max_slippage_bps=0.0,
        discord_min_notify_interval_secs=0.0,
        discord_attempt_notify=False,
    )
    monkeypatch.setattr(fitness_mod, "settings", dummy_settings)

    messages: list[str] = []

    def fake_notify(_venue: str, message: str, **_kwargs) -> None:
        messages.append(message)

    monkeypatch.setattr(fitness_mod, "notify_discord", fake_notify)

    caplog.set_level("INFO", logger="arbit")

    fitness_mod.fitness(
        venue="demo",
        secs=1,
        simulate=True,
        persist=False,
        attempt_notify=True,
    )

    assert any("attempt#1" in msg for msg in messages)
    assert any("sim_trades_total=1" in msg for msg in messages)
    assert any("attempt#1" in rec.message for rec in caplog.records)
