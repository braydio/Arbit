"""Minimal Prometheus client stub for tests."""

class _Value:
    def __init__(self) -> None:
        self._v = 0.0

    def get(self) -> float:
        return self._v


class _Metric:
    def __init__(self, *args, **kwargs) -> None:
        self._value = _Value()

    def inc(self, amount: float = 1.0) -> None:  # pragma: no cover - trivial
        self._value._v += amount

    def set(self, value: float) -> None:  # pragma: no cover - trivial
        self._value._v = value

Counter = Gauge = _Metric


def start_http_server(port: int) -> None:  # pragma: no cover - no-op
    pass
