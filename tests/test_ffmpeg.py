from __future__ import annotations

from pathlib import Path

from localcable.ffmpeg import (
    encoder_args,
    ffmpeg_release_url,
    normalize_hw,
    pick_encoder,
    platform_tag,
    resolve_ffmpeg,
    scale_filter,
)


def test_hw_aliases():
    assert normalize_hw("CUDA") == "nvenc"
    assert normalize_hw("intel") == "qsv"
    assert normalize_hw("off") == "cpu"
    assert normalize_hw("auto") == "auto"


def test_platform_tag_is_known():
    tag = platform_tag()
    url, kind = ffmpeg_release_url(tag)
    assert url.startswith("http")
    assert kind in {"zip", "tar.xz"}


def test_resolve_ffmpeg_prefers_env(tmp_path: Path, monkeypatch):
    binary = tmp_path / "ffmpeg"
    binary.write_text("x", encoding="utf-8")
    binary.chmod(0o755)
    monkeypatch.setenv("LOCALCABLE_FFMPEG", str(binary))
    assert resolve_ffmpeg(environ={"LOCALCABLE_FFMPEG": str(binary)}) == str(binary)


def test_resolve_ffmpeg_uses_path(tmp_path: Path):
    binary = tmp_path / "ffmpeg"
    binary.write_text("x", encoding="utf-8")
    found = resolve_ffmpeg(explicit=binary)
    assert found == str(binary)


def test_pick_encoder_cpu_when_forced():
    def runner(argv, **_k):
        class Result:
            returncode = 0
            stdout = " V..... libx264\n V..... h264_nvenc\n"
            stderr = ""

        if "-encoders" in argv:
            return Result()
        Result.returncode = 1
        return Result()

    hw, enc = pick_encoder("/usr/bin/ffmpeg", hw="cpu", runner=runner, smoke=False)
    assert hw == "cpu"
    assert enc == "libx264"


def test_pick_encoder_prefers_nvenc_when_listed():
    def runner(argv, **_k):
        class Result:
            returncode = 0
            stdout = " V..... h264_nvenc\n V..... libx264\n"
            stderr = ""

        return Result()

    hw, enc = pick_encoder("/usr/bin/ffmpeg", hw="auto", runner=runner, smoke=False)
    assert hw == "nvenc"
    assert enc == "h264_nvenc"


def test_encoder_args_and_scale():
    cpu = encoder_args("cpu", "libx264", crf=20, maxrate="8M")
    assert "libx264" in cpu
    assert "-crf" in cpu
    nv = encoder_args("nvenc", "h264_nvenc", crf=20)
    assert "h264_nvenc" in nv
    assert scale_filter("cpu", 720) == "scale=-2:720:flags=lanczos"
    assert scale_filter("cpu", None) is None
