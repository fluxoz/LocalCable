from __future__ import annotations

from pathlib import Path

import pytest

from localcable.dash import DashPackager, can_direct_play, codecs_allow_copy, content_id, dash_argv, mime_for


def test_dash_argv_copy_and_transcode(tmp_path: Path):
    src = tmp_path / "show.mkv"
    dest = tmp_path / "out"
    copy = dash_argv(src, dest, transcode=False)
    assert "-c" in copy and "copy" in copy
    assert "-f" in copy and "dash" in copy
    assert str(dest / "manifest.mpd") in copy
    xcode = dash_argv(src, dest, transcode=True)
    assert "libx264" in xcode
    assert "aac" in xcode
    assert any("min(720,ih)" in str(part) for part in xcode)
    jumped = dash_argv(src, dest, transcode=True, start_seconds=1200)
    assert "-ss" in jumped
    assert jumped.index("-ss") < jumped.index("-i")
    copy_jump = dash_argv(src, dest, transcode=False, start_seconds=1200)
    assert "copy" in copy_jump
    assert "-ss" in copy_jump
    assert copy_jump.index("-ss") < copy_jump.index("-i")
    assert "-avoid_negative_ts" in copy_jump
    assert "-probesize" in copy
    audio_only = dash_argv(src, dest, transcode=False, audio_transcode=True)
    assert audio_only[audio_only.index("-c:v") + 1] == "copy"
    assert "libx264" not in audio_only
    assert "aac" in audio_only
    crt = dash_argv(
        src,
        dest,
        transcode=True,
        video_filter="scale=-2:480:flags=lanczos,frei0r=ntscrs:/tmp/ntsc.json",
    )
    vf = crt[crt.index("-vf") + 1]
    assert "frei0r=ntscrs:" in vf
    assert "min(720" not in vf


def test_mime_for_manifest_and_segments():
    assert mime_for("manifest.mpd") == "application/dash+xml"
    assert mime_for("chunk-0-00001.m4s") == "video/iso.segment"
    assert mime_for("init-0.mp4") == "video/mp4"


def test_resolve_file_rejects_bad_ids_and_traversal(tmp_path: Path):
    pack = DashPackager(tmp_path)
    dest = tmp_path / "dash" / "aabbccdd11223344"
    dest.mkdir(parents=True)
    (dest / "manifest.mpd").write_text("x" * 50, encoding="utf-8")
    assert pack.resolve_file("not hex", "manifest.mpd") is None
    assert pack.resolve_file("aabbccdd11223344", "../passwd") is None
    assert pack.resolve_file("aabbccdd11223344", "manifest.mpd") == dest / "manifest.mpd"


def test_ensure_copy_then_stamp(tmp_path: Path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"video")
    calls: list[list[str]] = []

    class Proc:
        def terminate(self):
            return None

        def poll(self):
            return 0

    def popen(argv, **kwargs):
        calls.append(list(argv))
        dest = Path(kwargs["cwd"])
        (dest / "manifest.mpd").write_text('<?xml version="1.0"?><MPD/>' + "x" * 40, encoding="utf-8")
        return Proc()

    pack = DashPackager(
        tmp_path,
        popen=popen,
        which=lambda _n: "/usr/bin/ffmpeg",
        sleep=lambda _s: None,
        copy_ok=lambda _p: True,
    )
    pid = "aabbccddeeff00112233"
    mpd = pack.ensure(pid, src, wait=0.5)
    assert mpd.is_file()
    assert pack.manifest_url(pid) == f"/dash/{pid}/manifest.mpd"
    assert calls
    assert "copy" in calls[0]
    again = pack.ensure(pid, src, wait=0.5)
    assert again == mpd
    assert len(calls) == 1


def test_ensure_transcodes_when_copy_not_allowed(tmp_path: Path):
    src = tmp_path / "a.avi"
    src.write_bytes(b"video")
    calls: list[list[str]] = []

    class Proc:
        def terminate(self):
            return None

        def poll(self):
            return 0

    def popen(argv, **kwargs):
        calls.append(list(argv))
        dest = Path(kwargs["cwd"])
        (dest / "manifest.mpd").write_text('<?xml version="1.0"?><MPD/>' + "x" * 40, encoding="utf-8")
        return Proc()

    pack = DashPackager(
        tmp_path,
        popen=popen,
        which=lambda _n: "/usr/bin/ffmpeg",
        sleep=lambda _s: None,
        copy_ok=lambda _p: False,
    )
    pack.ensure("aabbccddeeff00112233", src, wait=0.5)
    assert calls
    assert "libx264" in calls[0]
    assert "copy" not in calls[0]


def test_codecs_allow_copy_reads_ffprobe_json(tmp_path: Path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")

    class Result:
        returncode = 0
        stdout = '{"streams":[{"codec_type":"video","codec_name":"h264"},{"codec_type":"audio","codec_name":"aac"}]}'

    assert codecs_allow_copy(src, runner=lambda *_a, **_k: Result()) is True

    class Mpeg4:
        returncode = 0
        stdout = '{"streams":[{"codec_type":"video","codec_name":"mpeg4"}]}'

    assert codecs_allow_copy(src, runner=lambda *_a, **_k: Mpeg4()) is False


def test_codecs_allow_copy_bounds_ffprobe(tmp_path: Path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    seen: list[list[str]] = []

    class Result:
        returncode = 0
        stdout = '{"streams":[{"codec_type":"video","codec_name":"h264"}]}'

    def runner(argv, **_k):
        seen.append(list(argv))
        return Result()

    assert codecs_allow_copy(src, runner=runner) is True
    assert seen
    assert "-probesize" in seen[0]
    assert "-analyzeduration" in seen[0]


def test_ensure_audio_transcode_keeps_video_copy(tmp_path: Path):
    src = tmp_path / "a.mkv"
    src.write_bytes(b"video")
    calls: list[list[str]] = []

    class Proc:
        def terminate(self):
            return None

        def poll(self):
            return 0

    def popen(argv, **kwargs):
        calls.append(list(argv))
        dest = Path(kwargs["cwd"])
        (dest / "manifest.mpd").write_text('<?xml version="1.0"?><MPD/>' + "x" * 40, encoding="utf-8")
        return Proc()

    pack = DashPackager(
        tmp_path,
        popen=popen,
        which=lambda _n: "/usr/bin/ffmpeg",
        sleep=lambda _s: None,
        copy_ok=lambda _p: False,
        copy_plan_fn=lambda _p: "audio",
    )
    pack.ensure("aabbccddeeff00112233", src, wait=0.5, start_seconds=600)
    assert calls
    assert calls[0][calls[0].index("-c:v") + 1] == "copy"
    assert "libx264" not in calls[0]
    assert "aac" in calls[0]
    assert "-ss" in calls[0]


def test_ensure_copy_keeps_live_offset(tmp_path: Path):
    src = tmp_path / "a.mkv"
    src.write_bytes(b"video")
    calls: list[list[str]] = []

    class Proc:
        def terminate(self):
            return None

        def poll(self):
            return 0

    def popen(argv, **kwargs):
        calls.append(list(argv))
        dest = Path(kwargs["cwd"])
        (dest / "manifest.mpd").write_text('<?xml version="1.0"?><MPD/>' + "x" * 40, encoding="utf-8")
        return Proc()

    pack = DashPackager(
        tmp_path,
        popen=popen,
        which=lambda _n: "/usr/bin/ffmpeg",
        sleep=lambda _s: None,
        copy_ok=lambda _p: True,
    )
    pack.ensure("aabbccddeeff00112233", src, wait=0.5, start_seconds=1200)
    assert calls
    assert "copy" in calls[0]
    assert "libx264" not in calls[0]
    assert "-ss" in calls[0]


def test_ensure_does_not_transcode_in_progress_copy(tmp_path: Path):
    src = tmp_path / "a.mkv"
    src.write_bytes(b"video")
    calls: list[list[str]] = []
    stopped: list[int] = []

    class Proc:
        def terminate(self):
            stopped.append(1)

        def poll(self):
            return None

    def popen(argv, **kwargs):
        calls.append(list(argv))
        return Proc()

    pack = DashPackager(
        tmp_path,
        popen=popen,
        which=lambda _n: "/usr/bin/ffmpeg",
        sleep=lambda _s: None,
        copy_ok=lambda _p: True,
    )
    with pytest.raises(TimeoutError):
        pack.ensure("aabbccddeeff00112233", src, wait=0.05)
    with pytest.raises(TimeoutError):
        pack.ensure("aabbccddeeff00112233", src, wait=0.05)
    assert len(calls) == 1
    assert "copy" in calls[0]
    assert stopped == []


def test_ensure_transcodes_if_copy_process_exits(tmp_path: Path):
    src = tmp_path / "a.mkv"
    src.write_bytes(b"video")
    calls: list[list[str]] = []

    class Dead:
        def terminate(self):
            return None

        def poll(self):
            return 1

    def popen(argv, **kwargs):
        calls.append(list(argv))
        dest = Path(kwargs["cwd"])
        if "libx264" in argv:
            (dest / "manifest.mpd").write_text(
                '<?xml version="1.0"?><MPD/>' + "x" * 40, encoding="utf-8"
            )
        return Dead()

    pack = DashPackager(
        tmp_path,
        popen=popen,
        which=lambda _n: "/usr/bin/ffmpeg",
        sleep=lambda _s: None,
        copy_ok=lambda _p: True,
    )
    pack.ensure("aabbccddeeff00112233", src, wait=0.05)
    assert len(calls) == 2
    assert "copy" in calls[0]
    assert "libx264" in calls[1]


def test_content_id_stable_and_direct_play_suffix(tmp_path: Path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x" * 12)
    assert content_id(src) == content_id(src)
    assert content_id(src, start_seconds=1200) != content_id(src)
    assert content_id(src, filter_mode="vhs") != content_id(src)
    assert can_direct_play(tmp_path / "a.mkv", copy_ok=lambda _p: True) is False
    assert can_direct_play(src, copy_ok=lambda _p: True) is True
    assert can_direct_play(src, copy_ok=lambda _p: False) is False
    assert can_direct_play(src, mse_copy=True) is True
    assert can_direct_play(src, mse_copy=False) is False
    assert can_direct_play(tmp_path / "a.mkv", mse_copy=True) is False
