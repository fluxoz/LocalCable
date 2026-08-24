"""Filename heuristics plus ffprobe duration / tag extraction."""

from __future__ import annotations

import json
import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Callable

from localcable.models import MediaFile

log = logging.getLogger(__name__)

RunFn = Callable[..., Any]

# Bound header reads so a 20 GB NFS file is not scanned end-to-end.
FFPROBE_PROBESIZE = "8000000"
FFPROBE_ANALYZEDURATION = "2000000"
COPY_VIDEO = {"h264", "avc1"}
COPY_AUDIO = {"aac", "mp4a"}

_JUNK_TAGS = {
    "1080p",
    "720p",
    "480p",
    "2160p",
    "4k",
    "uhd",
    "x264",
    "x265",
    "h264",
    "h265",
    "hevc",
    "avc",
    "webrip",
    "web-dl",
    "webdl",
    "bluray",
    "blu-ray",
    "dvdrip",
    "hdtv",
    "aac",
    "dts",
    "ac3",
    "hdr",
    "sdr",
    "proper",
    "repack",
    "extended",
    "yify",
    "rarbg",
}

_BRACKET = re.compile(r"[\[\(][^\]\)]*[\]\)]")


def clean_filename_title(filename: str) -> str:
    """Turn a media filename into a readable program title."""
    stem = Path(filename).stem
    original_stem = stem
    stem = _BRACKET.sub(" ", stem)
    stem = re.sub(r"[._]+", " ", stem)
    stem = re.sub(r"[-]+", " ", stem)
    words: list[str] = []
    for word in stem.split():
        lower = word.lower()
        if lower in _JUNK_TAGS:
            continue
        if re.fullmatch(r"\d{3,4}p", lower):
            continue
        words.append(word)
    title = " ".join(words).strip()
    if not title:
        title = re.sub(r"[._]+", " ", original_stem).strip() or original_stem
    if title.islower() or "_" in original_stem or "." in original_stem:
        title = title.title()
    return title


def run_ffprobe(
    path: Path,
    runner: RunFn | None = None,
    *,
    streams_only: bool = False,
    bounded: bool = True,
) -> dict[str, Any]:
    """Return parsed ffprobe JSON, or {} on any failure (never raises)."""
    run = runner or subprocess.run
    argv = ["ffprobe", "-v", "error"]
    if bounded:
        argv += [
            "-probesize",
            FFPROBE_PROBESIZE,
            "-analyzeduration",
            FFPROBE_ANALYZEDURATION,
        ]
    argv += ["-print_format", "json"]
    if streams_only:
        argv += ["-show_entries", "stream=codec_type,codec_name", "-show_streams"]
    else:
        argv += ["-show_format", "-show_streams"]
    argv.append(str(path))
    try:
        try:
            proc = run(argv, capture_output=True, text=True, check=False, timeout=12)
        except TypeError:
            proc = run(argv, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        log.warning("ffprobe is not installed; cannot read duration for %s", path)
        return {}
    except Exception as exc:  # noqa: BLE001 — never crash the scan
        log.warning("ffprobe failed for %s: %s", path, exc)
        return {}
    stdout = getattr(proc, "stdout", "") or ""
    if getattr(proc, "returncode", 0) not in (0, None):
        log.warning("ffprobe exit %s for %s", proc.returncode, path)
        if not stdout.strip():
            return {}
    try:
        data = json.loads(stdout) if stdout.strip() else {}
    except json.JSONDecodeError:
        log.warning("ffprobe produced invalid JSON for %s", path)
        return {}
    return data if isinstance(data, dict) else {}


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 0 or number != number:  # NaN
        return None
    return number


def codecs_from_probe(data: dict[str, Any]) -> tuple[str | None, list[str]]:
    """Return (video codec, audio codecs) from ffprobe JSON."""
    video: str | None = None
    audio: list[str] = []
    for stream in data.get("streams") or []:
        if not isinstance(stream, dict):
            continue
        kind = stream.get("codec_type")
        name = str(stream.get("codec_name") or "").strip().lower()
        if kind == "video" and video is None:
            video = name or None
        elif kind == "audio" and name:
            audio.append(name)
    return video, audio


def mse_copy_ok(video: str | None, audio: list[str] | None = None) -> bool:
    """True when MSE can play a stream copy (H.264 + AAC, or H.264 silent)."""
    if (video or "") not in COPY_VIDEO:
        return False
    for name in audio or []:
        if name not in COPY_AUDIO:
            return False
    return True


def copy_plan(video: str | None, audio: list[str] | None = None) -> str:
    """``copy`` (remux), ``audio`` (H.264 copy + AAC encode), or ``xcode``."""
    if mse_copy_ok(video, audio):
        return "copy"
    if (video or "") in COPY_VIDEO:
        return "audio"
    return "xcode"


def duration_from_probe(data: dict[str, Any]) -> float | None:
    fmt = data.get("format") or {}
    duration = _float_or_none(fmt.get("duration"))
    if duration:
        return duration
    for stream in data.get("streams") or []:
        duration = _float_or_none(stream.get("duration"))
        if duration:
            return duration
    return None


def _lower_tags(tags: Any) -> dict[str, str]:
    if not isinstance(tags, dict):
        return {}
    out: dict[str, str] = {}
    for key, value in tags.items():
        if value is None:
            continue
        text = str(value).strip()
        if text:
            out[str(key).lower()] = text
    return out


def tags_from_probe(data: dict[str, Any]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for stream in data.get("streams") or []:
        merged.update(_lower_tags(stream.get("tags")))
    merged.update(_lower_tags((data.get("format") or {}).get("tags")))
    return merged


def _first_tag(tags: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = tags.get(name)
        if value:
            return value
    return None


def probe_media(path: Path | str, *, runner: RunFn | None = None) -> MediaFile | None:
    """Extract title + duration (and optional tags) for a media file.

    Missing tags never raise. Files without a usable duration return None.
    """
    path = Path(path)
    try:
        data = run_ffprobe(path, runner=runner)
    except Exception as exc:  # noqa: BLE001
        log.warning("skipping %s: %s", path, exc)
        return None
    duration = duration_from_probe(data)
    if duration is None:
        try:
            data = run_ffprobe(path, runner=runner, bounded=False)
        except Exception as exc:  # noqa: BLE001
            log.warning("skipping %s: %s", path, exc)
            return None
        duration = duration_from_probe(data)
    if duration is None:
        log.warning("no duration for %s; skipping", path)
        return None
    video_codec, audio_codecs = codecs_from_probe(data)
    tags = tags_from_probe(data)
    embedded_title = _first_tag(tags, "title")
    try:
        fallback = clean_filename_title(path.name)
    except Exception:  # noqa: BLE001
        fallback = path.stem
    title = embedded_title or fallback or path.stem
    description = _first_tag(tags, "description", "comment", "synopsis", "plot")
    rating = _first_tag(tags, "rating", "age_rating", "content_rating")
    genre = _first_tag(tags, "genre")
    year = _first_tag(tags, "date", "year", "creation_time")
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path
    return MediaFile(
        path=resolved,
        title=title,
        duration_seconds=float(duration),
        description=description,
        rating=rating,
        genre=genre,
        year=year,
        video_codec=video_codec,
        audio_codec=audio_codecs[0] if audio_codecs else None,
        mse_copy=mse_copy_ok(video_codec, audio_codecs),
    )
