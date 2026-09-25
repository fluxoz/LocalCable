"""Folder → channel scan on a real ffmpeg fixture library."""

from __future__ import annotations

from pathlib import Path

import pytest

from localcable.models import Channel
from localcable.scan import (
    format_channel_number,
    pad_channels,
    parse_channel_folder_name,
    scan_media_root,
    stable_channel_number,
)


def test_parse_numbered_prefix():
    assert parse_channel_folder_name("101_CNN") == (101, "CNN")
    assert parse_channel_folder_name("287_MILT") == (287, "MILT")
    assert parse_channel_folder_name("HBO") == (None, "HBO")
    assert parse_channel_folder_name("Discovery") == (None, "Discovery")


def test_scan_numbered_and_unnumbered(media_root: Path):
    channels = scan_media_root(media_root, default_mode="sequential")
    by_name = {ch.name: ch for ch in channels}
    assert set(by_name) == {"CNN", "ALT", "HIST", "Discovery", "HBO"}
    assert by_name["CNN"].number == 101
    assert by_name["ALT"].number == 205
    assert by_name["HIST"].number == 310
    used = {101, 205, 310}
    discovery = stable_channel_number(str(media_root / "Discovery"), used)
    used.add(discovery)
    hbo = stable_channel_number(str(media_root / "HBO"), used)
    assert by_name["Discovery"].number == discovery
    assert by_name["HBO"].number == hbo
    assert by_name["Discovery"].number_explicit is False
    assert by_name["CNN"].number_explicit is True
    assert format_channel_number(discovery) == f"{discovery:03d}"
    assert scan_media_root(media_root)[0].number == channels[0].number
    numbers = [ch.number for ch in channels]
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == len(numbers)


def test_scan_uses_ffprobe_durations(media_root: Path):
    channels = scan_media_root(media_root)
    cnn = next(ch for ch in channels if ch.name == "CNN")
    by_title = {m.title: m for m in cnn.media}
    assert by_title["Evening News"].duration_seconds == pytest.approx(2.0, abs=0.25)
    assert by_title["Late Edition"].duration_seconds == pytest.approx(3.0, abs=0.25)
    hbo = next(ch for ch in channels if ch.name == "HBO")
    assert hbo.media[0].duration_seconds == pytest.approx(5.0, abs=0.25)


def test_playlist_m3u_order(media_root: Path):
    channels = scan_media_root(media_root)
    cnn = next(ch for ch in channels if ch.name == "CNN")
    assert cnn.playlist is not None
    names = [p.name for p in cnn.playlist]
    assert names == ["late_edition.mp4", "evening_news.mp4"]
    # Filename order would have been evening_news then late_edition.


def test_playlist_txt_order(media_root: Path):
    channels = scan_media_root(media_root)
    hist = next(ch for ch in channels if ch.name == "HIST")
    assert hist.playlist is not None
    names = [p.name for p in hist.playlist]
    assert names == ["beta.mp4", "alpha.mp4"]


def test_empty_folder_is_still_a_channel(tmp_path: Path):
    root = tmp_path / "media"
    (root / "101_CNN").mkdir(parents=True)
    (root / "Weather").mkdir(parents=True)
    (root / "205_HBO").mkdir(parents=True)
    channels = scan_media_root(root)
    by_name = {ch.name: ch for ch in channels}
    assert set(by_name) == {"CNN", "Weather", "HBO"}
    assert by_name["CNN"].number == 101
    assert by_name["CNN"].media == []
    assert by_name["HBO"].number == 205
    assert by_name["HBO"].media == []
    weather = stable_channel_number(str(root / "Weather"), {101, 205})
    assert by_name["Weather"].number == weather
    assert by_name["Weather"].media == []
    assert [ch.number for ch in channels] == sorted(ch.number for ch in channels)


def test_pad_channels_repeats_until_minimum():
    src = [
        Channel(number=13, name="Thunderbolt", folder_path=Path("/a")),
        Channel(number=6, name="Chuckle", folder_path=Path("/b")),
    ]
    padded = pad_channels(src, 5)
    assert len(padded) == 5
    names = [ch.name for ch in padded]
    assert "Thunderbolt" in names
    assert "Chuckle" in names
    assert len(set(names)) == 5
    assert "Thunderbolt 2" not in names
    assert "Chuckle 2" not in names
    assert len({ch.number for ch in padded}) == 5
    assert pad_channels(src, 0) == src
    assert pad_channels([], 24) == []


def test_pad_channels_does_not_clone_custom_or_music():
    src = [
        Channel(number=6, name="Chuckle", folder_path=Path("/genre"), pad_source=True),
        Channel(number=101, name="CNN", folder_path=Path("/custom/cnn"), pad_source=False),
        Channel(number=202, name="90s Hits", folder_path=Path("/music/90s"), pad_source=False),
    ]
    padded = pad_channels(src, 6)
    assert len(padded) == 6
    assert [ch.name for ch in padded].count("CNN") == 1
    assert [ch.name for ch in padded].count("90s Hits") == 1
    assert sum(1 for ch in padded if not ch.pad_source) == 2
    assert all(ch.pad_source or ch.name in {"CNN", "90s Hits"} for ch in padded)
    assert pad_channels(
        [Channel(number=1, name="Only Custom", folder_path=Path("/c"), pad_source=False)],
        8,
    )[0].name == "Only Custom"
