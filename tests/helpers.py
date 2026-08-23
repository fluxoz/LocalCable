"""Fixture media builders — real ffmpeg files with known durations."""

from __future__ import annotations

import subprocess
from pathlib import Path

FROZEN_ISO = "2026-08-23T15:00:00+00:00"


def make_video(
    path: Path,
    duration: float,
    *,
    title: str | None = None,
    color: str = "blue",
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=16x16:d={duration}:r=2",
        "-c:v",
        "mpeg4",
        "-q:v",
        "12",
        "-an",
        "-t",
        str(duration),
    ]
    if title is not None:
        cmd.extend(["-metadata", f"title={title}"])
    cmd.append(str(path))
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed for {path}: {proc.stderr[-800:]}")
    return path


def write_m3u(folder: Path, filenames: list[str]) -> Path:
    lines = ["#EXTM3U"]
    for name in filenames:
        lines.append("#EXTINF:-1,")
        lines.append(name)
    path = folder / "playlist.m3u"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_txt_playlist(folder: Path, filenames: list[str]) -> Path:
    path = folder / "playlist.txt"
    path.write_text("\n".join(filenames) + "\n", encoding="utf-8")
    return path


def build_tiny_library(root: Path) -> Path:
    """Numbered + unnumbered channels, m3u + txt playlists, mixed durations."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)

    cnn = root / "101_CNN"
    make_video(cnn / "evening_news.mp4", 2.0, color="blue")
    make_video(cnn / "late_edition.mp4", 3.0, color="navy")
    write_m3u(cnn, ["late_edition.mp4", "evening_news.mp4"])

    alt = root / "205_ALT"
    make_video(alt / "zeta_show.mp4", 4.0, color="green")

    hist = root / "310_HIST"
    make_video(hist / "alpha.mp4", 2.0, color="yellow")
    make_video(hist / "beta.mp4", 2.0, color="orange")
    write_txt_playlist(hist, ["beta.mp4", "alpha.mp4"])

    make_video(root / "Discovery" / "nature.mp4", 2.0, color="teal")
    make_video(root / "HBO" / "big_movie.mp4", 5.0, color="red")
    return root
