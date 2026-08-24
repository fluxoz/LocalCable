"""Auto cable lineup: find Movies/Shows, bucket by genre, invent channel names."""

from __future__ import annotations

import logging
import re
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from localcable.models import Channel, MediaFile, ScheduleMode

log = logging.getLogger(__name__)

OpenFn = Callable[..., Any]

MOVIE_DIR_ALIASES = {
    "movies",
    "movie",
    "films",
    "film",
    "cinema",
    "feature films",
}
TV_DIR_ALIASES = {
    "shows",
    "show",
    "tv",
    "tv shows",
    "tvshows",
    "tv series",
    "series",
    "television",
    "anime",
}

SEASON_DIR = re.compile(r"^(?:season|series)[\s._-]*(?P<num>\d{1,2})$", re.I)
EPISODE = re.compile(r"[Ss](?P<season>\d{1,2})[Ee](?P<episode>\d{1,2})")
MOVIE_YEAR = re.compile(
    r"^(?P<title>.+?)\s*\((?P<year>19\d{2}|20\d{2}|21\d{2})\)",
)
GENRE_TAG = re.compile(r"<genre>\s*([^<]+?)\s*</genre>", re.I)
SKIP_DIR = {
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


@dataclass(frozen=True)
class LineupSlot:
    number: int
    name: str
    keywords: tuple[str, ...]


# Invented cable brands. First match wins, so specific genres sit above Drama.
LINEUP: tuple[LineupSlot, ...] = (
    LineupSlot(17, "Nightfall", ("horror", "slasher")),
    LineupSlot(13, "Thunderbolt", ("action", "adventure", "war", "martial arts")),
    LineupSlot(15, "After Dark", ("crime", "thriller", "mystery", "suspense", "noir")),
    LineupSlot(20, "Starline", ("science fiction", "sci fi", "scifi", "fantasy")),
    LineupSlot(4, "Toonbox", ("animation", "anime", "kids", "children", "family", "cartoon")),
    LineupSlot(6, "Chuckle", ("comedy", "sitcom")),
    LineupSlot(11, "Heartstring", ("romance", "romantic")),
    LineupSlot(8, "Worldscope", ("documentary", "history", "biography", "news", "reality", "nature")),
    LineupSlot(28, "Gridiron", ("sport", "sports")),
    LineupSlot(31, "Jukebox", ("music", "musical")),
    LineupSlot(24, "Dustbowl", ("western",)),
    LineupSlot(22, "Prime", ("drama",)),
)

FALLBACK_SLOT = LineupSlot(2, "Local 8", ())


def _norm_genre(text: str) -> str:
    blob = text.lower().replace("&", " ").replace("/", " ").replace("-", " ").replace("_", " ")
    blob = blob.replace("sciencefiction", "science fiction")
    return re.sub(r"\s+", " ", blob).strip()


def configured_lineup(cfg: Any = None) -> tuple[tuple[LineupSlot, ...], LineupSlot]:
    """Apply settings.yaml names/channels on top of the default invented lineup."""
    slots: list[LineupSlot] = list(LINEUP)
    fallback = FALLBACK_SLOT
    if cfg is None:
        return tuple(slots), fallback
    custom = getattr(cfg, "channels", None) or []
    built: list[LineupSlot] = []
    for row in custom:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        genres = row.get("genres") or row.get("keywords") or ()
        number = int(row.get("number") or 0) or fallback.number
        built.append(LineupSlot(number, name, tuple(str(g).lower() for g in genres)))
    if built:
        slots = built
    names = {str(k).strip().lower(): str(v).strip() for k, v in (getattr(cfg, "names", None) or {}).items() if v}
    renamed: list[LineupSlot] = []
    for slot in slots:
        new_name = names.get(slot.name.lower()) or names.get(str(slot.number))
        if not new_name:
            for keyword in slot.keywords:
                if keyword in names:
                    new_name = names[keyword]
                    break
        renamed.append(LineupSlot(slot.number, new_name, slot.keywords) if new_name else slot)
    slots = renamed
    fallback_name = getattr(cfg, "fallback", None)
    fallback_number = getattr(cfg, "fallback_number", None)
    if "local 8" in names and not fallback_name:
        fallback_name = names["local 8"]
    if fallback_name or fallback_number is not None:
        fallback = LineupSlot(
            int(fallback_number) if fallback_number is not None else fallback.number,
            str(fallback_name or fallback.name),
            (),
        )
    return tuple(slots), fallback


def pick_slot(
    genre: str | None,
    *,
    slots: tuple[LineupSlot, ...] | None = None,
    fallback: LineupSlot | None = None,
) -> LineupSlot:
    """Map a free-text genre (possibly comma-separated) onto a lineup channel."""
    table = slots if slots is not None else LINEUP
    miss = fallback if fallback is not None else FALLBACK_SLOT
    blob = _norm_genre(genre or "")
    if not blob:
        return miss
    for slot in table:
        for keyword in slot.keywords:
            if keyword in blob:
                return slot
    return miss


def find_named_subdir(root: Path | str, aliases: set[str]) -> Path | None:
    root = Path(root)
    if not root.is_dir():
        return None
    try:
        children = [p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError:
        return None
    by_lower = {p.name.lower(): p for p in children}
    for alias in aliases:
        if alias in by_lower:
            return by_lower[alias]
    return None


def find_tv_dir(root: Path | str) -> Path | None:
    return find_named_subdir(root, TV_DIR_ALIASES)


def find_movie_dir(root: Path | str) -> Path | None:
    return find_named_subdir(root, MOVIE_DIR_ALIASES)


def _child_dirs(root: Path) -> list[Path]:
    try:
        return [
            p
            for p in root.iterdir()
            if p.is_dir() and not p.name.startswith(".") and p.name.lower() not in SKIP_DIR
        ]
    except OSError:
        return []


def looks_like_tv_library(root: Path | str) -> bool:
    root = Path(root)
    for series in _child_dirs(root):
        try:
            kids = list(series.iterdir())
        except OSError:
            continue
        if any(p.is_dir() and SEASON_DIR.match(p.name) for p in kids):
            return True
        if any(p.is_file() and EPISODE.search(p.name) for p in kids):
            return True
    return False


def looks_like_movie_library(root: Path | str) -> bool:
    root = Path(root)
    if looks_like_tv_library(root):
        return False
    dirs = _child_dirs(root)
    if not dirs:
        return False
    hits = sum(1 for p in dirs if MOVIE_YEAR.match(p.name))
    return hits >= 1 and hits >= (len(dirs) + 1) // 2


def detect_library_kind(root: Path | str) -> str:
    """Guess auto / tv / movies / channels from a directory's children."""
    root = Path(root)
    if not root.is_dir():
        return "channels"
    if find_tv_dir(root) is not None or find_movie_dir(root) is not None:
        return "auto"
    if looks_like_tv_library(root):
        return "auto"
    if looks_like_movie_library(root):
        return "auto"
    return "channels"


def is_episode(media: MediaFile) -> bool:
    if EPISODE.search(media.path.name):
        return True
    return bool(SEASON_DIR.match(media.path.parent.name))


def series_key(media: MediaFile) -> str:
    if SEASON_DIR.match(media.path.parent.name):
        return str(media.path.parent.parent)
    return str(media.path.parent)


def mix_playlist(items: list[MediaFile]) -> list[Path]:
    """Weave TV episodes (kept in series order) with movies for a cable-like mix."""
    buckets: dict[str, deque[MediaFile]] = {}
    movies: deque[MediaFile] = deque()
    for item in items:
        if is_episode(item):
            buckets.setdefault(series_key(item), deque()).append(item)
        else:
            movies.append(item)
    queues = [buckets[key] for key in sorted(buckets)]
    out: list[MediaFile] = []
    while queues or movies:
        alive: list[deque[MediaFile]] = []
        for queue in queues:
            if queue:
                out.append(queue.popleft())
                if queue:
                    alive.append(queue)
        queues = alive
        if movies:
            out.append(movies.popleft())
    return [item.path for item in out]


def read_nfo_genres(*paths: Path) -> str | None:
    found: list[str] = []
    seen: set[str] = set()
    for path in paths:
        if path is None or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for match in GENRE_TAG.finditer(text):
            genre = match.group(1).strip()
            key = genre.lower()
            if genre and key not in seen:
                seen.add(key)
                found.append(genre)
    if not found:
        return None
    return ", ".join(found)


def nfo_paths_for(media: MediaFile) -> list[Path]:
    video = media.path
    parent = video.parent
    paths = [
        video.with_suffix(".nfo"),
        parent / "movie.nfo",
        parent / f"{parent.name}.nfo",
        parent / "tvshow.nfo",
        parent / "season.nfo",
    ]
    if SEASON_DIR.match(parent.name):
        series = parent.parent
        paths.extend(
            [
                series / "tvshow.nfo",
                series / f"{series.name}.nfo",
            ]
        )
    return paths


def enrich_genres(
    items: list[MediaFile],
    *,
    fetch: bool = False,
    opener: OpenFn | None = None,
) -> None:
    """Fill blank MediaFile.genre from NFO, then optional TVMaze / iTunes."""
    from localcable.organize import fetch_movie_metadata, fetch_tv_metadata

    series_items: dict[str, list[MediaFile]] = {}
    movies: list[MediaFile] = []
    for item in items:
        if item.genre:
            continue
        nfo = read_nfo_genres(*nfo_paths_for(item))
        if nfo:
            item.genre = nfo
            continue
        if is_episode(item):
            series_items.setdefault(series_key(item), []).append(item)
        else:
            movies.append(item)

    if not fetch:
        for group in series_items.values():
            shared = next((m.genre for m in group if m.genre), None)
            if shared:
                for item in group:
                    if not item.genre:
                        item.genre = shared
        return

    for key, group in series_items.items():
        if not group:
            continue
        if any(item.genre for item in group):
            shared = next(item.genre for item in group if item.genre)
            for item in group:
                if not item.genre:
                    item.genre = shared
            continue
        show = Path(key).name
        show = MOVIE_YEAR.match(show).group("title") if MOVIE_YEAR.match(show) else show
        tag = EPISODE.search(group[0].path.name)
        season, episode = (int(tag.group("season")), int(tag.group("episode"))) if tag else (1, 1)
        try:
            meta = fetch_tv_metadata(show, season, episode, opener=opener)
        except Exception as exc:  # noqa: BLE001
            log.debug("tv genre lookup failed for %s: %s", show, exc)
            meta = {}
        genre = meta.get("genre")
        for item in group:
            if genre and not item.genre:
                item.genre = str(genre)
            if meta.get("description") and not item.description:
                item.description = str(meta["description"])

    for item in movies:
        if item.genre:
            continue
        title = item.title or item.path.stem
        year = item.year
        match = MOVIE_YEAR.match(title)
        if match:
            title = match.group("title")
            year = year or match.group("year")
        try:
            meta = fetch_movie_metadata(title, year, opener=opener)
        except Exception as exc:  # noqa: BLE001
            log.debug("movie genre lookup failed for %s: %s", title, exc)
            meta = {}
        if meta.get("genre"):
            item.genre = str(meta["genre"])
        if meta.get("description") and not item.description:
            item.description = str(meta["description"])


def lineup_channels(
    items: list[MediaFile],
    root: Path,
    *,
    default_mode: str = "sequential",
    lineup_config: Any = None,
) -> list[Channel]:
    """Bucket media into invented cable channels; skip empty slots."""
    mode: ScheduleMode = "random" if str(default_mode).lower() == "random" else "sequential"
    slots, fallback = configured_lineup(lineup_config)
    buckets: dict[int, list[MediaFile]] = {}
    names: dict[int, str] = {}
    for item in items:
        slot = pick_slot(item.genre, slots=slots, fallback=fallback)
        buckets.setdefault(slot.number, []).append(item)
        names[slot.number] = slot.name
    channels: list[Channel] = []
    for number in sorted(buckets):
        media = buckets[number]
        if not media:
            continue
        playlist = mix_playlist(media)
        channels.append(
            Channel(
                number=number,
                name=names[number],
                folder_path=Path(root).resolve(),
                media=media,
                schedule_mode=mode,
                playlist=playlist,
            )
        )
    return channels
