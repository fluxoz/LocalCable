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
    exclude_from_padding,
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


def _display_show_name(text: str) -> str:
    """Series name without a trailing (Year). clean_title may have stripped ')'."""
    raw = (text or "").strip()
    if not raw:
        return raw
    repaired = raw + ")" if re.search(r"\((?:19|20|21)\d{2}$", raw) else raw
    title, year = parse_movie_label(repaired)
    if year and title:
        return title
    stripped = re.sub(r"\s*\(?((?:19|20|21)\d{2})\)?\s*$", "", raw).strip()
    return stripped or raw


def annotate_episode_fields(item: MediaFile) -> None:
    """Fill show/season/episode from the filename or Jellyfin folder layout."""
    if item.season is not None and item.episode is not None and item.show_title:
        return
    parsed = parse_loose_filename(item.path.name)
    if parsed and parsed.get("kind") == "tv":
        if not item.show_title:
            raw_show = str(parsed.get("show") or "")
            item.show_title = _display_show_name(raw_show) or None
        if item.season is None:
            item.season = int(parsed["season"])
        if item.episode is None:
            item.episode = int(parsed["episode"])
        if not item.episode_title and parsed.get("episode_title"):
            item.episode_title = str(parsed["episode_title"])
        return
    tag = parse_episode_tag(item.path.name)
    if not tag:
        return
    season, episode = tag
    if item.season is None:
        item.season = season
    if item.episode is None:
        item.episode = episode
    parent = item.path.parent
    if SEASON_DIR.match(parent.name):
        show_folder = parent.parent.name
        title, _year = parse_movie_label(show_folder)
        if not item.show_title:
            item.show_title = title or show_folder
    if not item.episode_title:
        stem = item.path.stem
        found = EPISODE.search(stem)
        if found:
            tail = stem[found.end() :].strip(" -._")
            tail = QUALITY_TAGS.sub("", tail)
            tail = re.sub(r"\s+", " ", tail).strip(" -._")
            if tail:
                item.episode_title = clean_title(tail)


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
    from localcable.progress import note_files, note_probe

    probe = probe_fn or probe_media
    media: list[MediaFile] = []
    dirty = False
    note_files(len(files))
    for file_path in files:
        note_probe(file_path.name)
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
    series_renditions: dict[Path, dict[str, list]] = {}
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
        from localcable.transcode import collapse_rendition_files

        grouped = collapse_rendition_files(files)
        series_files[series] = [primary for primary, _rends in grouped]
        series_renditions[series] = {
            str(primary.resolve()): rends for primary, rends in grouped
        }

    channels: list[Channel] = []
    for number, name, folder in assign_channel_numbers(parsed):
        media, d = _probe_many(
            series_files.get(folder, []),
            probe_runner=probe_runner,
            probe_fn=probe_fn,
            cache=cache,
        )
        dirty = dirty or d
        rmap = series_renditions.get(folder, {})
        for item in media:
            rends = rmap.get(str(item.path.resolve())) or []
            item.renditions = [r.to_dict() for r in rends]
            annotate_episode_fields(item)
            tag = parse_episode_tag(item.path.name)
            if tag:
                season, episode = tag
                pretty = f"S{season:02d}E{episode:02d}"
                if pretty.lower() not in item.title.lower():
                    item.title = f"{pretty} · {item.title}"
        explicit_number, _explicit_name = parse_channel_folder_name(folder.name)
        channels.append(
            Channel(
                number=number,
                name=name,
                folder_path=folder.resolve(),
                media=media,
                schedule_mode=mode,
                number_explicit=explicit_number is not None,
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
    folder_rends: dict[str, list] = {}
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
                from localcable.transcode import collapse_rendition_files

                grouped = collapse_rendition_files(videos)
                grouped.sort(key=lambda row: natural_key(row[0].name))
                primary, rends = grouped[0]
                files.append(primary)
                folder_rends[str(primary.resolve())] = rends
        elif is_video_file(child):
            files.append(child)
    from localcable.transcode import collapse_rendition_files

    grouped = collapse_rendition_files(files)
    rendition_map = {str(primary.resolve()): rends for primary, rends in grouped}
    rendition_map.update(folder_rends)
    files = [primary for primary, _rends in grouped]
    media, dirty = _probe_many(files, probe_runner=probe_runner, probe_fn=probe_fn, cache=cache)
    for item in media:
        rends = rendition_map.get(str(item.path.resolve())) or []
        item.renditions = [r.to_dict() for r in rends]
        title, year = parse_movie_label(item.path.parent.name if item.path.parent != root else item.path.stem)
        if title:
            item.title = f"{title} ({year})" if year else title
            if year:
                item.year = year
    if dirty and cache_file is not None:
        _save_probe_cache(cache_file, cache)
    number, name = parse_channel_folder_name(root.name)
    explicit = number is not None
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
            number_explicit=explicit,
        )
    ]


def _prefix_series_titles(channel: Channel) -> None:
    title, _year = parse_movie_label(channel.name)
    prefix = title or channel.name
    if not prefix:
        return
    for item in channel.media:
        annotate_episode_fields(item)
        if not item.show_title:
            item.show_title = prefix
        if prefix.lower() not in item.title.lower():
            item.title = f"{prefix} · {item.title}"


def _collect_videos(folder: Path) -> list[Path]:
    """Every video under *folder*, skipping extras/trailers and dot dirs."""
    videos: list[Path] = []
    stack = [folder]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError:
            continue
        for child in children:
            if child.name.startswith(".") or _skip_dir(child.name):
                continue
            if child.is_dir():
                stack.append(child)
            elif is_video_file(child):
                videos.append(child)
    videos.sort(key=lambda path: natural_key(str(path)))
    return videos


def scan_music_video_root(
    root: Path | str,
    *,
    default_mode: str = "sequential",
    probe_runner: Callable[..., Any] | None = None,
    cache_dir: Path | str | None = None,
    probe_fn: Callable[..., MediaFile | None] | None = None,
) -> list[Channel]:
    """Each immediate subfolder of a music-video library is a named channel.

    Videos nested further down (artist / album) stay on that channel. Loose
    files in the library root become one Music Videos channel. ``NNN_Name``
    folders keep their number; everything else gets a stable 3-digit number.
    """
    root = Path(root)
    if not root.is_dir():
        return []
    mode: ScheduleMode = "random" if str(default_mode).lower() == "random" else "sequential"
    cache_file = Path(cache_dir) / "probe.json" if cache_dir is not None else None
    cache: dict[str, Any] = _load_probe_cache(cache_file) if cache_file else {}
    try:
        children = list(root.iterdir())
    except OSError as exc:
        log.warning("cannot list music video root %s: %s", root, exc)
        return []
    parsed: list[tuple[int | None, str, Path]] = []
    files_for: dict[Path, list[Path]] = {}
    for child in children:
        if child.name.startswith(".") or _skip_dir(child.name):
            continue
        if not child.is_dir():
            continue
        number, name = parse_channel_folder_name(child.name)
        parsed.append((number, name, child))
        files_for[child] = _collect_videos(child)
    loose = [child for child in children if is_video_file(child)]
    if loose:
        parsed.append((None, "Music Videos", root))
        files_for[root] = sorted(loose, key=lambda path: natural_key(path.name))
    if not parsed:
        return []
    from localcable.transcode import collapse_rendition_files

    channels: list[Channel] = []
    dirty = False
    for number, name, folder in assign_channel_numbers(parsed):
        grouped = collapse_rendition_files(files_for.get(folder, []))
        files = [primary for primary, _rends in grouped]
        rendition_map = {str(primary.resolve()): rends for primary, rends in grouped}
        media, d = _probe_many(files, probe_runner=probe_runner, probe_fn=probe_fn, cache=cache)
        dirty = dirty or d
        for item in media:
            rends = rendition_map.get(str(item.path.resolve())) or []
            item.renditions = [r.to_dict() for r in rends]
        explicit_number, _explicit_name = parse_channel_folder_name(folder.name)
        channels.append(
            Channel(
                number=number,
                name=name,
                folder_path=folder.resolve(),
                media=media,
                schedule_mode=mode,
                number_explicit=explicit_number is not None and folder != root,
                pad_source=False,
            )
        )
    if dirty and cache_file is not None:
        _save_probe_cache(cache_file, cache)
    channels.sort(key=lambda ch: (ch.number, natural_key(ch.name)))
    return channels


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
    custom_channels: Path | str | None = None,
    music_videos: Path | str | None = None,
) -> list[Channel]:
    """Scan a top-level library (Movies/ + Shows/) into genre cable channels.

    Sibling ``custom_channel`` folders use the legacy folder-per-channel layout
    and are added beside the genre lineup. Sibling ``music_video`` folders become
    one named channel per subfolder.
    """
    from localcable.lineup import (
        CUSTOM_CHANNEL_ALIASES,
        MUSIC_VIDEO_ALIASES,
        enrich_genres,
        find_movie_dir,
        find_tv_dir,
        lineup_channels,
        looks_like_movie_library,
        looks_like_tv_library,
        resolve_extra_dir,
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
    genre: list[Channel] = []
    if items:
        enrich_genres(items, fetch=fetch_metadata, opener=opener, cache_dir=cache_dir)
        genre = lineup_channels(
            items, root, default_mode=default_mode, lineup_config=lineup_config
        )
    groups: list[list[Channel]] = [genre]
    custom_dir = resolve_extra_dir(root, custom_channels, CUSTOM_CHANNEL_ALIASES)
    if custom_dir is not None:
        groups.append(exclude_from_padding(scan_media_root(custom_dir, **kwargs)))
    music_dir = resolve_extra_dir(root, music_videos, MUSIC_VIDEO_ALIASES)
    if music_dir is not None:
        groups.append(scan_music_video_root(music_dir, **kwargs))
    if not any(groups):
        return []
    return merge_channels(*groups)


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
        custom = getattr(lib, "custom_channels", None)
        music = getattr(lib, "music_videos", None)
        lib_auto = {
            **auto_kwargs,
            "custom_channels": custom,
            "music_videos": music,
        }
        if kind in {"auto", "lineup", "cable", "jellyfin"}:
            groups.append(scan_auto_root(path, **lib_auto))
            continue
        if kind in {"music", "music_video", "music_videos"}:
            groups.append(scan_music_video_root(path, **kwargs))
            continue
        if kind == "tv":
            base = scan_tv_root(path, **kwargs)
        elif kind in {"movie", "movies"}:
            base = scan_movies_root(path, **kwargs)
        else:
            detected = detect_library_kind(path) if auto_channels else "channels"
            if detected == "auto":
                groups.append(scan_auto_root(path, **lib_auto))
                continue
            if detected == "tv":
                base = scan_tv_root(path, **kwargs)
            elif detected == "movies":
                base = scan_movies_root(path, **kwargs)
            else:
                base = scan_media_root(path, **kwargs)
        groups.append(_with_extras(base, path, custom, music, kwargs))
    return merge_channels(*groups)


def _existing_dir(path: Path | str | None) -> Path | None:
    if path is None or not str(path).strip():
        return None
    candidate = Path(path).expanduser()
    return candidate if candidate.is_dir() else None


def _same_dir(left: Path, right: Path) -> bool:
    try:
        return left.resolve() == right.resolve()
    except OSError:
        return left == right


def _with_extras(
    base: list[Channel],
    root: Path,
    custom_channels: Path | str | None,
    music_videos: Path | str | None,
    kwargs: dict[str, Any],
) -> list[Channel]:
    """Folder-per-channel and music-video dirs beside a tv, movies, or legacy library."""
    groups = [base]
    custom_dir = _existing_dir(custom_channels)
    if custom_dir is not None and not _same_dir(custom_dir, root):
        groups.append(exclude_from_padding(scan_media_root(custom_dir, **kwargs)))
    music_dir = _existing_dir(music_videos)
    if music_dir is not None and not _same_dir(music_dir, root):
        groups.append(scan_music_video_root(music_dir, **kwargs))
    if len(groups) == 1:
        return base
    return merge_channels(*groups)
