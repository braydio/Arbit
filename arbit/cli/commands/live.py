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
    help_verbose: bool = False,
) -> None:
    """Continuously scan for profitable triangles and execute trades across venues."""

    if help_verbose:
        app.print_verbose_help_for("live")
        raise SystemExit(0)

    venue_list = [
        v.strip()
        for v in (venues.split(",") if venues else [venue])
        if v.strip()
    ]
    if not venue_list:
        venue_list = [venue]

    try:
        start_metrics_server(settings.prom_port)
    except Exception:
        pass

    async def _run_for_all() -> None:
        if len(venue_list) == 1:
            await _live_run_for_venue(
                venue_list[0],
                symbols=symbols,
                auto_suggest_top=auto_suggest_top,
                attempt_notify_override=attempt_notify,
            )
            return

        tasks = [
            asyncio.create_task(
                _live_run_for_venue(
                    venue_name,
                    symbols=symbols,
                    auto_suggest_top=auto_suggest_top,
                    attempt_notify_override=attempt_notify,
                )
            )
            for venue_name in venue_list
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:  # pragma: no cover - ctrl+c handling
            for task in tasks:
                task.cancel()
        except KeyboardInterrupt:  # pragma: no cover
            for task in tasks:
                task.cancel()

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
