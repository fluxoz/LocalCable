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
        show_title=media.show_title,
        season=media.season,
        episode=media.episode,
        episode_title=media.episode_title,
        renditions=list(media.renditions),
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
        rng_state = None
        if mode == "random":
            channel_rng = _channel_rng(channel, window_start, rng)
            rng_state = channel_rng.getstate()
            programs = pack_random(
                channel.media,
                channel=channel,
                window_start=window_start,
                window_end=window_end,
                rng=channel_rng,
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
                pack_rng_state=rng_state,
            )
        )
    packed.sort(key=lambda ch: (ch.number, natural_key(ch.name)))
    return GuideSchedule(
        now=now,
        window_start=window_start,
        window_end=window_end,
        channels=packed,
        pack_start=window_start,
    )


def _pack_channel(
    packed: ChannelSchedule,
    channel: Channel,
    anchor: datetime,
    window_end: datetime,
) -> list[ScheduledProgram]:
    if packed.schedule_mode == "random":
        channel_rng = random.Random()
        if packed.pack_rng_state is not None:
            try:
                channel_rng.setstate(packed.pack_rng_state)
            except (TypeError, ValueError):
                channel_rng = _channel_rng(channel, anchor, None)
        else:
            channel_rng = _channel_rng(channel, anchor, None)
        return pack_random(
            channel.media,
            channel=channel,
            window_start=anchor,
            window_end=window_end,
            rng=channel_rng,
        )
    return pack_sequential(
        channel.media,
        channel=channel,
        window_start=anchor,
        window_end=window_end,
    )


def _extends(existing: list[ScheduledProgram], fresh: list[ScheduledProgram]) -> bool:
    """True when every existing airing still appears, in order, in *fresh*."""
    if not existing:
        return True
    positions = {program.id: index for index, program in enumerate(fresh)}
    last = -1
    for program in existing:
        index = positions.get(program.id)
        if index is None or index <= last:
            return False
        last = index
    return True


def _append_unaligned(
    packed: ChannelSchedule,
    channel: Channel,
    window_end: datetime,
) -> list[ScheduledProgram]:
    """Media changed under a live guide. Keep the airings already on screen and fill the tail."""
    existing = list(packed.programs)
    if not existing:
        return existing
    cursor = existing[-1].end_time
    if cursor >= window_end:
        return existing
    if packed.schedule_mode == "random":
        tail_rng = _channel_rng(channel, cursor, None)
        tail = pack_random(
            channel.media,
            channel=channel,
            window_start=cursor,
            window_end=window_end,
            rng=tail_rng,
        )
    else:
        tail = pack_sequential(
            channel.media,
            channel=channel,
            window_start=cursor,
            window_end=window_end,
        )
    seen = {program.id for program in existing}
    for program in tail:
        if program.id in seen or program.start_time < cursor:
            continue
        existing.append(program)
        seen.add(program.id)
    return existing


def extend_schedule(
    schedule: GuideSchedule,
    channels: list[Channel],
    *,
    window_end: datetime,
    keep_after: datetime | None = None,
) -> GuideSchedule:
    """Append airings through *window_end* without renumbering the ones already packed.

    Random channels replay the shuffle captured at generation, so the overlap
    stays put and only the tail is new. *keep_after* drops airings that ended
    before the visible past horizon. *pack_start* does not move.
    """
    if schedule.pack_start is None:
        schedule.pack_start = schedule.window_start
    anchor = schedule.pack_start
    target_end = max(schedule.window_end, window_end)
    by_number = {channel.number: channel for channel in channels}
    for packed in schedule.channels:
        channel = by_number.get(packed.number)
        if channel is None or target_end <= schedule.window_end:
            programs = list(packed.programs)
        else:
            fresh = _pack_channel(packed, channel, anchor, target_end)
            programs = fresh if _extends(packed.programs, fresh) else _append_unaligned(packed, channel, target_end)
        if keep_after is not None:
            programs = [program for program in programs if program.end_time > keep_after]
        packed.programs = programs
    if target_end > schedule.window_end:
        schedule.window_end = target_end
    if keep_after is not None and keep_after > schedule.window_start:
        schedule.window_start = keep_after
    return schedule
