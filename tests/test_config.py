import pytest


def test_settings_env(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("pydantic")
    from arbit.config import Settings

    monkeypatch.setenv("ARBIT_API_KEY", "k")
    monkeypatch.setenv("ARBIT_API_SECRET", "s")
    settings = Settings()
    assert settings.api_key == "k"
    assert settings.api_secret == "s"
    assert settings.net_threshold == 0.001
    assert settings.data_dir.name == "data"
