"""IR-remote actions: channel tune, CH+/CH−, and optional evdev grab.

A remote that already types like a keyboard is handled in the guide JS and
mpv lua. This module is the shared action layer (and an optional dedicated
device listener) so the same CH+/digits work while video has focus.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import Any, Callable

from localcable.models import ChannelSchedule, ScheduledProgram

log = logging.getLogger(__name__)

ACTIONS = frozenset(
    {
        "guide",
        "back",
        "exit",
        "ok",
        "play",
        "info",
        "channel-up",
        "channel-down",
        "digit",
        "tune",
        "select",
    }
)

KEY_TO_ACTION: dict[str, str] = {
    "escape": "guide",
    "esc": "guide",
    "goback": "guide",
    "browserback": "guide",
    "backspace": "guide",
    "mediaguide": "guide",
    "guide": "guide",
    "epg": "guide",
    "menu": "guide",
    "contextmenu": "guide",
    "home": "guide",
    "gohome": "guide",
    "enter": "ok",
    " ": "ok",
    "space": "ok",
    "spacebar": "ok",
    "select": "ok",
    "ok": "ok",
    "channelup": "channel-up",
    "channeldown": "channel-down",
    "pageup": "channel-up",
    "pagedown": "channel-down",
    "mediaplay": "play",
    "mediapause": "play",
    "mediaplaypause": "play",
    "info": "info",
    "f1": "info",
    "i": "info",
    "g": "guide",
}

EVDEV_KEY_ACTIONS: dict[str, str] = {
    "KEY_CHANNELUP": "channel-up",
    "KEY_CHANNELDOWN": "channel-down",
    "KEY_OK": "ok",
    "KEY_SELECT": "ok",
    "KEY_ENTER": "ok",
    "KEY_KPENTER": "ok",
    "KEY_EXIT": "guide",
    "KEY_BACK": "guide",
    "KEY_ESC": "guide",
    "KEY_EPG": "guide",
    "KEY_TV": "guide",
    "KEY_MENU": "guide",
    "KEY_INFO": "info",
    "KEY_DISPLAY": "info",
    "KEY_PLAY": "play",
    "KEY_PLAYPAUSE": "play",
    "KEY_PAUSE": "play",
}


def normalize_action(
    action: str | None = None,
    *,
    key: str | None = None,
    digit: str | None = None,
) -> tuple[str, str | None]:
    """Return (action, digit) from a remote request."""
    if digit is not None and str(digit).isdigit():
        return "digit", str(digit)[-1]
    if key:
        text = str(key).strip()
        if len(text) == 1 and text.isdigit():
            return "digit", text
        if text.lower().startswith("digit") and text[-1].isdigit():
            return "digit", text[-1]
        mapped = KEY_TO_ACTION.get(text.lower())
        if mapped:
            return mapped, None
    if action:
        name = str(action).strip().lower().replace("_", "-")
        if name in {"ch+", "ch-up", "chan-up"}:
            name = "channel-up"
        if name in {"ch-", "ch-down", "chan-down"}:
            name = "channel-down"
        if name in ACTIONS:
            return name, None
    raise ValueError("unknown remote action")


def match_channel_number(numbers: list[int], buf: str) -> int | None:
    """Resolve a typed channel buffer the way a cable box does."""
    if not buf or not buf.isdigit() or not numbers:
        return None
    typed = int(buf)
    if typed in numbers:
        return typed
    prefixes = [n for n in numbers if str(n).startswith(buf)]
    if len(prefixes) == 1:
        return prefixes[0]
    return min(numbers, key=lambda n: (abs(n - typed), n))


def step_channel(numbers: list[int], current: int | None, delta: int) -> int | None:
    if not numbers:
        return None
    ordered = sorted(numbers)
    if current not in ordered:
        return ordered[0] if delta >= 0 else ordered[-1]
    idx = ordered.index(current)
    return ordered[(idx + delta) % len(ordered)]


def program_airing_on(channel: ChannelSchedule, now: datetime) -> ScheduledProgram | None:
    for program in channel.programs:
        if program.start_time <= now < program.end_time:
            return program
    if channel.programs:
        return channel.programs[0]
    return None


def max_channel_digits(numbers: list[int]) -> int:
    if not numbers:
        return 1
    return max(len(str(n)) for n in numbers)


def start_evdev_listener(
    device: str,
    handler: Callable[..., Any],
    *,
    stop_event: threading.Event | None = None,
) -> threading.Event:
    """Grab *device* and dispatch KEY_* presses. Optional extra: ``evdev``."""
    stop = stop_event or threading.Event()

    def _run() -> None:
        try:
            import evdev  # type: ignore[import-not-found]
            from evdev import categorize, ecodes
        except ImportError:
            log.warning("remote.device is set but python-evdev is not installed")
            return
        try:
            dev = evdev.InputDevice(device)
            dev.grab()
        except OSError as exc:
            log.warning("cannot open IR device %s: %s", device, exc)
            return
        log.info("IR remote listening on %s (%s)", device, getattr(dev, "name", ""))
        try:
            for event in dev.read_loop():
                if stop.is_set():
                    break
                if event.type != ecodes.EV_KEY:
                    continue
                key = categorize(event)
                if getattr(key, "keystate", None) != 1:
                    continue
                code = getattr(key, "keycode", None)
                if isinstance(code, (list, tuple)):
                    code = code[0] if code else ""
                name = str(code)
                if name.startswith("KEY_") and name[4:].isdigit():
                    handler(action="digit", digit=name[4:])
                    continue
                if name.startswith("KEY_NUMERIC_") and name.split("_")[-1].isdigit():
                    handler(action="digit", digit=name.split("_")[-1])
                    continue
                action = EVDEV_KEY_ACTIONS.get(name)
                if action:
                    handler(action=action)
        except OSError as exc:
            log.warning("IR remote listener stopped: %s", exc)
        finally:
            try:
                dev.ungrab()
            except OSError:
                pass
            try:
                dev.close()
            except OSError:
                pass

    thread = threading.Thread(target=_run, name="localcable-ir", daemon=True)
    thread.start()
    return stop
