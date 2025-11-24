"""Live trading CLI commands."""

from __future__ import annotations

import asyncio

from arbit.config import settings
from arbit.metrics.exporter import start_metrics_server
from arbit.notify import notify_discord

from ..core import TyperOption, app
from ..utils import _balances_brief, _build_adapter, _live_run_for_venue


@app.command("live")
@app.command("live_run")
def live(
    venue: str = "alpaca",
    venues: str | None = TyperOption(
        None,
        "--venues",
        help=(
            "Comma-separated venues to trade concurrently. Overrides --venue when"
            " provided."
        ),
    ),
    symbols: str | None = None,
    auto_suggest_top: int = 0,
    attempt_notify: bool | None = TyperOption(
        None,
        "--attempt-notify/--no-attempt-notify",
        help="Send per-attempt Discord alerts (noisy). Overrides env.",
    ),
    continuous: bool = TyperOption(
        False,
        "--continuous",
        help="Run continuously until stopped (Ctrl+C)",
    ),
    interval: int = TyperOption(
        30,
        "--interval",
        help="Seconds to wait between scans when running continuously.",
    ),
    help_verbose: bool = False,
) -> None:
    """Scan for profitable triangles and execute trades across venues.

    The command can be configured to loop continuously with a configurable
    interval between scans when ``--continuous`` is supplied.
    """

    if help_verbose:
        app.print_verbose_help_for("live")
        raise SystemExit(0)

    raw_venues = venues.split(",") if venues else [venue]
    venue_list: list[str] = []
    for entry in raw_venues:
        cleaned = entry.strip()
        if cleaned and cleaned not in venue_list:
            venue_list.append(cleaned)
    if not venue_list:
        venue_list = [venue]

    run_kwargs = {
        "symbols": symbols,
        "auto_suggest_top": auto_suggest_top,
        "attempt_notify_override": attempt_notify,
    }

    try:
        start_metrics_server(settings.prom_port)
    except Exception:
        pass

    async def _run_for_all() -> None:
        try:
            if continuous:
                while True:
                    if len(venue_list) == 1:
                        await _live_run_for_venue(venue_list[0], **run_kwargs)
                    else:
                        tasks = [
                            asyncio.create_task(_live_run_for_venue(v, **run_kwargs))
                            for v in venue_list
                        ]
                        await asyncio.gather(*tasks)

                    await asyncio.sleep(interval)
            else:
                if len(venue_list) == 1:
                    await _live_run_for_venue(venue_list[0], **run_kwargs)
                else:
                    tasks = [
                        asyncio.create_task(_live_run_for_venue(v, **run_kwargs))
                        for v in venue_list
                    ]
                    await asyncio.gather(*tasks)
        except KeyboardInterrupt:
            print("Stopping live monitor...")

    try:
        asyncio.run(_run_for_all())
    except KeyboardInterrupt:
        pass
    finally:
        if bool(getattr(settings, "discord_live_stop_notify", True)):
            for venue_name in venue_list:
                try:
                    adapter = _build_adapter(venue_name, settings)
                    notify_discord(
                        venue_name,
                        f"[live@{venue_name}] stop | {_balances_brief(adapter)}",
                    )
                except Exception:
                    pass


__all__ = ["live"]
