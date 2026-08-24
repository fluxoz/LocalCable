"""Shared helpers."""

from __future__ import annotations

import re
import socket
from pathlib import Path


def natural_key(value: str) -> list:
    """Split a string into text/int chunks for natural filename sort."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def natural_sort_key_path(path: Path) -> list:
    return natural_key(path.name)


def live_offset_seconds(
    start,
    now,
    duration_seconds: float,
    *,
    end=None,
) -> float:
    """Seconds into a program that matches wall-clock time on the guide.

    Past and future airings start at 0. An airing in progress joins at *now*.
    """
    elapsed = (now - start).total_seconds()
    if elapsed <= 1:
        return 0.0
    duration = float(duration_seconds or 0.0)
    if duration <= 0 and end is not None:
        duration = (end - start).total_seconds()
    if duration <= 2:
        return 0.0
    if elapsed >= duration - 1:
        return 0.0
    return float(elapsed)


def lan_ipv4_addresses() -> list[str]:
    """Best-effort LAN IPv4 addresses for this machine (never includes loopback)."""
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("1.1.1.1", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                found.append(ip)
    except OSError:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in found:
                found.append(ip)
    except OSError:
        pass
    return found
