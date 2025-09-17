"""Helpers for writing CLI environment configuration files.

This module centralizes logic for updating environment files used by the
Typer CLI commands. Currently it exposes a helper for safely persisting
triangle discoveries back to a ``.env`` file without disturbing unrelated
settings.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import MutableMapping, Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile

__all__ = ["_update_env_triangles"]

_ENV_LINE_RE = re.compile(
    r"^(?P<prefix>\s*(?:export\s+)?)"
    r"(?P<key>[A-Za-z_][A-Za-z0-9_]*)"
    r"(?P<sep>\s*=\s*)"
    r"(?P<value>.*)$"
)


def _normalize_triangles(triangles: Sequence[Sequence[str]]) -> list[list[str]]:
    """Normalize *triangles* into a JSON-serializable list of string triples.

    Args:
        triangles: Sequence of 3-leg triangle definitions. Entries that are not
            iterable, contain fewer than three legs, or include ``None`` values
            are ignored.

    Returns:
        A list of ``[leg_ab, leg_bc, leg_ac]`` triples ready for JSON encoding.
    """

    normalized: list[list[str]] = []
    for tri in triangles:
        if not isinstance(tri, Sequence):
            continue
        if isinstance(tri, (str, bytes)):
            continue
        if len(tri) != 3:
            continue
        legs = [str(part) for part in tri]
        if any(not leg for leg in legs):
            continue
        normalized.append(legs)
    return normalized


def _parse_existing_triangles(value: str) -> MutableMapping[str, list[list[str]]]:
    """Parse the JSON payload contained in *value*.

    Args:
        value: String payload extracted from the ``TRIANGLES_BY_VENUE`` line of
            a ``.env`` file. Surrounding single or double quotes should already
            be removed.

    Returns:
        A mutable mapping representing the decoded JSON object. Invalid or
        non-object payloads yield an empty dictionary.
    """

    try:
        data = json.loads(value) if value else {}
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, MutableMapping):
        return {}
    cleaned: dict[str, list[list[str]]] = {}
    for venue, triangles in data.items():
        if not isinstance(venue, str):
            continue
        if isinstance(triangles, Sequence):
            cleaned[venue] = _normalize_triangles(triangles)  # type: ignore[arg-type]
    return cleaned


def _prepare_env_content(lines: list[str], newline: str, ensure_trailing: bool) -> str:
    """Return serialized file content with consistent newline handling."""

    body = newline.join(lines)
    if ensure_trailing:
        body += newline
    return body


def _update_env_triangles(
    venue: str,
    triangles: Sequence[Sequence[str]],
    env_path: str = ".env",
) -> bool:
    """Persist *triangles* for *venue* into ``TRIANGLES_BY_VENUE`` within *env_path*.

    The helper preserves unrelated settings, updates existing triangle entries
    when present, and performs an atomic replacement to avoid partially written
    files.

    Args:
        venue: Venue identifier (e.g., ``"kraken"``).
        triangles: Iterable of triangle legs discovered for the venue.
        env_path: Target ``.env`` file path. Missing files will be created.

    Returns:
        ``True`` if the update succeeds, ``False`` otherwise.
    """

    path = Path(env_path)
    try:
        raw = path.read_text(encoding="utf-8")
        newline = (
            "\r\n" if "\r\n" in raw and "\n" not in raw.replace("\r\n", "") else "\n"
        )
        lines = raw.splitlines()
        had_trailing_newline = raw.endswith(("\n", "\r\n"))
    except FileNotFoundError:
        lines = []
        newline = "\n"
        had_trailing_newline = True
    except OSError:
        return False

    normalized = _normalize_triangles(triangles)
    data: MutableMapping[str, list[list[str]]] = {}
    line_index: int | None = None
    line_prefix = ""
    line_sep = "="
    existing_value = ""

    for idx, line in enumerate(lines):
        match = _ENV_LINE_RE.match(line)
        if not match:
            continue
        key = match.group("key")
        if key != "TRIANGLES_BY_VENUE":
            continue
        line_index = idx
        line_prefix = match.group("prefix") or ""
        line_sep = match.group("sep") or "="
        raw_value = match.group("value").strip()
        if (
            len(raw_value) >= 2
            and raw_value[0] == raw_value[-1]
            and raw_value[0] in {'"', "'"}
        ):
            raw_value = raw_value[1:-1]
        existing_value = raw_value
        break

    if existing_value:
        data = _parse_existing_triangles(existing_value)
    if not isinstance(data, MutableMapping):
        data = {}

    data[str(venue)] = normalized
    payload = json.dumps(data, separators=(",", ":"), sort_keys=True)

    new_line = f"{line_prefix}TRIANGLES_BY_VENUE{line_sep}{payload}"

    if line_index is not None:
        lines[line_index] = new_line
    else:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(new_line)
        had_trailing_newline = True

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with NamedTemporaryFile(
            "w", encoding="utf-8", dir=str(path.parent), delete=False
        ) as tmp:
            tmp.write(_prepare_env_content(lines, newline, had_trailing_newline))
            tmp_path = Path(tmp.name)
    except OSError:
        return False

    try:
        os.replace(tmp_path, path)
    except OSError:
        try:
            tmp_path.unlink(missing_ok=True)  # type: ignore[attr-defined]
        except Exception:
            pass
        return False

    return True
