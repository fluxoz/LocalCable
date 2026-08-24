"""Scan a media root: each immediate subfolder is a channel."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from localcable.metadata import probe_media
from localcable.models import Channel, MediaFile, ScheduleMode
from localcable.util import natural_key

log = logging.getLogger(__name__)

CHANNEL_PREFIX = re.compile(r"^(\d+)_(.+)$")

VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".webm",
    ".m4v",
    ".ts",
    ".m2ts",
    ".mts",
    ".m2t",
    ".wmv",
    ".flv",
    ".mpg",
    ".mpeg",
    ".vob",
    ".ogv",
    ".3gp",
    ".divx",
    ".xvid",
    ".asf",
    ".f4v",
    ".iso",
    ".rmvb",
    ".rm",
}

PLAYLIST_M3U_NAMES = {"playlist.m3u", "playlist.m3u8"}
PLAYLIST_TXT_NAMES = {"playlist.txt"}


def parse_channel_folder_name(name: str) -> tuple[int | None, str]:
    """Parse optional ``NNN_Name`` prefixes. Returns (number or None, display name)."""
    match = CHANNEL_PREFIX.match(name.strip())
    if not match:
        return None, name.strip()
    return int(match.group(1)), match.group(2).strip()


def is_video_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS and not path.name.startswith(".")


def parse_playlist_file(path: Path, folder: Path) -> list[Path]:
    """Read playlist.m3u / playlist.txt into paths (relative entries resolve to *folder*)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("cannot read playlist %s: %s", path, exc)
        return []
    entries: list[Path] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("file:"):
            line = line[5:].lstrip("/")
        candidate = Path(line)
        if not candidate.is_absolute():
            candidate = folder / line
        try:
            entries.append(candidate.resolve())
        except OSError:
            entries.append(candidate)
    return entries


def find_playlist(folder: Path) -> list[Path] | None:
    """Return playlist paths if a playlist file exists, else None."""
    m3u: Path | None = None
    txt: Path | None = None
    try:
        children = list(folder.iterdir())
    except OSError as exc:
        log.warning("cannot list %s: %s", folder, exc)
        return None
    for child in children:
        if not child.is_file():
            continue
        lower = child.name.lower()
        if lower in PLAYLIST_M3U_NAMES:
            m3u = child
        elif lower in PLAYLIST_TXT_NAMES:
            txt = child
    chosen = m3u or txt
    if chosen is None:
        return None
    return parse_playlist_file(chosen, folder)


def _next_free_number(used: set[int]) -> int:
    candidate = 1
    while candidate in used:
        candidate += 1
    return candidate


def assign_channel_numbers(
    parsed: list[tuple[int | None, str, Path]],
) -> list[tuple[int, str, Path]]:
    """Keep explicit ``NNN_`` numbers; auto-number the rest after sorting by name."""
    used = {number for number, _, _ in parsed if number is not None}
    numbered = [(number, name, path) for number, name, path in parsed if number is not None]
    unnumbered = sorted(
        [(name, path) for number, name, path in parsed if number is None],
        key=lambda item: natural_key(item[0]),
    )
    assigned: list[tuple[int, str, Path]] = list(numbered)
    for name, path in unnumbered:
        number = _next_free_number(used)
        used.add(number)
        assigned.append((number, name, path))
    assigned.sort(key=lambda item: (item[0], natural_key(item[1])))
    return assigned


def _load_probe_cache(cache_file: Path) -> dict[str, Any]:
    if not cache_file.is_file():
        return {}
    try:
        data = json.loads(cache_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_probe_cache(cache_file: Path, data: dict[str, Any]) -> None:
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=0), encoding="utf-8")
        tmp.replace(cache_file)
    except OSError as exc:
        log.debug("could not write probe cache: %s", exc)


def _media_from_cache(path: Path, record: dict[str, Any]) -> MediaFile | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    if record.get("mtime") != stat.st_mtime or record.get("size") != stat.st_size:
        return None
    duration = record.get("duration_seconds")
    try:
        duration_f = float(duration)
    except (TypeError, ValueError):
        return None
    if duration_f <= 0:
        return None
    title = record.get("title") or path.stem
    mse_copy = record.get("mse_copy")
    if mse_copy is not None:
        mse_copy = bool(mse_copy)
    return MediaFile(
        path=path.resolve(),
        title=str(title),
        duration_seconds=duration_f,
        description=record.get("description"),
        rating=record.get("rating"),
        genre=record.get("genre"),
        year=record.get("year"),
        video_codec=record.get("video_codec"),
        audio_codec=record.get("audio_codec"),
        mse_copy=mse_copy,
    )


def _cache_record(path: Path, media: MediaFile) -> dict[str, Any]:
    try:
        stat = path.stat()
        mtime, size = stat.st_mtime, stat.st_size
    except OSError:
        mtime, size = None, None
    return {
        "mtime": mtime,
        "size": size,
        "title": media.title,
        "duration_seconds": media.duration_seconds,
        "description": media.description,
        "rating": media.rating,
        "genre": media.genre,
        "year": media.year,
        "video_codec": media.video_codec,
        "audio_codec": media.audio_codec,
        "mse_copy": media.mse_copy,
    }


def scan_media_root(
    root: Path | str,
    *,
    default_mode: str = "sequential",
    probe_runner: Callable[..., Any] | None = None,
    cache_dir: Path | str | None = None,
    probe_fn: Callable[..., MediaFile | None] | None = None,
) -> list[Channel]:
    """Scan *root* for channel folders and probe each video.

    ``probe_fn`` defaults to the shipped :func:`probe_media`. Tests should
    leave it unset so ffprobe actually runs against fixture files.
    """
    root = Path(root)
    if not root.is_dir():
        log.warning("media root does not exist or is not a directory: %s", root)
        return []

    mode: ScheduleMode = "random" if str(default_mode).lower() == "random" else "sequential"
    probe = probe_fn or probe_media

    cache_file: Path | None = None
    cache: dict[str, Any] = {}
    if cache_dir is not None:
        cache_file = Path(cache_dir) / "probe.json"
        cache = _load_probe_cache(cache_file)

    try:
        subdirs = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError as exc:
        log.warning("cannot list media root %s: %s", root, exc)
        return []

    parsed: list[tuple[int | None, str, Path]] = []
    for folder in subdirs:
        number, name = parse_channel_folder_name(folder.name)
        parsed.append((number, name, folder))

    channels: list[Channel] = []
    cache_dirty = False
    for number, name, folder in assign_channel_numbers(parsed):
        media: list[MediaFile] = []
        try:
            files = sorted(
                (p for p in folder.iterdir() if is_video_file(p)),
                key=lambda p: natural_key(p.name),
            )
        except OSError as exc:
            log.warning("cannot list channel folder %s: %s", folder, exc)
            files = []
        for file_path in files:
            key = str(file_path.resolve()) if file_path.exists() else str(file_path)
            cached = _media_from_cache(file_path, cache.get(key) or {}) if key in cache else None
            if cached is not None:
                media.append(cached)
                continue
            try:
                item = probe(file_path, runner=probe_runner)
            except TypeError:
                item = probe(file_path)
            except Exception as exc:  # noqa: BLE001
                log.warning("skipping %s: %s", file_path, exc)
                continue
            if item is None:
                continue
            media.append(item)
            cache[str(item.path)] = _cache_record(file_path, item)
            cache_dirty = True
        playlist = find_playlist(folder)
        channels.append(
            Channel(
                number=number,
                name=name,
                folder_path=folder.resolve(),
                media=media,
                schedule_mode=mode,
                playlist=playlist,
            )
        )

    if cache_dirty and cache_file is not None:
        _save_probe_cache(cache_file, cache)

    channels.sort(key=lambda ch: (ch.number, natural_key(ch.name)))
    return channels


def merge_channels(*groups: list[Channel]) -> list[Channel]:
    """Combine scans from several roots, keeping unique channel numbers."""
    used: set[int] = set()
    out: list[Channel] = []
    overflow: list[Channel] = []
    for group in groups:
        for channel in group:
            if channel.number in used:
                overflow.append(channel)
            else:
                used.add(channel.number)
                out.append(channel)
    for channel in overflow:
        number = 1
        while number in used:
            number += 1
        channel.number = number
        used.add(number)
        out.append(channel)
    out.sort(key=lambda ch: (ch.number, natural_key(ch.name)))
    return out


def pad_channels(channels: list[Channel], minimum: int) -> list[Channel]:
    """Repeat existing channels until *minimum* rows fill the guide."""
    if minimum <= 0 or not channels or len(channels) >= minimum:
        return channels
    used = {ch.number for ch in channels}
    copies = {ch.number: 1 for ch in channels}
    out = list(channels)
    index = 0
    while len(out) < int(minimum):
        src = channels[index % len(channels)]
        copies[src.number] = copies.get(src.number, 1) + 1
        number = 1
        while number in used:
            number += 1
        used.add(number)
        suffix = copies[src.number]
        name = src.name if suffix <= 1 else f"{src.name} {suffix}"
        out.append(
            replace(
                src,
                number=number,
                name=name,
                media=list(src.media),
                playlist=list(src.playlist) if src.playlist else None,
            )
        )
        index += 1
    out.sort(key=lambda ch: (ch.number, natural_key(ch.name)))
    return out
