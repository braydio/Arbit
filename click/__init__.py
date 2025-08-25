"""A tiny subset of the Click API used for testing.

This lightweight implementation provides just enough features for the
project's Typer-based command line interface.  It supports defining
commands with options, grouping subcommands, emitting output, and running
commands via a simple test runner.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Any, Callable, Iterable, List


@dataclass
class Option:
    """Command line option definition.

    Parameters
    ----------
    names:
        Iterable of option flags (e.g. ``["--foo"]``).
    default:
        Default value used when the flag is not supplied.
    type:
        Callable used to convert the string value from the command line.
    """

    names: Iterable[str]
    default: Any = None
    type: Callable[[str], Any] = str

    @property
    def name(self) -> str:
        """Return the canonical option name without leading dashes."""
        for n in self.names:
            return n.lstrip("-").replace("-", "_")
        raise ValueError("Option without names")


class Command:
    """A callable command with typed options."""

    def __init__(self, name: str, params: List[Option], callback: Callable[..., Any]):
        self.name = name
        self.params = params
        self.callback = callback

    # pragma: no cover - trivial
    def add_command(self, cmd: "Command") -> None:
        raise NotImplementedError("Only groups support subcommands")

    def main(self, args: List[str] | None = None) -> Any:
        """Execute the command using *args* from the command line."""

        if args is None:
            args = sys.argv[1:]
        values = {p.name: p.default for p in self.params}
        it = iter(args)
        for token in it:
            if token.startswith("--"):
                name = token[2:].replace("-", "_")
                opt = next((p for p in self.params if p.name == name), None)
                if opt is None:
                    raise SystemExit(f"Unknown option {token}")
                try:
                    value = next(it)
                except StopIteration:  # pragma: no cover - invalid usage
                    raise SystemExit(f"Missing value for {token}")
                values[name] = opt.type(value)
            else:  # pragma: no cover - no positional args used in tests
                raise SystemExit(f"Unexpected argument {token}")
        return self.callback(**values)

    # allow calling like a function
    __call__ = main


class Group(Command):
    """Collection of subcommands."""

    def __init__(
        self,
        name: str | None = None,
        params: List[Option] | None = None,
        callback: Callable[..., Any] | None = None,
    ):
        super().__init__(name or "", params or [], callback or (lambda: None))
        self.commands: dict[str, Command] = {}

    def add_command(self, cmd: Command) -> None:
        """Register *cmd* as a subcommand."""
        self.commands[cmd.name] = cmd

    def main(self, args: List[str] | None = None) -> Any:
        if args is None:
            args = sys.argv[1:]
        if not args:
            raise SystemExit("Missing command")
        name, rest = args[0], args[1:]
        try:
            cmd = self.commands[name]
        except KeyError as exc:  # pragma: no cover - defensive
            raise SystemExit(f"Unknown command {name}") from exc
        return cmd.main(rest)


def echo(message: str) -> None:
    """Print *message* to standard output."""
    print(message)


__all__ = ["Option", "Command", "Group", "echo"]
