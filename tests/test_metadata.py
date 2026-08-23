"""Filename heuristics + real ffprobe — missing tags must not raise."""

from __future__ import annotations

from pathlib import Path

import pytest

from localcable.metadata import clean_filename_title, probe_media
from tests.helpers import make_video


def test_clean_filename_title_underscores_and_extension():
    assert clean_filename_title("evening_news.mkv") == "Evening News"
    assert clean_filename_title("late_edition.mp4") == "Late Edition"
    assert clean_filename_title("big_movie.mp4") == "Big Movie"


def test_ffprobe_duration_matches_file(tmp_path: Path):
    path = make_video(tmp_path / "clip.mp4", 2.0, color="blue")
    media = probe_media(path)
    assert media is not None
    assert media.duration_seconds == pytest.approx(2.0, abs=0.25)
    assert media.path.resolve() == path.resolve()


def test_cleaned_filename_title_when_tags_absent(tmp_path: Path):
    path = make_video(tmp_path / "evening_news.mp4", 2.0)
    media = probe_media(path)
    assert media is not None
    assert media.title == "Evening News"


def test_embedded_title_wins_over_filename(tmp_path: Path):
    path = make_video(tmp_path / "evening_news.mp4", 2.0, title="Nightly News")
    media = probe_media(path)
    assert media is not None
    assert media.title == "Nightly News"


def test_missing_description_and_rating_do_not_raise(tmp_path: Path):
    path = make_video(tmp_path / "untagged_show.mp4", 3.0, color="red")
    media = probe_media(path)
    assert media is not None
    assert media.description is None
    assert media.rating is None
    assert media.genre is None
    assert media.title
    assert media.duration_seconds == pytest.approx(3.0, abs=0.25)
