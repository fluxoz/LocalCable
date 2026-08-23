"""Folder → channel scan on a real ffmpeg fixture library."""

from __future__ import annotations

from pathlib import Path

import pytest

from localcable.scan import parse_channel_folder_name, scan_media_root


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
    # Unnumbered folders are sorted by name, then given unused numbers from 1.
    assert by_name["Discovery"].number == 1
    assert by_name["HBO"].number == 2
    numbers = [ch.number for ch in channels]
    assert numbers == sorted(numbers)


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
