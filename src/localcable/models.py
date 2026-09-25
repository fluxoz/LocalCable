"""Domain objects for channels, programs, and the rolling guide schedule."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

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
    video_codec: str | None = None
    audio_codec: str | None = None
    mse_copy: bool | None = None
    show_title: str | None = None
    season: int | None = None
    episode: int | None = None
    episode_title: str | None = None
    renditions: list[dict] = field(default_factory=list)


@dataclass
class Channel:
    number: int
    name: str
    folder_path: Path
    media: list[MediaFile] = field(default_factory=list)
    schedule_mode: ScheduleMode = "sequential"
    playlist: list[Path] | None = None
    # True when the number came from an NNN_ folder or an explicit lineup number.
    number_explicit: bool = False


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
    mse_copy: bool | None = None
    show_title: str | None = None
    season: int | None = None
    episode: int | None = None
    episode_title: str | None = None
    renditions: list[dict] = field(default_factory=list)

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
            "show_title": self.show_title,
            "season": self.season,
            "episode": self.episode,
            "episode_title": self.episode_title,
            "renditions": list(self.renditions),
        }


@dataclass
class ChannelSchedule:
    number: int
    name: str
    folder_path: Path
    schedule_mode: ScheduleMode
    programs: list[ScheduledProgram] = field(default_factory=list)
    # RNG snapshot from before this channel was packed, so a later extend
    # replays the same shuffle and only the tail is new. Not sent to the client.
    pack_rng_state: Any | None = None

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
    # Original pack anchor. window_start moves forward as old airings drop off;
    # pack_start stays put so a replay continues the same timeline.
    pack_start: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "now": isoformat_local(self.now),
            "window_start": isoformat_local(self.window_start),
            "window_end": isoformat_local(self.window_end),
            "channels": [ch.to_dict() for ch in self.channels],
        }
