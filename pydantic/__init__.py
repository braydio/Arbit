"""Minimal subset of Pydantic for testing purposes."""

from __future__ import annotations

import os
from typing import Any


def Field(default: Any, description: str | None = None) -> Any:
    """Return ``default`` value; kept for compatibility.

    Args:
        default: The default value to return.
        description: Deprecated parameter retained for API compatibility.

    Returns:
        The ``default`` value as provided.
    """
    _ = description
    return default


class BaseSettings:
    """Very small settings loader using environment variables."""

    class Config:
        env_prefix = ""
        case_sensitive = False

    def __init__(self, **kwargs: Any) -> None:
        for name, default in self.__class__.__dict__.items():
            if name.startswith("_") or callable(default):
                continue
            env_name = f"{self.Config.env_prefix}{name}".upper()
            value = os.getenv(env_name, default)
            setattr(self, name, kwargs.get(name, value))
