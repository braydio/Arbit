import pytest


def test_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pydantic")
    from arbit.config import Settings

    monkeypatch.setenv("ARBIT_API_KEY", "k")
    monkeypatch.setenv("ARBIT_API_SECRET", "s")
    monkeypatch.setenv("ARBIT_USDC_ADDRESS", "0xusdc")
    monkeypatch.setenv("ARBIT_POOL_ADDRESS", "0xpool")
    monkeypatch.setenv("ARBIT_USDC_ABI_PATH", "erc20.json")
    monkeypatch.setenv("ARBIT_POOL_ABI_PATH", "pool.json")
    settings = Settings()
    assert settings.api_key == "k"
    assert settings.api_secret == "s"
    assert settings.net_threshold == 0.001
    assert settings.data_dir.name == "data"
    assert settings.usdc_address == "0xusdc"
    assert settings.pool_address == "0xpool"
    assert settings.usdc_abi_path == "erc20.json"
    assert settings.pool_abi_path == "pool.json"
