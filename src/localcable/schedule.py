"""Rolling-window schedule packers (sequential + random)."""

from __future__ import annotations

import hashlib
import logging
import random
from datetime import datetime, timedelta
from pathlib import Path

from localcable.models import (
    Channel,
    ChannelSchedule,
    GuideSchedule,
    MediaFile,
    ScheduledProgram,
    ScheduleMode,
)
from localcable.util import natural_key

log = logging.getLogger(__name__)

MAX_AIRINGS_PER_CHANNEL = 100_000


def make_program_id(channel_number: int, file_path: Path, start: datetime) -> str:
    raw = f"{channel_number}|{file_path}|{start.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def sequence_for_channel(channel: Channel, media: list[MediaFile] | None = None) -> list[MediaFile]:
    """Playlist order when present and usable; otherwise natural filename order."""
    files = list(media if media is not None else channel.media)
    by_path = {item.path.resolve(): item for item in files}
    if channel.playlist:
        ordered: list[MediaFile] = []
        seen: set[Path] = set()
        for entry in channel.playlist:
            try:
                resolved = Path(entry).resolve()
            except OSError:
                resolved = Path(entry)
            item = by_path.get(resolved)
            if item is not None and item.path.resolve() not in seen:
                ordered.append(item)
                seen.add(item.path.resolve())
        if ordered:
            return ordered
    return sorted(files, key=lambda item: natural_key(item.path.name))


def _airing(media: MediaFile, channel: Channel, start: datetime) -> ScheduledProgram:
    end = start + timedelta(seconds=float(media.duration_seconds))
    return ScheduledProgram(
        id=make_program_id(channel.number, media.path, start),
        title=media.title,
        description=media.description,
        rating=media.rating,
        genre=media.genre,
        duration_seconds=float(media.duration_seconds),
        file_path=media.path,
        start_time=start,
        end_time=end,
        channel_number=channel.number,
        channel_name=channel.name,
        mse_copy=media.mse_copy,
    )


def pack_sequential(
    media: list[MediaFile],
    *,
    channel: Channel,
    window_start: datetime,
    window_end: datetime,
) -> list[ScheduledProgram]:
    """Loop playlist / filename order from *window_start* until the window is covered."""
    sequence = sequence_for_channel(channel, media)
    if not sequence:
        return []
    programs: list[ScheduledProgram] = []
    cursor = window_start
    index = 0
    n = len(sequence)
    guard = 0
    while cursor < window_end and guard < MAX_AIRINGS_PER_CHANNEL:
        item = sequence[index % n]
        duration = float(item.duration_seconds)
        if duration <= 0:
            index += 1
            guard += 1
            continue
        programs.append(_airing(item, channel, cursor))
        cursor = cursor + timedelta(seconds=duration)
        index += 1
        guard += 1
    return programs


def pack_random(
    media: list[MediaFile],
    *,
    channel: Channel,
    window_start: datetime,
    window_end: datetime,
    rng: random.Random,
) -> list[ScheduledProgram]:
    """Shuffle, pack end-to-end by real duration, re-shuffle when the bag is empty."""
    library = [item for item in media if float(item.duration_seconds) > 0]
    if not library:
        return []
    programs: list[ScheduledProgram] = []
    cursor = window_start
    bag: list[MediaFile] = []
    guard = 0
    while cursor < window_end and guard < MAX_AIRINGS_PER_CHANNEL:
        if not bag:
            bag = list(library)
            rng.shuffle(bag)
        item = bag.pop(0)
        duration = float(item.duration_seconds)
        programs.append(_airing(item, channel, cursor))
        cursor = cursor + timedelta(seconds=duration)
        guard += 1
    return programs


def _channel_rng(channel: Channel, window_start: datetime, rng: random.Random | None) -> random.Random:
    if rng is not None:
        return rng
    # Include the channel number and name so genre channels (which all share the
    # library root as folder_path) and padded clones each get a distinct shuffle
    # instead of identical random programming.
    seed_src = f"{channel.number}|{channel.name}|{channel.folder_path}|{window_start.isoformat()}"
    seed = int(hashlib.sha256(seed_src.encode("utf-8")).hexdigest()[:16], 16)
    return random.Random(seed)


def generate_schedule(
    channels: list[Channel],
    *,
    now: datetime,
    window_hours_before: float = 6.0,
    window_hours_after: float = 18.0,
    default_mode: str | None = None,
    rng: random.Random | None = None,
) -> GuideSchedule:
    """Place every channel's programs into [now-before, now+after]."""
    window_start = now - timedelta(hours=float(window_hours_before))
    window_end = now + timedelta(hours=float(window_hours_after))
    packed: list[ChannelSchedule] = []
    for channel in channels:
        mode: ScheduleMode
        if default_mode:
            mode = "random" if str(default_mode).lower() == "random" else "sequential"
        else:
            mode = channel.schedule_mode
        if mode == "random":
            programs = pack_random(
                channel.media,
                channel=channel,
                window_start=window_start,
                window_end=window_end,
                rng=_channel_rng(channel, window_start, rng),
            )
        else:
            programs = pack_sequential(
                channel.media,
                channel=channel,
                window_start=window_start,
                window_end=window_end,
            )
        packed.append(
            ChannelSchedule(
                number=channel.number,
                name=channel.name,
                folder_path=channel.folder_path,
                schedule_mode=mode,
                programs=programs,
            )
        )
    packed.sort(key=lambda ch: (ch.number, natural_key(ch.name)))
    return GuideSchedule(
        now=now,
        window_start=window_start,
        window_end=window_end,
        channels=packed,
    )
