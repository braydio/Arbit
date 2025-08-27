"""Testing helpers for the minimal :mod:`click` clone."""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass
from typing import Any, List


@dataclass
class Result:
    """Outcome of invoking a CLI command."""

    exit_code: int
    output: str
    exception: Exception | None = None


class CliRunner:
    """Execute commands and capture their output for tests."""

    @staticmethod
    def invoke(app, args: List[str]) -> Result:
        buf = io.StringIO()
        exc: Exception | None = None
        with contextlib.redirect_stdout(buf):
            try:
                app.main(list(args))
                code = 0
            except SystemExit as e:
                code = int(e.code)
            except Exception as e:  # pragma: no cover - error path
                code = 1
                exc = e
        return Result(exit_code=code, output=buf.getvalue(), exception=exc)


__all__ = ["CliRunner", "Result"]
