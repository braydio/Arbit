"""Configuration management and credential helpers."""

from typing import List

from pydantic import BaseSettings


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    env: str = "dev"
    log_level: str = "INFO"
    exchanges: List[str] = ["alpaca", "kraken"]  # default venues

    # Per-venue keys (preferred)
    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None
    alpaca_base_url: str = "https://api.alpaca.markets"

    kraken_api_key: str | None = None
    kraken_api_secret: str | None = None

    # Legacy fallback (ARBIT_* → use for both if set)
    arbit_api_key: str | None = None
    arbit_api_secret: str | None = None

    notional_per_trade_usd: float = 200.0
    net_threshold_bps: float = 10.0
    max_slippage_bps: float = 8.0
    max_open_orders: int = 3
    dry_run: bool = True

    prom_port: int = 9109
    sqlite_path: str = "arbit.db"
    discord_webhook_url: str | None = None

    class Config(BaseSettings.Config):
        """Pydantic settings configuration."""

        env_file = ".env"


# Singleton settings instance populated on import.
settings = Settings()


def creds_for(ex_id: str) -> tuple[str | None, str | None]:
    """Return API credentials for *ex_id*, falling back to legacy values."""
    # Prefer per-venue; fall back to legacy ARBIT_* if present.
    if ex_id == "alpaca":
        return (
            settings.alpaca_api_key or settings.arbit_api_key,
            settings.alpaca_api_secret or settings.arbit_api_secret,
        )
    if ex_id == "kraken":
        return (
            settings.kraken_api_key or settings.arbit_api_key,
            settings.kraken_api_secret or settings.arbit_api_secret,
        )
    return (settings.arbit_api_key, settings.arbit_api_secret)
