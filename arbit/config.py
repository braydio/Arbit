"""Application configuration using Pydantic settings."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseSettings, Field


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables.

    Attributes:
        api_key: API key for exchange authentication.
        api_secret: API secret for exchange authentication.
        net_threshold: Minimum acceptable net profit threshold.
        data_dir: Directory for storing runtime data.
        log_path: File path for log output.
    """

    api_key: str = Field(..., description="Exchange API key")
    api_secret: str = Field(..., description="Exchange API secret")
    net_threshold: float = Field(0.001, description="Minimum net return threshold")
    data_dir: Path = Field(Path("./data"), description="Directory for storing data")
    log_path: Path = Field(Path("./arbit.log"), description="Path for log file")

    class Config:
        env_prefix = "ARBIT_"
        env_file = ".env"
        case_sensitive = False
