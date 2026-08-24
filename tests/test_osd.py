"""Now-playing overlay payload for the mpv OSD."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from localcable.models import ScheduledProgram
from localcable.osd import (
    format_clock,
    format_range,
    osd_payload_from_path,
    osd_payload_from_program,
    write_osd_state,
)


def test_format_clock_12h():
    assert format_clock(datetime(2026, 8, 23, 15, 5, tzinfo=timezone.utc)) == "3:05pm"
    assert format_clock(datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)) == "12:00am"
    assert format_range(
        datetime(2026, 8, 23, 14, 50, tzinfo=timezone.utc),
        datetime(2026, 8, 23, 15, 0, tzinfo=timezone.utc),
    ) == "2:50pm – 3:00pm"


def test_payload_from_program_and_write(tmp_path: Path):
    program = ScheduledProgram(
        id="p1",
        title="Evening News",
        description="A fixture newscast.",
        rating="TV-G",
        genre=None,
        duration_seconds=600,
        file_path=tmp_path / "evening_news.mp4",
        start_time=datetime(2026, 8, 23, 14, 50, tzinfo=timezone.utc),
        end_time=datetime(2026, 8, 23, 15, 0, tzinfo=timezone.utc),
        channel_number=101,
        channel_name="CNN",
    )
    payload = osd_payload_from_program(program)
    assert payload["title"] == "Evening News"
    assert payload["channel_number"] == "101"
    assert payload["channel_name"] == "CNN"
    assert payload["rating"] == "TV-G"
    assert "2:50pm" in payload["time_range"]
    dest = write_osd_state(tmp_path / "osd.json", payload)
    data = json.loads(dest.read_text(encoding="utf-8"))
    assert data["title"] == "Evening News"


def test_payload_from_path_uses_filename(tmp_path: Path):
    payload = osd_payload_from_path(tmp_path / "late_edition.mp4")
    assert payload["title"] == "late edition"
    assert payload["channel_number"] == ""
