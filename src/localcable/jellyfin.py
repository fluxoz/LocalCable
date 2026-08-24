"""Jellyfin-style library layout: Movies/Title (Year)/ and Shows/Season 01/SxxExx."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Callable

from localcable.metadata import probe_media
from localcable.models import Channel, MediaFile, ScheduleMode
from localcable.scan import (
    _cache_record,
    _load_probe_cache,
    _media_from_cache,
    _save_probe_cache,
    assign_channel_numbers,
    is_video_file,
    merge_channels,
    parse_channel_folder_name,
    scan_media_root,
)
from localcable.util import natural_key

log = logging.getLogger(__name__)

SKIP_DIR_NAMES = {
    "trailers",
    "featurettes",
    "extras",
    "behind the scenes",
    "interviews",
    "deleted scenes",
    "theme-music",
    "backdrops",
    "samples",
    "@eadir",
}

SEASON_DIR = re.compile(r"^(?:season|series)[\s._-]*(?P<num>\d{1,2})$", re.I)
EPISODE = re.compile(
    r"[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,2})",
)
MOVIE_YEAR = re.compile(
    r"^(?P<title>.+?)\s*\((?P<year>19\d{2}|20\d{2}|21\d{2})\)(?:\s*\[.+\])?\s*$",
)
LOOSE_EPISODE = re.compile(
    r"^(?P<show>.+?)[\s._-]+[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,2})"
    r"(?:[\s._-]+(?P<etitle>.+))?$",
    re.I,
)
LOOSE_X = re.compile(
    r"^(?P<show>.+?)[\s._-]+(?P<season>\d{1,2})x(?P<episode>\d{2})"
    r"(?:[\s._-]+(?P<etitle>.+))?$",
    re.I,
)
LOOSE_MOVIE = re.compile(
    r"^(?P<title>.+?)[\s._(]+(?P<year>19\d{2}|20\d{2})\)?",
    re.I,
)
QUALITY_TAGS = re.compile(
    r"\b(720p|1080p|2160p|480p|webrip|web[-. ]?dl|bluray|blu[-. ]?ray|"
    r"x264|x265|h264|h265|hevc|hdr|dv|proper|repack|extended|unrated|"
    r"multi|aac|dts|ac3|yify|rarbg|hdtv|pdtv|dvdrip|brrip|amzn|nf|dsnp)\b",
    re.I,
)
INVALID_FS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def safe_component(name: str) -> str:
    """Strip characters that cannot appear in a folder or file name."""
    text = INVALID_FS.sub("", name)
    text = re.sub(r"\s+", " ", text).strip(" .")
    return text or "Unknown"


def clean_title(text: str) -> str:
    cleaned = re.sub(r"[._]+", " ", text)
    cleaned = QUALITY_TAGS.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -._[]()")
    if cleaned.islower() or cleaned.isupper():
        cleaned = cleaned.title()
    return cleaned


def parse_episode_tag(name: str) -> tuple[int, int] | None:
    match = EPISODE.search(name)
    if not match:
        return None
    return int(match.group("season")), int(match.group("episode"))


def parse_movie_label(name: str) -> tuple[str, str | None]:
    text = Path(name).stem if "." in name and not name.endswith(")") else name
    match = MOVIE_YEAR.match(text.strip())
    if match:
        return re.sub(r"[._]+", " ", match.group("title")).strip(), match.group("year")
    return re.sub(r"[._]+", " ", text).strip(), None


def parse_loose_filename(filename: str) -> dict[str, Any] | None:
    """Guess TV vs movie from a download-style filename."""
    stem = Path(filename).stem
    spaced = re.sub(r"[._]+", " ", stem.replace(" - ", " "))
    ep = LOOSE_EPISODE.match(stem.replace(" - ", " ")) or LOOSE_EPISODE.match(spaced)
    if not ep:
        ep = LOOSE_X.match(spaced)
    if ep:
        show = clean_title(ep.group("show"))
        etitle = ep.group("etitle")
        if etitle:
            etitle = clean_title(etitle) or None
        return {
            "kind": "tv",
            "show": show,
            "season": int(ep.group("season")),
            "episode": int(ep.group("episode")),
            "episode_title": etitle or None,
        }
    movie = LOOSE_MOVIE.search(spaced)
    if movie:
        title = clean_title(movie.group("title"))
        if title:
            return {"kind": "movie", "title": title, "year": movie.group("year")}
    cleaned = clean_title(stem)
    if cleaned:
        return {"kind": "movie", "title": cleaned, "year": None}
    return None


def jellyfin_tv_path(
    root: Path | str,
    show: str,
    year: str | None,
    season: int,
    episode: int,
    ext: str,
    episode_title: str | None = None,
) -> Path:
    """Series/Season 01/Series - S01E01 - Title.ext under a TV library root."""
    folder = safe_component(f"{show} ({year})" if year else show)
    season_dir = f"Season {season:02d}"
    base = f"{folder} - S{season:02d}E{episode:02d}"
    if episode_title:
        base = f"{base} - {safe_component(episode_title)}"
    suffix = ext if ext.startswith(".") else f".{ext}"
    return Path(root) / folder / season_dir / f"{base}{suffix}"


def jellyfin_movie_path(root: Path | str, title: str, year: str | None, ext: str) -> Path:
    """Title (Year)/Title (Year).ext under a movies library root."""
    folder = safe_component(f"{title} ({year})" if year else title)
    suffix = ext if ext.startswith(".") else f".{ext}"
    return Path(root) / folder / f"{folder}{suffix}"


def is_already_jellyfin_tv(path: Path, root: Path) -> bool:
    try:
        rel = path.resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return False
    parts = rel.parts
    return len(parts) >= 3 and bool(SEASON_DIR.match(parts[-2]))


def is_already_jellyfin_movie(path: Path, root: Path) -> bool:
    try:
        rel = path.resolve().relative_to(Path(root).resolve())
    except (ValueError, OSError):
        return False
    return len(rel.parts) >= 2


def _skip_dir(name: str) -> bool:
    return name.startswith(".") or name.lower() in SKIP_DIR_NAMES


def _probe_many(
    files: list[Path],
    *,
    probe_runner: Callable[..., Any] | None,
    probe_fn: Callable[..., MediaFile | None] | None,
    cache: dict[str, Any],
) -> tuple[list[MediaFile], bool]:
    probe = probe_fn or probe_media
    media: list[MediaFile] = []
    dirty = False
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
        dirty = True
    return media, dirty


def scan_tv_root(
    root: Path | str,
    *,
    default_mode: str = "sequential",
    probe_runner: Callable[..., Any] | None = None,
    cache_dir: Path | str | None = None,
    probe_fn: Callable[..., MediaFile | None] | None = None,
) -> list[Channel]:
    """Each series folder becomes a channel; episodes play in SxxExx order."""
    root = Path(root)
    if not root.is_dir():
        return []
    mode: ScheduleMode = "random" if str(default_mode).lower() == "random" else "sequential"
    cache_file = Path(cache_dir) / "probe.json" if cache_dir is not None else None
    cache: dict[str, Any] = _load_probe_cache(cache_file) if cache_file else {}
    dirty = False
    parsed: list[tuple[int | None, str, Path]] = []
    series_files: dict[Path, list[Path]] = {}
    try:
        series_dirs = [p for p in root.iterdir() if p.is_dir() and not _skip_dir(p.name)]
    except OSError as exc:
        log.warning("cannot list TV root %s: %s", root, exc)
        return []
    for series in series_dirs:
        number, name = parse_channel_folder_name(series.name)
        title, year = parse_movie_label(name)
        display = f"{title} ({year})" if year and "(" not in name else name
        parsed.append((number, display, series))
        files: list[Path] = []
        try:
            children = list(series.iterdir())
        except OSError:
            children = []
        season_dirs = [p for p in children if p.is_dir() and not _skip_dir(p.name)]
        loose = [p for p in children if is_video_file(p)]
        if season_dirs:
            for season in sorted(season_dirs, key=lambda p: natural_key(p.name)):
                try:
                    files.extend(p for p in season.iterdir() if is_video_file(p))
                except OSError:
                    continue
        files.extend(loose)
        files.sort(key=lambda p: _episode_sort_key(p))
        series_files[series] = files

    channels: list[Channel] = []
    for number, name, folder in assign_channel_numbers(parsed):
        media, d = _probe_many(
            series_files.get(folder, []),
            probe_runner=probe_runner,
            probe_fn=probe_fn,
            cache=cache,
        )
        dirty = dirty or d
        for item in media:
            tag = parse_episode_tag(item.path.name)
            if tag:
                season, episode = tag
                pretty = f"S{season:02d}E{episode:02d}"
                if pretty.lower() not in item.title.lower():
                    item.title = f"{pretty} · {item.title}"
        channels.append(
            Channel(
                number=number,
                name=name,
                folder_path=folder.resolve(),
                media=media,
                schedule_mode=mode,
            )
        )
    if dirty and cache_file is not None:
        _save_probe_cache(cache_file, cache)
    channels.sort(key=lambda ch: (ch.number, natural_key(ch.name)))
    return channels


def _episode_sort_key(path: Path) -> tuple:
    tag = parse_episode_tag(path.name)
    if tag:
        return (tag[0], tag[1], natural_key(path.name))
    parent = SEASON_DIR.match(path.parent.name)
    season = int(parent.group("num")) if parent else 0
    return (season, 0, natural_key(path.name))


def scan_movies_root(
    root: Path | str,
    *,
    default_mode: str = "sequential",
    probe_runner: Callable[..., Any] | None = None,
    cache_dir: Path | str | None = None,
    probe_fn: Callable[..., MediaFile | None] | None = None,
) -> list[Channel]:
    """One channel for the movies library; each movie folder is one program."""
    root = Path(root)
    if not root.is_dir():
        return []
    mode: ScheduleMode = "random" if str(default_mode).lower() == "random" else "sequential"
    cache_file = Path(cache_dir) / "probe.json" if cache_dir is not None else None
    cache: dict[str, Any] = _load_probe_cache(cache_file) if cache_file else {}
    files: list[Path] = []
    try:
        children = list(root.iterdir())
    except OSError as exc:
        log.warning("cannot list movies root %s: %s", root, exc)
        return []
    for child in sorted(children, key=lambda p: natural_key(p.name)):
        if child.name.startswith(".") or _skip_dir(child.name):
            continue
        if child.is_dir():
            try:
                videos = [p for p in child.iterdir() if is_video_file(p)]
            except OSError:
                videos = []
            videos.sort(key=lambda p: natural_key(p.name))
            if videos:
                files.append(videos[0])
        elif is_video_file(child):
            files.append(child)
    media, dirty = _probe_many(files, probe_runner=probe_runner, probe_fn=probe_fn, cache=cache)
    for item in media:
        title, year = parse_movie_label(item.path.parent.name if item.path.parent != root else item.path.stem)
        if title:
            item.title = f"{title} ({year})" if year else title
            if year:
                item.year = year
    if dirty and cache_file is not None:
        _save_probe_cache(cache_file, cache)
    number, name = parse_channel_folder_name(root.name)
    if number is None:
        name = name or "Movies"
    assigned = assign_channel_numbers([(number, name, root)])
    ch_num, ch_name, folder = assigned[0]
    return [
        Channel(
            number=ch_num,
            name=ch_name,
            folder_path=folder.resolve(),
            media=media,
            schedule_mode=mode,
        )
    ]


def _prefix_series_titles(channel: Channel) -> None:
    title, _year = parse_movie_label(channel.name)
    prefix = title or channel.name
    if not prefix:
        return
    for item in channel.media:
        if prefix.lower() not in item.title.lower():
            item.title = f"{prefix} · {item.title}"


def scan_auto_root(
    root: Path | str,
    *,
    default_mode: str = "sequential",
    probe_runner: Callable[..., Any] | None = None,
    cache_dir: Path | str | None = None,
    probe_fn: Callable[..., MediaFile | None] | None = None,
    fetch_metadata: bool = False,
    opener: Callable[..., Any] | None = None,
    lineup_config: Any = None,
) -> list[Channel]:
    """Scan a top-level library (Movies/ + Shows/) into genre cable channels."""
    from localcable.lineup import (
        enrich_genres,
        find_movie_dir,
        find_tv_dir,
        lineup_channels,
        looks_like_movie_library,
        looks_like_tv_library,
    )

    root = Path(root)
    kwargs: dict[str, Any] = {
        "default_mode": default_mode,
        "probe_runner": probe_runner,
        "cache_dir": cache_dir,
        "probe_fn": probe_fn,
    }
    tv_dir = find_tv_dir(root)
    movie_dir = find_movie_dir(root)
    if tv_dir is None and looks_like_tv_library(root):
        tv_dir = root
    if movie_dir is None and tv_dir is None and looks_like_movie_library(root):
        movie_dir = root
    items: list[MediaFile] = []
    if tv_dir is not None:
        for channel in scan_tv_root(tv_dir, **kwargs):
            _prefix_series_titles(channel)
            items.extend(channel.media)
    if movie_dir is not None:
        for channel in scan_movies_root(movie_dir, **kwargs):
            items.extend(channel.media)
    if not items:
        return []
    enrich_genres(items, fetch=fetch_metadata, opener=opener)
    return lineup_channels(
        items, root, default_mode=default_mode, lineup_config=lineup_config
    )


def scan_libraries(
    libraries: list[Any],
    *,
    default_mode: str = "sequential",
    probe_runner: Callable[..., Any] | None = None,
    cache_dir: Path | str | None = None,
    probe_fn: Callable[..., MediaFile | None] | None = None,
    fetch_metadata: bool = False,
    opener: Callable[..., Any] | None = None,
    auto_channels: bool = True,
    lineup_config: Any = None,
) -> list[Channel]:
    """Scan mixed channel / Jellyfin TV / movie roots and merge channel numbers."""
    from localcable.lineup import detect_library_kind

    kwargs: dict[str, Any] = {
        "default_mode": default_mode,
        "probe_runner": probe_runner,
        "cache_dir": cache_dir,
        "probe_fn": probe_fn,
    }
    auto_kwargs = {
        **kwargs,
        "fetch_metadata": fetch_metadata,
        "opener": opener,
        "lineup_config": lineup_config,
    }
    groups: list[list[Channel]] = []
    for lib in libraries:
        path = Path(getattr(lib, "path"))
        kind = str(getattr(lib, "kind", "channels") or "channels").lower()
        if kind in {"auto", "lineup", "cable"}:
            groups.append(scan_auto_root(path, **auto_kwargs))
            continue
        if kind == "jellyfin":
            groups.append(scan_auto_root(path, **auto_kwargs))
            continue
        if kind == "tv":
            groups.append(scan_tv_root(path, **kwargs))
            continue
        if kind in {"movie", "movies"}:
            groups.append(scan_movies_root(path, **kwargs))
            continue
        detected = detect_library_kind(path) if auto_channels else "channels"
        if detected == "auto":
            groups.append(scan_auto_root(path, **auto_kwargs))
        elif detected == "tv":
            groups.append(scan_tv_root(path, **kwargs))
        elif detected == "movies":
            groups.append(scan_movies_root(path, **kwargs))
        else:
            groups.append(scan_media_root(path, **kwargs))
    return merge_channels(*groups)
