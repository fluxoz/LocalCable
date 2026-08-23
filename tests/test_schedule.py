"""Sequential / random packers on the shipped generate_schedule path."""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

import pytest

from localcable.scan import scan_media_root
from localcable.schedule import generate_schedule, sequence_for_channel


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
    assert hbo.number == 2
    assert hbo.programs
    assert hbo.programs[0].title == "Big Movie"
