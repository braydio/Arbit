"""Module entry point so `python -m arbit.cli` executes the Typer app."""

from __future__ import annotations

from .core import app


def main() -> None:
    """Invoke the CLI application."""

    app()


if __name__ == "__main__":  # pragma: no cover - module execution
    main()
