import sys
import types
from typing import Any, Dict


class DummyExchange:
    def load_markets(self) -> Dict[str, Dict[str, Any]]:
        return {"BTC/USD": {"symbol": "BTC/USD"}}


def test_ccxt_adapter_load_markets(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "arbit.config",
        types.SimpleNamespace(
            creds_for=lambda ex: ("k", "s"),
            settings=types.SimpleNamespace(alpaca_map_usdt_to_usd=False),
        ),
    )
    sys.modules.pop("arbit.adapters.ccxt_adapter", None)
    from arbit.adapters.ccxt_adapter import CCXTAdapter

    adapter = CCXTAdapter.__new__(CCXTAdapter)
    adapter.ex = DummyExchange()  # type: ignore[attr-defined]
    assert adapter.load_markets()["BTC/USD"]["symbol"] == "BTC/USD"


def test_alpaca_adapter_load_markets(monkeypatch) -> None:
    from arbit.adapters import alpaca_adapter as aa
    from tests.alpaca_mocks import MockTradingClient

    monkeypatch.setattr(
        aa, "settings", types.SimpleNamespace(alpaca_map_usdt_to_usd=True)
    )
    adapter = aa.AlpacaAdapter.__new__(aa.AlpacaAdapter)
    adapter._markets = None  # type: ignore[attr-defined]
    adapter.trading = MockTradingClient()  # type: ignore[attr-defined]

    class DummyEnum:
        ACTIVE = "ACTIVE"
        CRYPTO = "CRYPTO"

    monkeypatch.setattr(aa, "GetAssetsRequest", lambda **_: object())
    monkeypatch.setattr(aa, "AssetStatus", DummyEnum)
    monkeypatch.setattr(aa, "AssetClass", DummyEnum)

    markets = adapter.load_markets()
    assert {"BTC/USD", "ETH/USD", "BTC/USDT", "ETH/USDT"}.issubset(markets)
