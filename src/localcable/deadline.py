"""Bound a call that may ignore its own timeout.

DNS lookups and a subprocess stuck in uninterruptible sleep can sit forever
inside ``urlopen`` or ``subprocess.run`` even when a timeout was requested.
The caller continues; the stuck work is left on a daemon thread.
"""

from __future__ import annotations

import threading
from typing import Callable, TypeVar

T = TypeVar("T")


def call_with_deadline(fn: Callable[[], T], timeout: float, *, default: T | None = None) -> T | None:
    """Return ``fn()`` unless it is still running after ``timeout`` seconds."""
    if timeout < 0:
        timeout = 0.0
    box: dict[str, object] = {}

    def run() -> None:
        try:
            box["value"] = fn()
        except Exception as exc:  # noqa: BLE001 — caller decides
            box["error"] = exc

    thread = threading.Thread(target=run, name="localcable-deadline", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        return default
    if "error" in box:
        raise box["error"]  # type: ignore[misc]
    return box.get("value", default)  # type: ignore[return-value]
