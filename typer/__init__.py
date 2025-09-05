"""Minimal subset of the Typer API for offline testing."""

from __future__ import annotations

import inspect
import typing

import click


class Typer(click.Group):
    """Simplified Typer implementation based on Click.

    Supports:
    - ``@app.command()`` and ``@app.command("name")``
    - Stacked decorators for aliases, e.g.:
        @app.command("foo:bar")
        @app.command("foo_bar")
        def foo_bar(...): ...
    """

    def command(self, *args, **kwargs):  # type: ignore[override]
        """Return a decorator registering a function or alias as a CLI command."""

        # Optional custom command name may be passed positionally like Typer
        custom_name = args[0] if args and isinstance(args[0], str) else None

        def decorator(obj):
            # If this decorator is applied on an already-created Command
            # (because of stacked decorators), register an alias.
            if isinstance(obj, click.Command):
                if custom_name:
                    # Alias the existing command under the provided name.
                    self.commands[custom_name] = obj
                else:
                    # No custom_name: ensure it's registered under its own name.
                    self.add_command(obj)
                return obj

            # Otherwise, we're decorating a function; introspect parameters.
            func = obj
            sig = inspect.signature(func)
            try:
                # Use function globals when available; fall back to empty.
                type_hints = typing.get_type_hints(
                    func, globalns=getattr(func, "__globals__", {})
                )
            except Exception:
                # Be resilient to evaluation issues in annotations.
                type_hints = {}

            params = []
            for pname, param in sig.parameters.items():
                annotation = type_hints.get(pname, param.annotation)

                # Choose a converter callable for the option type.
                opt_type: typing.Callable[[str], typing.Any]
                if annotation is bool:

                    def _parse_bool(s: str) -> bool:
                        sl = s.lower()
                        if sl in ("1", "true", "yes", "on"):  # common truthy tokens
                            return True
                        if sl in ("0", "false", "no", "off"):
                            return False
                        raise SystemExit(
                            f"Invalid boolean for --{pname.replace('_', '-')}: {s}"
                        )

                    opt_type = _parse_bool
                else:
                    opt_type = (
                        annotation if annotation is not inspect.Signature.empty else str
                    )

                default = (
                    None if param.default is inspect.Signature.empty else param.default
                )
                opt = click.Option(
                    [f"--{pname.replace('_', '-')}"],
                    default=default,
                    type=opt_type,
                )
                params.append(opt)

            name = custom_name or func.__name__
            cmd = click.Command(name, params=params, callback=func)
            self.add_command(cmd)
            return cmd

        return decorator

    def __call__(self, *args, **kwargs):  # pragma: no cover - passthrough
        return self.main(*args, **kwargs)


def echo(message: str) -> None:
    """Print *message* to stdout."""
    click.echo(message)
