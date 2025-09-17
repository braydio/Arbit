"""Arbit CLI package that exposes the Typer application and command helpers."""

from __future__ import annotations

import asyncio as asyncio
import time as time

from arbit.config import settings
from arbit.engine.triangle import (
    discover_triangles_from_markets as _discover_triangles_from_markets,
)
from arbit.metrics.exporter import (
    CYCLE_LATENCY,
    FILLS_TOTAL,
    ORDERS_TOTAL,
    PROFIT_TOTAL,
    YIELD_ALERTS_TOTAL,
    YIELD_APR,
    YIELD_BEST_APR,
    YIELD_CHECKS_TOTAL,
    YIELD_DEPOSITS_TOTAL,
    YIELD_ERRORS_TOTAL,
    YIELD_WITHDRAWS_TOTAL,
    start_metrics_server,
)
from arbit.models import Fill, Triangle, TriangleAttempt
from arbit.notify import fmt_usd, notify_discord
from arbit.persistence.db import (
    init_db,
    insert_attempt,
    insert_fill,
    insert_triangle,
    insert_yield_op,
)

from .core import CLIApp, TyperOption, app, log
from .help_text import VERBOSE_COMMAND_HELP, VERBOSE_GLOBAL_OVERVIEW
from .utils import (
    AaveProvider,
    AlpacaAdapter,
    CCXTAdapter,
    ExchangeAdapter,
    _balances_brief,
    _build_adapter,
    _live_run_for_venue,
    _log_balances,
    _triangles_for,
    format_live_heartbeat,
    stream_triangles,
    try_triangle,
)

# Import command modules for side-effect registration
from . import commands
from .commands.config import config_discover, config_recommend
from .commands.fitness import fitness, fitness_hybrid
from .commands.keys import keys_check
from .commands.live import live, live_multi
from .commands.markets import markets_limits
from .commands.notify import notify_test
from .commands.yield_commands import yield_collect, yield_watch, yield_withdraw

__all__ = [
    "CLIApp",
    "TyperOption",
    "AaveProvider",
    "AlpacaAdapter",
    "CCXTAdapter",
    "ExchangeAdapter",
    "Fill",
    "Triangle",
    "TriangleAttempt",
    "VERBOSE_COMMAND_HELP",
    "VERBOSE_GLOBAL_OVERVIEW",
    "_balances_brief",
    "_build_adapter",
    "_discover_triangles_from_markets",
    "_live_run_for_venue",
    "_log_balances",
    "_triangles_for",
    "app",
    "asyncio",
    "commands",
    "config_discover",
    "config_recommend",
    "fitness",
    "fitness_hybrid",
    "format_live_heartbeat",
    "init_db",
    "insert_attempt",
    "insert_fill",
    "insert_triangle",
    "insert_yield_op",
    "keys_check",
    "live",
    "live_multi",
    "log",
    "markets_limits",
    "notify_discord",
    "notify_test",
    "settings",
    "start_metrics_server",
    "stream_triangles",
    "time",
    "try_triangle",
    "fmt_usd",
    "yield_collect",
    "yield_watch",
    "yield_withdraw",
    "CYCLE_LATENCY",
    "FILLS_TOTAL",
    "ORDERS_TOTAL",
    "PROFIT_TOTAL",
    "YIELD_ALERTS_TOTAL",
    "YIELD_APR",
    "YIELD_BEST_APR",
    "YIELD_CHECKS_TOTAL",
    "YIELD_DEPOSITS_TOTAL",
    "YIELD_ERRORS_TOTAL",
    "YIELD_WITHDRAWS_TOTAL",
]
