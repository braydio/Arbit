"""Core Typer application and logging bootstrap for the Arbit CLI package."""

from __future__ import annotations

import logging
import sys
from typing import Any

import typer
from arbit.config import settings

from .help_text import VERBOSE_COMMAND_HELP, VERBOSE_GLOBAL_OVERVIEW

# Backward-compat: some environments may lack typer.Option; provide a fallback
try:  # pragma: no cover - environment-specific
    from typer import Option as TyperOption
except Exception:  # pragma: no cover

    def TyperOption(default: Any = None, *args: Any, **kwargs: Any) -> Any:
        """Fallback used when Typer's Option helper is unavailable."""

        return default


class CLIApp(typer.Typer):
    """Custom Typer application that prints usage on bad invocation."""

    # ------------------------------------------------------------------
    def _unique_commands(self) -> dict[str, dict[str, Any]]:
        """Return mapping of canonical command names to command/aliases."""

        mapping: dict[str, dict[str, Any]] = {}
        for name, cmd in self.commands.items():
            canonical = name.replace("_", ":")
            info = mapping.setdefault(canonical, {"command": cmd, "aliases": []})
            info["aliases"].append(name)
        return mapping

    def main(self, args: list[str] | None = None):  # type: ignore[override]
        """Run the CLI with *args*, handling help flags and bad input."""

        if args is None:
            args = sys.argv[1:]

        if args and "--help-verbose" in args:
            idx = args.index("--help-verbose")
            if idx == 0:
                self._print_verbose_help()
            else:
                target = args[0] if args else ""
                canonical = None
                for cname, info in self._unique_commands().items():
                    if target == cname or target in info["aliases"]:
                        canonical = cname
                        break
                self._print_verbose_help(canonical)
            raise SystemExit(0)

        if args and args[0] == "--help":
            self._print_basic_help()
            raise SystemExit(0)

        if not args or args[0] not in self.commands:
            typer.echo("Usage: arbit.cli [COMMAND]")
            if self.commands:
                typer.echo("Commands:")
                for cname in sorted(self._unique_commands()):
                    typer.echo(f"  {cname}")
            raise SystemExit(0 if not args else 1)
        return super().main(args)

    # ------------------------------------------------------------------
    def _print_basic_help(self) -> None:
        """Print a short summary of available commands."""

        typer.echo(
            "Usage: python -m arbit.cli [--help | --help-verbose] COMMAND [ARGS]"
        )
        typer.echo("\nAvailable commands:")
        for cname, info in sorted(self._unique_commands().items()):
            desc = (info["command"].callback.__doc__ or "").strip().splitlines()[0]
            aliases = [
                a.replace("_", ":")
                for a in info["aliases"]
                if a.replace("_", ":") != cname
            ]
            alias_str = f" (aliases: {', '.join(sorted(aliases))})" if aliases else ""
            typer.echo(f"  {cname:<12} {desc}{alias_str}")
        typer.echo(
            "\nExchanges: alpaca (native API via alpaca-py) and kraken (via CCXT)."
        )
        typer.echo(
            "\nTip: run --help-verbose for the full catalog or COMMAND --help-verbose"
            " for focused tips."
        )

    # ------------------------------------------------------------------
    def _print_verbose_help(self, command: str | None = None) -> None:
        """Print detailed command reference with optional command filtering."""

        typer.echo(VERBOSE_GLOBAL_OVERVIEW.strip())
        typer.echo()

        if command:
            text = VERBOSE_COMMAND_HELP.get(command)
            if text:
                typer.echo(text.rstrip())
            else:
                typer.echo(f"No verbose help available for '{command}'.")
            return

        for cname, info in sorted(self._unique_commands().items()):
            text = VERBOSE_COMMAND_HELP.get(cname)
            if not text:
                continue
            typer.echo(text.rstrip())
            aliases = [
                alias.replace("_", ":")
                for alias in info["aliases"]
                if alias.replace("_", ":") != cname
            ]
            if aliases:
                typer.echo(f"  Aliases: {', '.join(sorted(set(aliases)))}")
            typer.echo()

    def print_verbose_help_for(self, command: str) -> None:
        """Expose verbose help rendering for command functions."""

        self._print_verbose_help(command)


app = CLIApp()
log = logging.getLogger("arbit")

# Configure logging once with console + optional rotating file handler
if not getattr(log, "_configured", False):
    log.setLevel(getattr(logging, str(settings.log_level).upper(), logging.INFO))
    log.propagate = False
    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(log.level)
    ch.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    log.addHandler(ch)
    # Optional file handler
    try:
        import os
        from logging.handlers import RotatingFileHandler

        log_path = getattr(settings, "log_file", None) or "data/arbit.log"
        if log_path:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            max_bytes = int(getattr(settings, "log_max_bytes", 1_000_000) or 1_000_000)
            backup_count = int(getattr(settings, "log_backup_count", 3) or 3)
            fh = RotatingFileHandler(
                log_path, maxBytes=max_bytes, backupCount=backup_count
            )
            fh.setLevel(log.level)
            fh.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
            )
            log.addHandler(fh)
    except Exception:
        # If file logging fails, continue with console-only
        pass
    setattr(log, "_configured", True)

__all__ = ["CLIApp", "TyperOption", "app", "log"]
