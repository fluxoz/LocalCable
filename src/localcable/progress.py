"""Optional progress sink for the startup scan. No-op when nothing is listening."""

from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Callable

Sink = Callable[[float, str], None]

_sink: ContextVar[Sink | None] = ContextVar("localcable_progress_sink", default=None)
_ticker: ContextVar[dict[str, int] | None] = ContextVar("localcable_progress_ticker", default=None)


def bind_progress(sink: Sink) -> tuple[Token[Sink | None], Token[dict[str, int] | None]]:
    ticker = {"done": 0, "known": 0}
    return _sink.set(sink), _ticker.set(ticker)


def unbind_progress(tokens: tuple[Token[Sink | None], Token[dict[str, int] | None]]) -> None:
    sink_token, ticker_token = tokens
    _sink.reset(sink_token)
    _ticker.reset(ticker_token)


def note(fraction: float, message: str) -> None:
    sink = _sink.get()
    if sink is None:
        return
    try:
        sink(float(fraction), message)
    except Exception:  # noqa: BLE001 — progress must not break the scan
        return


def note_files(count: int) -> None:
    ticker = _ticker.get()
    if ticker is None:
        return
    ticker["known"] += max(0, int(count))


def note_probe(name: str) -> None:
    ticker = _ticker.get()
    sink = _sink.get()
    if ticker is None or sink is None:
        return
    ticker["done"] += 1
    total = max(ticker["known"], ticker["done"], 1)
    fraction = 0.18 + 0.72 * (ticker["done"] / total)
    try:
        sink(min(0.93, fraction), f"Probing {ticker['done']}/{total} · {name}")
    except Exception:  # noqa: BLE001 — progress must not break the scan
        return
