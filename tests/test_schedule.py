"""Sequential / random packers on the shipped generate_schedule path."""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from localcable.models import Channel, MediaFile
from localcable.scan import scan_media_root, stable_channel_number
from localcable.schedule import extend_schedule, generate_schedule, sequence_for_channel


def _window_hours(seconds: float) -> float:
    return seconds / 3600.0


def _assert_abut(programs) -> None:
    for left, right in zip(programs, programs[1:]):
        assert left.end_time == right.start_time
        delta = (left.end_time - left.start_time).total_seconds()
        assert delta == pytest.approx(left.duration_seconds, abs=0.01)


def test_sequential_playlist_order_not_filename_order(media_root: Path, frozen_now: datetime):
    channels = scan_media_root(media_root)
    cnn = next(ch for ch in channels if ch.name == "CNN")
    seq = sequence_for_channel(cnn)
    assert [m.path.name for m in seq] == ["late_edition.mp4", "evening_news.mp4"]
    filename_order = sorted(m.path.name for m in cnn.media)
    assert filename_order == ["evening_news.mp4", "late_edition.mp4"]

    schedule = generate_schedule(
        [cnn],
        now=frozen_now,
        window_hours_before=_window_hours(10),
        window_hours_after=_window_hours(20),
    )
    titles = [p.title for p in schedule.channels[0].programs]
    assert titles[0] == "Late Edition"
    assert titles[1] == "Evening News"


def test_sequential_playlist_txt_order(media_root: Path, frozen_now: datetime):
    channels = scan_media_root(media_root)
    hist = next(ch for ch in channels if ch.name == "HIST")
    schedule = generate_schedule(
        [hist],
        now=frozen_now,
        window_hours_before=_window_hours(5),
        window_hours_after=_window_hours(5),
    )
    titles = [p.title for p in schedule.channels[0].programs]
    assert titles[0] == "Beta"
    assert titles[1] == "Alpha"


def test_sequential_loop_fills_window(media_root: Path, frozen_now: datetime):
    channels = scan_media_root(media_root)
    cnn = next(ch for ch in channels if ch.name == "CNN")
    schedule = generate_schedule(
        [cnn],
        now=frozen_now,
        window_hours_before=_window_hours(10),
        window_hours_after=_window_hours(20),
    )
    programs = schedule.channels[0].programs
    assert programs, "sequential packer produced no programs"
    _assert_abut(programs)
    assert programs[0].start_time == schedule.window_start
    assert programs[-1].end_time >= schedule.window_end
    unique = {p.title for p in programs}
    assert unique == {"Late Edition", "Evening News"}
    # 30s window / 5s cycle → more airings than unique files (loop).
    assert len(programs) > len(cnn.media)
    titles = [p.title for p in programs]
    for i in range(0, (len(titles) // 2) * 2, 2):
        assert titles[i : i + 2] == ["Late Edition", "Evening News"]
    now = schedule.now
    assert any(p.start_time <= now < p.end_time for p in programs)


def test_random_packs_by_duration_without_gaps(media_root: Path, frozen_now: datetime):
    channels = scan_media_root(media_root)
    hist = next(ch for ch in channels if ch.name == "HIST")
    rng = random.Random(0)
    schedule = generate_schedule(
        [hist],
        now=frozen_now,
        window_hours_before=_window_hours(10),
        window_hours_after=_window_hours(20),
        default_mode="random",
        rng=rng,
    )
    programs = schedule.channels[0].programs
    assert programs
    _assert_abut(programs)
    assert programs[0].start_time == schedule.window_start
    assert programs[-1].end_time >= schedule.window_end
    library_titles = {m.title for m in hist.media}
    n = len(hist.media)
    titles = [p.title for p in programs]
    assert len(programs) > n  # window is longer than one pass
    for i in range(0, (len(titles) // n) * n, n):
        assert set(titles[i : i + n]) == library_titles
    now = schedule.now
    assert any(p.start_time <= now < p.end_time for p in programs)


def test_random_padded_clones_get_distinct_schedules(tmp_path: Path, frozen_now: datetime):
    """Genre channels and their padded clones share folder_path + media; each must
    still get a unique random shuffle instead of identical repeated programming."""
    from localcable.models import MediaFile
    from localcable.scan import pad_channels

    root = tmp_path / "lib"
    media = [
        MediaFile(path=root / f"{i}.mp4", title=f"C{i}", duration_seconds=60.0)
        for i in range(6)
    ]
    base = Channel(
        number=6,
        name="Chuckle",
        folder_path=root,
        media=media,
        schedule_mode="random",
    )
    channels = pad_channels([base], 4)
    assert len(channels) == 4

    schedule = generate_schedule(
        channels,
        now=frozen_now,
        window_hours_before=_window_hours(0),
        window_hours_after=_window_hours(600),
    )
    orders = []
    for ch in schedule.channels:
        assert ch.schedule_mode == "random"
        assert ch.programs
        orders.append(tuple(p.title for p in ch.programs))
    # Every clone shares the same media + folder_path, but the schedules must differ.
    assert len(set(orders)) == len(orders)


def test_unnumbered_channel_appears_in_schedule(media_root: Path, frozen_now: datetime):
    channels = scan_media_root(media_root)
    schedule = generate_schedule(
        channels,
        now=frozen_now,
        window_hours_before=_window_hours(8),
        window_hours_after=_window_hours(8),
    )
    names = [ch.name for ch in schedule.channels]
    assert "HBO" in names
    assert "Discovery" in names
    hbo = next(ch for ch in schedule.channels if ch.name == "HBO")
    used = {101, 205, 310}
    discovery_number = stable_channel_number(str(media_root / "Discovery"), used)
    used.add(discovery_number)
    assert hbo.number == stable_channel_number(str(media_root / "HBO"), used)
    assert hbo.programs
    assert hbo.programs[0].title == "Big Movie"


def test_extend_schedule_continues_the_same_lineup(tmp_path: Path, frozen_now: datetime):
    root = tmp_path / "lib"
    media = [
        MediaFile(path=root / f"{name}.mp4", title=name, duration_seconds=60.0)
        for name in ("Alpha", "Beta", "Gamma")
    ]
    sequential = Channel(
        number=2,
        name="Seq",
        folder_path=root,
        media=list(media),
        schedule_mode="sequential",
    )
    shuffled = Channel(
        number=3,
        name="Rnd",
        folder_path=root,
        media=list(media),
        schedule_mode="random",
    )
    schedule = generate_schedule(
        [sequential, shuffled],
        now=frozen_now,
        window_hours_before=1,
        window_hours_after=2,
        rng=random.Random(1),
    )
    before = {ch.number: [p.id for p in ch.programs] for ch in schedule.channels}
    titles = {ch.number: [p.title for p in ch.programs] for ch in schedule.channels}
    old_end = schedule.window_end
    extend_schedule(
        schedule,
        [sequential, shuffled],
        window_end=old_end + timedelta(hours=3),
        keep_after=schedule.window_start,
    )
    assert schedule.window_end >= old_end + timedelta(hours=3)
    assert schedule.pack_start == old_end - timedelta(hours=3)
    for ch in schedule.channels:
        ids = [p.id for p in ch.programs]
        assert ids[: len(before[ch.number])] == before[ch.number]
        assert [p.title for p in ch.programs][: len(titles[ch.number])] == titles[ch.number]
        assert ch.programs[-1].end_time >= old_end + timedelta(hours=3)
        _assert_abut(ch.programs)
        assert any(p.start_time <= frozen_now < p.end_time for p in ch.programs)


def test_extend_schedule_drops_airings_older_than_the_horizon(tmp_path: Path, frozen_now: datetime):
    root = tmp_path / "lib"
    channel = Channel(
        number=4,
        name="Seq",
        folder_path=root,
        media=[MediaFile(path=root / "a.mp4", title="Alpha", duration_seconds=60.0)],
        schedule_mode="sequential",
    )
    schedule = generate_schedule(
        [channel],
        now=frozen_now,
        window_hours_before=1,
        window_hours_after=1,
    )
    kept = next(p for p in schedule.channels[0].programs if p.start_time <= frozen_now < p.end_time)
    extend_schedule(
        schedule,
        [channel],
        window_end=schedule.window_end + timedelta(hours=1),
        keep_after=frozen_now,
    )
    ids = [p.id for p in schedule.channels[0].programs]
    assert kept.id in ids
    assert all(p.end_time > frozen_now for p in schedule.channels[0].programs)
    assert schedule.window_start == frozen_now
    _assert_abut(schedule.channels[0].programs)


def test_empty_channel_appears_with_no_programs(tmp_path: Path, frozen_now: datetime):
    empty = Channel(
        number=42,
        name="GAP",
        folder_path=tmp_path / "42_GAP",
        media=[],
    )
    filled = Channel(
        number=101,
        name="CNN",
        folder_path=tmp_path / "101_CNN",
        media=[],
    )
    schedule = generate_schedule(
        [empty, filled],
        now=frozen_now,
        window_hours_before=_window_hours(8),
        window_hours_after=_window_hours(8),
    )
    names = [ch.name for ch in schedule.channels]
    assert names == ["GAP", "CNN"]
    gap = schedule.channels[0]
    assert gap.number == 42
    assert gap.programs == []
