from __future__ import annotations

import arbit.cli as cli


def test_format_live_heartbeat_includes_stats(monkeypatch):
    """format_live_heartbeat should report key metrics."""

    # Freeze time so attempts_per_sec is deterministic
    monkeypatch.setattr(cli.time, "time", lambda: 10.0)

    msg = cli.format_live_heartbeat(
        venue="kraken",
        dry_run=True,
        attempts=10,
        successes=2,
        last_net=0.01,
        last_pnl=5.0,
        net_total=0.02,
        latency_total=1.0,
        start_time=0.0,
    )

    assert "attempts=10" in msg
    assert "successes=2" in msg
    assert "hit_rate=20.00%" in msg
    assert "avg_spread=1.00%" in msg
    assert "avg_latency_ms=100.0" in msg
    assert "attempts_per_sec=1.00" in msg
