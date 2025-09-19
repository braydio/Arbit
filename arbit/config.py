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

try:  # Support Pydantic v1 and v2 (via pydantic-settings)
    from pydantic import BaseSettings  # type: ignore
except Exception:  # pragma: no cover - fallback for Pydantic v2
    try:
        from pydantic_settings import BaseSettings  # type: ignore
    except Exception as e:  # pragma: no cover
        raise ImportError(
            "BaseSettings not available; install pydantic (v1) or pydantic-settings (v2)"
        ) from e


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


def _coerce_fee_value(value: Any, *, assume_bps: bool) -> float | None:
    """Return a decimal fee rate parsed from *value*.

    Parameters
    ----------
    value:
        Raw value provided by the environment or settings initialiser.
    assume_bps:
        When ``True`` the supplied number is interpreted as basis points and
        scaled by ``1/10_000``. When ``False`` the number is assumed to be a
        decimal rate (e.g., ``0.001`` for 10 bps).

    Returns
    -------
    float | None
        Parsed and clamped decimal fee rate, or ``None`` if parsing fails.
    """

    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if assume_bps:
        number /= 10_000.0
    return max(number, 0.0)


def _normalize_fee_overrides(
    data: Any,
) -> dict[str, dict[str, dict[str, float]]]:
    """Return a normalised fee override mapping derived from *data*.

    Parameters
    ----------
    data:
        Raw mapping or JSON string describing fee overrides. Expected format is
        ``{venue: {symbol: {maker_bps|maker, taker_bps|taker}}}`` with fee
        values supplied either in basis points or decimal form.

    Returns
    -------
    dict[str, dict[str, dict[str, float]]]
        Nested mapping keyed by lower-case venue and upper-case symbol. Each
        value contains optional ``maker`` and ``taker`` decimal fee rates.
    """

    if data is None:
        return {}
    if isinstance(data, str):
        raw = data.strip()
        if not raw:
            return {}
        try:
            data = json.loads(raw)
        except Exception:
            return {}
    if not isinstance(data, dict):
        return {}

    normalised: dict[str, dict[str, dict[str, float]]] = {}
    for venue_key, symbols in data.items():
        if not isinstance(symbols, dict):
            continue
        venue = str(venue_key).strip().lower()
        if not venue:
            continue
        venue_map = normalised.setdefault(venue, {})
        for symbol_key, fee_map in symbols.items():
            if not isinstance(fee_map, dict):
                continue
            symbol = str(symbol_key).strip()
            if not symbol:
                continue
            symbol = symbol.upper()

            maker = _coerce_fee_value(fee_map.get("maker_bps"), assume_bps=True)
            taker = _coerce_fee_value(fee_map.get("taker_bps"), assume_bps=True)

            maker_decimal = _coerce_fee_value(fee_map.get("maker"), assume_bps=False)
            taker_decimal = _coerce_fee_value(fee_map.get("taker"), assume_bps=False)

            if maker is None:
                maker = maker_decimal
            if taker is None:
                taker = taker_decimal

            if maker is None and taker is None:
                continue

            entry = venue_map.setdefault(symbol, {})
            if maker is not None:
                entry["maker"] = maker
            if taker is not None:
                entry["taker"] = taker

    return normalised


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    env: str = "dev"
    log_level: str = "INFO"
    # Optional log file path; when set, logs also write to this file.
    log_file: str | None = "data/arbit.log"
    log_max_bytes: int = 1_000_000
    log_backup_count: int = 3
    exchanges: List[str] = ["alpaca", "kraken"]  # default venues

    # Per-venue keys (preferred)
    alpaca_api_key: str | None = None
    alpaca_api_secret: str | None = None
    alpaca_base_url: str = "https://api.alpaca.markets"
    # Websocket endpoint for crypto order book streams.
    alpaca_ws_crypto_url: str = "wss://stream.data.alpaca.markets/v1beta3/crypto/us"
    # Streaming data feed selection (``us`` retail by default, ``sip`` for paid).
    alpaca_data_feed: str = "us"

    kraken_api_key: str | None = None
    kraken_api_secret: str | None = None
    kraken_maker_fee_bps: float | None = None
    kraken_taker_fee_bps: float | None = None

    # Legacy fallback (ARBIT_* → use for both if set)
    arbit_api_key: str | None = None
    arbit_api_secret: str | None = None

    notional_per_trade_usd: float = 200.0
    net_threshold_bps: float = 10.0
    max_slippage_bps: float = 8.0
    max_open_orders: int = 3
    dry_run: bool = True
    reserve_amount_usd: float = 0.0
    reserve_percent: float = 0.0
    # Market data freshness guard (milliseconds)
    max_book_age_ms: int = 1500

    # Aave staking defaults
    usdc_address: str = "0xff970A61a04b1Ca14834A43F5de4533eBDDB5CC8"
    pool_address: str = "0xE0fBa4Fc209b4948668006B2Be61711b7f465bAf"
    atoken_address: str | None = (
        None  # Optional: aToken address for interest-bearing USDC
    )
    min_usdc_stake: int = 100 * 10**6  # 100 USDC (6 decimals)
    min_eth_balance_wei: int = int(0.005 * 10**18)  # 0.005 ETH for gas
    max_gas_price_gwei: int = 5  # Ceiling for gas price to ensure low fees

    prom_port: int = 9109
    sqlite_path: str = "arbit.db"
    discord_webhook_url: str | None = None
    discord_heartbeat_secs: int = 60
    # Discord notifications toggles and rate limits
    discord_trade_notify: bool = False
    discord_skip_notify: bool = True
    discord_error_notify: bool = False
    discord_live_start_notify: bool = True
    discord_live_stop_notify: bool = True
    # Attempt-level notifications (per arbitrage attempt; noisy, opt-in)
    discord_attempt_notify: bool = False
    discord_min_notify_interval_secs: int = 10

    # Optional RPC configuration for on-chain yield ops
    rpc_url: str | None = None
    private_key: str | None = None

    # Optional venue-specific behavior
    alpaca_map_usdt_to_usd: bool = False
    # Prefer native alpaca-py adapter over CCXT for Alpaca (set false to force CCXT)
    alpaca_prefer_native: bool = True
    # Convenience env flag to force CCXT adapter for Alpaca (ALPACA_USE_CCXT=true)
    alpaca_use_ccxt: bool | str | None = None
    # Streaming/attempt freshness controls
    refresh_on_stale: bool = True
    stale_refresh_min_gap_ms: int = 150

    # Per-venue triangle definitions (override via JSON in env if desired)
    # Format: { venue: [[leg_ab, leg_bc, leg_ac], ...], ... }
    triangles_by_venue: dict[str, list[list[str]]] = {
        # Alpaca crypto typically lacks crypto-to-crypto crosses like ETH/BTC.
        # Leave empty by default to avoid unsupported-symbol errors.
        "alpaca": [],
        "kraken": [
            ["ETH/USDT", "ETH/BTC", "BTC/USDT"],
            ["ETH/USDC", "ETH/BTC", "BTC/USDC"],
            # Added SOL triangle candidate
            ["SOL/USDT", "SOL/BTC", "BTC/USDT"],
            # Added DAI-based stable triangle candidate
            ["DAI/USDT", "ETH/DAI", "ETH/USDT"],
            # Added USDC-based stable triangle candidate
            ["USDC/USDT", "ETH/USDC", "ETH/USDT"],
        ],
    }
    # Optional per-venue fee overrides with basis point inputs.
    fee_overrides: dict[str, dict[str, dict[str, float]]] | None = None

    class Config(BaseSettings.Config):
        """Pydantic settings configuration."""

        env_file = ".env"
        env_prefix = ""

    def __init__(self, **kwargs: Any) -> None:
        """Normalise environment-provided configuration values.

        The initializer coerces numeric strings into floats/integers, handles
        boolean toggles expressed as text, expands exchange lists, and sanitises
        optional fee override mappings so downstream consumers can rely on a
        consistent structure.
        """
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

        for f in (
            "notional_per_trade_usd",
            "net_threshold_bps",
            "max_slippage_bps",
            "kraken_maker_fee_bps",
            "kraken_taker_fee_bps",
        ):
            _coerce_float(f)
        for f in ("reserve_amount_usd", "reserve_percent"):
            _coerce_float(f)
        for f in (
            "max_open_orders",
            "prom_port",
            "min_usdc_stake",
            "min_eth_balance_wei",
            "max_gas_price_gwei",
            "max_book_age_ms",
            "log_max_bytes",
            "log_backup_count",
        ):
            _coerce_int(f)
        for b in (
            "dry_run",
            "discord_trade_notify",
            "discord_skip_notify",
            "discord_error_notify",
            "discord_live_start_notify",
            "discord_live_stop_notify",
            "alpaca_map_usdt_to_usd",
        ):
            _coerce_bool(b)

        def _coerce_lower(attr: str, default: str | None = None) -> None:
            v = getattr(self, attr, None)
            if v is None:
                return
            cleaned = str(v).strip()
            if not cleaned and default is None:
                return
            setattr(self, attr, (cleaned or default or "").lower())

        _coerce_lower("alpaca_data_feed", default="us")

        if isinstance(self.exchanges, str):
            try:
                parsed = json.loads(self.exchanges)
            except Exception:
                parsed = [e.strip() for e in self.exchanges.split(",") if e.strip()]
            else:
                if isinstance(parsed, str):
                    parsed = [s.strip() for s in parsed.split(",") if s.strip()]
            if isinstance(parsed, list):
                items = parsed
            else:
                items = [str(parsed)]
        else:
            items = list(self.exchanges)

        # Clean up any stray quotes/brackets from env strings
        cleaned: list[str] = []
        for e in items:
            s = str(e).strip()
            # remove leading/trailing quotes and brackets
            s = s.strip("[] ")
            if (s.startswith('"') and s.endswith('"')) or (
                s.startswith("'") and s.endswith("'")
            ):
                s = s[1:-1]
            s = s.strip().strip("\"'")
            if s:
                cleaned.append(s)
        if cleaned:
            self.exchanges = cleaned

        self.fee_overrides = _normalize_fee_overrides(self.fee_overrides)


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
