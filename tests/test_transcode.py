from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from localcable.ffmpeg import resolve_ffmpeg
from localcable.main import main
from localcable.transcode import (
    already_native,
    collapse_rendition_files,
    dest_for,
    output_name,
    parse_rungs,
    plan_file,
    progress_seconds,
    target_heights,
    transcode_argv,
    transcode_library,
    variant_base,
)


def test_parse_rungs_and_no_upscale():
    assert parse_rungs("1080,720,native") == ["1080", "720", "native"]
    assert parse_rungs(["2160", "1080"]) == ["2160", "1080"]
    assert target_heights(1080, ["native", "2160", "1080", "720"]) == [
        ("native", 1080),
        ("720", 720),
    ]
    assert target_heights(480, ["1080", "720"]) == [("native", 480)]


def test_output_names_sit_alongside():
    src = Path("/media/Show.S01E01.mkv")
    assert output_name(src, "native") == Path("/media/Show.S01E01.mp4")
    assert output_name(src, "1080") == Path("/media/Show.S01E01.1080p.mp4")
    assert variant_base(Path("/media/Show.S01E01.720p.mp4")) == "Show.S01E01"
    mixed = dest_for(src, "native", 1080, 1080, ["native", "720"])
    assert mixed.name == "Show.S01E01.1080p.mp4"
    only = dest_for(src, "native", 1080, 1080, ["native"])
    assert only.name == "Show.S01E01.mp4"


def test_collapse_renditions_groups_siblings(tmp_path: Path):
    hi = tmp_path / "Pilot.1080p.mp4"
    lo = tmp_path / "Pilot.720p.mp4"
    other = tmp_path / "Finale.mp4"
    hi.write_bytes(b"x")
    lo.write_bytes(b"x")
    other.write_bytes(b"x")
    grouped = collapse_rendition_files([hi, lo, other])
    by_primary = {row[0].name: row[1] for row in grouped}
    assert "Pilot.1080p.mp4" in by_primary
    labels = {r.label for r in by_primary["Pilot.1080p.mp4"]}
    assert labels == {"1080p", "720p"}
    assert other.name in by_primary


def test_plan_file_replaces_foreign_container(tmp_path: Path):
    src = tmp_path / "clip.mkv"
    src.write_bytes(b"x")
    probe = {
        "streams": [
            {"codec_type": "video", "codec_name": "hevc", "width": 1920, "height": 1080},
            {"codec_type": "audio", "codec_name": "ac3"},
        ]
    }
    plan = plan_file(src, ["native", "720"], probe=probe)
    names = [job.dest.name for job in plan.jobs]
    assert "clip.1080p.mp4" in names
    assert "clip.720p.mp4" in names
    assert src in plan.replace


def test_already_native_h264_aac_mp4(tmp_path: Path):
    path = tmp_path / "clip.mp4"
    path.write_bytes(b"x")
    probe = {
        "streams": [
            {"codec_type": "video", "codec_name": "h264"},
            {"codec_type": "audio", "codec_name": "aac"},
        ]
    }
    assert already_native(path, probe, codec="h264") is True
    mkv = tmp_path / "clip.mkv"
    mkv.write_bytes(b"x")
    assert already_native(mkv, probe, codec="h264") is False


def test_transcode_argv_is_h264_aac():
    argv = transcode_argv(
        Path("in.mkv"),
        Path("out.mp4"),
        ffmpeg="/opt/ffmpeg",
        encoder="libx264",
        hw_name="cpu",
        height=720,
        crf=21,
        maxrate="4M",
        copy_audio=False,
    )
    assert argv[0] == "/opt/ffmpeg"
    assert "libx264" in argv
    assert "aac" in argv
    assert "+faststart" in argv
    assert argv[argv.index("-f") + 1] == "mp4"
    assert "scale=-2:720:flags=lanczos" in argv
    assert "hevc" not in argv and "libx265" not in argv
    assert str(argv[-1]).endswith(".mp4")


def test_transcode_library_dry_run(tmp_path: Path):
    src = tmp_path / "101_CNN" / "news.mkv"
    src.parent.mkdir()
    src.write_bytes(b"x")

    def runner(argv, **_k):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        if "-encoders" in argv:
            Result.stdout = " V..... libx264\n"
            return Result()
        if argv and str(argv[0]).endswith("ffprobe") or (argv and "ffprobe" in argv[0]):
            Result.stdout = (
                '{"streams":[{"codec_type":"video","codec_name":"mpeg4",'
                '"width":1280,"height":720}]}'
            )
            return Result()
        return Result()

    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("x", encoding="utf-8")
    result = transcode_library(
        [tmp_path],
        rungs=["720"],
        hw="cpu",
        dry_run=True,
        ffmpeg=str(ffmpeg),
        runner=runner,
        smoke=False,
    )
    assert result.planned >= 1
    assert result.encoded == 0


def test_real_ffmpeg_accepts_partial_mp4_output(tmp_path: Path):
    from tests.helpers import make_video

    try:
        ffmpeg = resolve_ffmpeg()
    except FileNotFoundError:
        pytest.skip("ffmpeg not installed")
    src = make_video(tmp_path / "clip.mkv", 0.4, codec="mpeg4")
    dest = tmp_path / "clip.mp4"
    tmp = dest.with_name(dest.stem + ".partial" + dest.suffix)
    argv = transcode_argv(
        src,
        tmp,
        ffmpeg=ffmpeg,
        encoder="libx264",
        hw_name="cpu",
        height=None,
        crf=28,
        maxrate="1M",
        copy_audio=False,
    )
    proc = subprocess.run(argv, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert tmp.is_file() and tmp.stat().st_size > 0


def test_progress_seconds_from_ffmpeg_fields():
    assert progress_seconds({"out_time_us": "1500000"}) == 1.5
    assert progress_seconds({"out_time": "00:00:02.5"}) == 2.5


def test_transcode_library_reports_progress(tmp_path: Path):
    src = tmp_path / "101_CNN" / "news.mkv"
    src.parent.mkdir()
    src.write_bytes(b"x")
    events: list[dict] = []

    def runner(argv, **_k):
        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        if "-encoders" in argv:
            Result.stdout = " V..... libx264\n"
            return Result()
        Result.stdout = (
            '{"streams":[{"codec_type":"video","codec_name":"mpeg4",'
            '"width":1280,"height":720}],"format":{"duration":"2.0"}}'
        )
        return Result()

    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("x", encoding="utf-8")
    transcode_library(
        [tmp_path],
        rungs=["720"],
        hw="cpu",
        dry_run=True,
        ffmpeg=str(ffmpeg),
        runner=runner,
        smoke=False,
        on_progress=events.append,
    )
    assert events
    assert any(ev.get("files") for ev in events)
    assert any(ev.get("library_total", 0) >= 1 for ev in events)


def test_cli_transcode_help():
    try:
        main(["transcode", "--help"])
    except SystemExit as exc:
        assert exc.code == 0
