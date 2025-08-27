"""Minimal subset of the Typer API for offline testing."""

from __future__ import annotations

import inspect
import typing

import click


class Typer(click.Group):
    """Simplified Typer implementation based on Click."""

    def command(self, *args, **kwargs):  # type: ignore[override]
        """Return a decorator registering a function as a CLI command."""

        def decorator(func):
            sig = inspect.signature(func)
            type_hints = typing.get_type_hints(func, globalns=func.__globals__)
            params = []
            for name, param in sig.parameters.items():
                annotation = type_hints.get(name, param.annotation)
                opt = click.Option(
                    [f"--{name.replace('_', '-')}"],
                    default=param.default,
                    type=(
                        annotation if annotation is not inspect.Signature.empty else str
                    ),
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
