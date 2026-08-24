"""Filename heuristics + real ffprobe — missing tags must not raise."""

from __future__ import annotations

from pathlib import Path

import pytest

from localcable.metadata import clean_filename_title, copy_plan, mse_copy_ok, probe_media, run_ffprobe
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
    assert media.video_codec == "mpeg4"
    assert media.mse_copy is False


def test_mse_copy_ok_h264_aac():
    assert mse_copy_ok("h264", ["aac"]) is True
    assert mse_copy_ok("h264", []) is True
    assert mse_copy_ok("mpeg4", ["aac"]) is False
    assert mse_copy_ok("h264", ["ac3"]) is False
    assert copy_plan("h264", ["aac"]) == "copy"
    assert copy_plan("h264", ["ac3"]) == "audio"
    assert copy_plan("hevc", ["aac"]) == "xcode"


def test_run_ffprobe_is_bounded(tmp_path: Path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    seen: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = "{}"

    def runner(argv, **_k):
        seen.append(list(argv))
        return Result()

    run_ffprobe(path, runner=runner)
    assert seen
    assert "-probesize" in seen[0]


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
