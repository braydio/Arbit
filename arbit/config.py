"""Configuration management and credential helpers.

This module loads environment variables from a local ``.env`` file if one is
present so that credentials such as API keys are available without manual
exports.  Values in the real environment take precedence over those in the
file.
"""

import json
import os
from pathlib import Path
from typing import Any, List

from pydantic import BaseSettings


def _load_env_file(path: str = ".env") -> None:
    """Populate :mod:`os.environ` with key/value pairs from *path*.

    The implementation is intentionally minimal to avoid depending on external
    packages such as :mod:`python-dotenv`. Lines starting with ``#`` or lacking
    an ``=`` separator are ignored. Existing keys are not overwritten. Values
    wrapped in single or double quotes are unquoted to match typical ``.env``
    file behavior.
    """

    try:
        for line in Path(path).read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip()
            if (value.startswith('"') and value.endswith('"')) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            os.environ.setdefault(key, value)
    except FileNotFoundError:
        # It's fine if the .env file is absent; environment variables may be
        # supplied via other means (e.g., shell exports).
        pass


_load_env_file()


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

    # Aave staking defaults
    usdc_address: str = "0xff970A61a04b1Ca14834A43F5de4533eBDDB5CC8"
    pool_address: str = "0xE0fBa4Fc209b4948668006B2Be61711b7f465bAf"
    min_usdc_stake: int = 100 * 10**6  # 100 USDC (6 decimals)
    min_eth_balance_wei: int = int(0.005 * 10**18)  # 0.005 ETH for gas
    max_gas_price_gwei: int = 5  # Ceiling for gas price to ensure low fees

    prom_port: int = 9109
    sqlite_path: str = "arbit.db"
    discord_webhook_url: str | None = None

    # Per-venue triangle definitions (override via JSON in env if desired)
    # Format: { venue: [[leg_ab, leg_bc, leg_ac], ...], ... }
    triangles_by_venue: dict[str, list[list[str]]] = {
        "alpaca": [
            ["ETH/USDT", "ETH/BTC", "BTC/USDT"],
            ["ETH/USDC", "ETH/BTC", "BTC/USDC"],
        ],
        "kraken": [
            ["ETH/USDT", "ETH/BTC", "BTC/USDT"],
            ["ETH/USDC", "ETH/BTC", "BTC/USDC"],
        ],
    }

    class Config(BaseSettings.Config):
        """Pydantic settings configuration."""

        env_file = ".env"
        env_prefix = ""

    def __init__(self, **kwargs: Any) -> None:
        """Normalize exchange list from environment variables."""
        super().__init__(**kwargs)
        # Coerce common env-sourced strings to proper types for robustness.
        def _coerce_float(attr: str) -> None:
            v = getattr(self, attr, None)
            if isinstance(v, str):
                try:
                    setattr(self, attr, float(v))
                except Exception:
                    pass

        def _coerce_int(attr: str) -> None:
            v = getattr(self, attr, None)
            if isinstance(v, str):
                try:
                    setattr(self, attr, int(float(v)))
                except Exception:
                    pass

        def _coerce_bool(attr: str) -> None:
            v = getattr(self, attr, None)
            if isinstance(v, str):
                s = v.strip().lower()
                if s in {"1", "true", "yes", "on"}:
                    setattr(self, attr, True)
                elif s in {"0", "false", "no", "off"}:
                    setattr(self, attr, False)

        for f in ("notional_per_trade_usd", "net_threshold_bps", "max_slippage_bps"):
            _coerce_float(f)
        for f in (
            "max_open_orders",
            "prom_port",
            "min_usdc_stake",
            "min_eth_balance_wei",
            "max_gas_price_gwei",
        ):
            _coerce_int(f)
        _coerce_bool("dry_run")

        if isinstance(self.exchanges, str):
            try:
                parsed = json.loads(self.exchanges)
            except Exception:
                parsed = [e.strip() for e in self.exchanges.split(",") if e.strip()]
            else:
                if isinstance(parsed, str):
                    parsed = [s.strip() for s in parsed.split(",") if s.strip()]
            if isinstance(parsed, list):
                self.exchanges = parsed
            else:
                self.exchanges = [str(parsed)]


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
