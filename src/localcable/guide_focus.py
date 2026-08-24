"""Raise the LocalCable guide window without touching the mpv player."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import webbrowser
from typing import Any, Callable

GUIDE_WINDOW_TITLE = "LocalCable Guide"


def _title_matches(title: str | None, needle: str) -> bool:
    if not title:
        return False
    return needle.lower() in str(title).lower()


def focus_guide_window(
    *,
    title: str = GUIDE_WINDOW_TITLE,
    url: str | None = None,
    run: Callable[..., Any] | None = None,
    which: Callable[[str], str | None] | None = None,
    open_url: Callable[[str], Any] | None = None,
    environ: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Focus the existing guide window. Never sends commands to mpv."""
    run_fn = run or subprocess.run
    which_fn = which or shutil.which
    env = environ if environ is not None else os.environ

    niri = _try_niri(title, run_fn, which_fn, env)
    if niri:
        return niri
    kdo = _try_kdotool(title, run_fn, which_fn)
    if kdo:
        return kdo
    wm = _try_wmctrl(title, run_fn, which_fn)
    if wm:
        return wm
    xdo = _try_xdotool(title, run_fn, which_fn)
    if xdo:
        return xdo

    if url:
        opener = open_url or webbrowser.open
        opener(url)
        return {"ok": True, "method": "open_url"}
    return {"ok": False, "method": None}


def _run_ok(run: Callable[..., Any], argv: list[str], **kwargs: Any) -> Any:
    return run(argv, capture_output=True, text=True, timeout=1.5, check=False, **kwargs)


def _try_niri(
    title: str,
    run: Callable[..., Any],
    which: Callable[[str], str | None],
    env: dict[str, str],
) -> dict[str, Any] | None:
    if not env.get("NIRI_SOCKET") or not which("niri"):
        return None
    try:
        listed = _run_ok(run, ["niri", "msg", "--json", "windows"])
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return None
    if getattr(listed, "returncode", 1) != 0 or not getattr(listed, "stdout", ""):
        return None
    try:
        windows = json.loads(listed.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(windows, list):
        return None
    for window in windows:
        if not isinstance(window, dict):
            continue
        if not _title_matches(window.get("title"), title):
            continue
        wid = window.get("id")
        if wid is None:
            continue
        try:
            focused = _run_ok(run, ["niri", "msg", "action", "focus-window", "--id", str(wid)])
        except (OSError, subprocess.SubprocessError, TimeoutError):
            return None
        if getattr(focused, "returncode", 1) == 0:
            return {"ok": True, "method": "niri"}
    return None


def _try_kdotool(
    title: str,
    run: Callable[..., Any],
    which: Callable[[str], str | None],
) -> dict[str, Any] | None:
    if not which("kdotool"):
        return None
    try:
        found = _run_ok(run, ["kdotool", "search", "--title", title])
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return None
    ids = [line.strip() for line in (getattr(found, "stdout", "") or "").splitlines() if line.strip()]
    if getattr(found, "returncode", 1) != 0 or not ids:
        return None
    try:
        activated = _run_ok(run, ["kdotool", "windowactivate", ids[0]])
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return None
    if getattr(activated, "returncode", 1) == 0:
        return {"ok": True, "method": "kdotool"}
    return None


def _try_wmctrl(
    title: str,
    run: Callable[..., Any],
    which: Callable[[str], str | None],
) -> dict[str, Any] | None:
    if not which("wmctrl"):
        return None
    try:
        result = _run_ok(run, ["wmctrl", "-a", title])
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return None
    if getattr(result, "returncode", 1) == 0:
        return {"ok": True, "method": "wmctrl"}
    return None


def _try_xdotool(
    title: str,
    run: Callable[..., Any],
    which: Callable[[str], str | None],
) -> dict[str, Any] | None:
    if not which("xdotool"):
        return None
    try:
        result = _run_ok(run, ["xdotool", "search", "--name", title, "windowactivate"])
    except (OSError, subprocess.SubprocessError, TimeoutError):
        return None
    if getattr(result, "returncode", 1) == 0:
        return {"ok": True, "method": "xdotool"}
    return None
