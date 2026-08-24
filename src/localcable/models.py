"""Domain objects for channels, programs, and the rolling guide schedule."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

ScheduleMode = Literal["sequential", "random"]


def isoformat_local(dt: datetime) -> str:
    """RFC 3339 with offset, seconds only — JS Date() parses this reliably."""
    if dt.tzinfo is None:
        dt = dt.astimezone()
    return dt.isoformat(timespec="seconds")


@dataclass
class MediaFile:
    path: Path
    title: str
    duration_seconds: float
    description: str | None = None
    rating: str | None = None
    genre: str | None = None
    year: str | None = None


@dataclass
class Channel:
    number: int
    name: str
    folder_path: Path
    media: list[MediaFile] = field(default_factory=list)
    schedule_mode: ScheduleMode = "sequential"
    playlist: list[Path] | None = None


@dataclass
class ScheduledProgram:
    id: str
    title: str
    description: str | None
    rating: str | None
    genre: str | None
    duration_seconds: float
    file_path: Path
    start_time: datetime
    end_time: datetime
    channel_number: int
    channel_name: str

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "rating": self.rating,
            "genre": self.genre,
            "duration_seconds": self.duration_seconds,
            "file_path": str(self.file_path),
            "start_time": isoformat_local(self.start_time),
            "end_time": isoformat_local(self.end_time),
            "channel_number": self.channel_number,
            "channel_name": self.channel_name,
            "art": f"/art/{self.id}",
        }


@dataclass
class ChannelSchedule:
    number: int
    name: str
    folder_path: Path
    schedule_mode: ScheduleMode
    programs: list[ScheduledProgram] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "number": self.number,
            "name": self.name,
            "folder_path": str(self.folder_path),
            "schedule_mode": self.schedule_mode,
            "programs": [p.to_dict() for p in self.programs],
        }


@dataclass
class GuideSchedule:
    now: datetime
    window_start: datetime
    window_end: datetime
    channels: list[ChannelSchedule] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "now": isoformat_local(self.now),
            "window_start": isoformat_local(self.window_start),
            "window_end": isoformat_local(self.window_end),
            "channels": [ch.to_dict() for ch in self.channels],
        }
