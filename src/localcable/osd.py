"""Now-playing overlay payload written for the mpv lua OSD."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from localcable.models import ScheduledProgram


def format_clock(dt: datetime) -> str:
    h = dt.hour
    m = dt.minute
    ampm = "pm" if h >= 12 else "am"
    h = h % 12 or 12
    return f"{h}:{m:02d}{ampm}"


def format_range(start: datetime, end: datetime) -> str:
    return f"{format_clock(start)} – {format_clock(end)}"


def osd_payload_from_program(program: ScheduledProgram) -> dict[str, Any]:
    desc = program.description or ""
    if len(desc) > 160:
        desc = desc[:157].rstrip() + "..."
    number = program.channel_number
    return {
        "title": program.title or "",
        "channel_name": program.channel_name or "",
        "channel_number": "" if number is None else str(number),
        "rating": program.rating or "",
        "description": desc,
        "time_range": format_range(program.start_time, program.end_time),
        "path": str(program.file_path),
    }


def osd_payload_from_path(path: Path | str) -> dict[str, Any]:
    p = Path(path)
    title = p.stem.replace("_", " ").replace(".", " ").strip() or p.name
    return {
        "title": title,
        "channel_name": "",
        "channel_number": "",
        "rating": "",
        "description": "",
        "time_range": "",
        "path": str(p),
    }


def write_osd_state(path: Path | str, payload: dict[str, Any]) -> Path:
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(dest)
    return dest
