"""Shared helpers."""

from __future__ import annotations

import re
from pathlib import Path


def natural_key(value: str) -> list:
    """Split a string into text/int chunks for natural filename sort."""
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def natural_sort_key_path(path: Path) -> list:
    return natural_key(path.name)
