"""Minimal subset of the Typer API for offline testing."""

from __future__ import annotations

import inspect
import click


class Typer(click.Group):
    """Simplified Typer implementation based on Click."""

    def command(self, *args, **kwargs):  # type: ignore[override]
        def decorator(func):
            sig = inspect.signature(func)
            params = []
            for name, param in sig.parameters.items():
                opt = click.Option(
                    [f"--{name.replace('_','-')}"],
                    default=param.default,
                    type=(eval(param.annotation, func.__globals__) if isinstance(param.annotation, str) else param.annotation) if param.annotation is not inspect._empty else str,
                )
                params.append(opt)
            cmd = click.Command(func.__name__, params=params, callback=func)
            self.add_command(cmd)
            return cmd
        return decorator

    def __call__(self, *args, **kwargs):  # pragma: no cover - passthrough
        return self.main(*args, **kwargs)


def echo(message: str) -> None:
    """Print *message* to stdout."""
    click.echo(message)
