"""Opt-in auto-organize: parse loose files into the Jellyfin library layout.

Metadata comes from TVMaze (TV) and the iTunes Search API (movies). No API keys.
Existing files are never overwritten.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from localcable.artwork import USER_AGENT, _download_image
from localcable.jellyfin import (
    SKIP_DIR_NAMES,
    is_already_jellyfin_movie,
    is_already_jellyfin_tv,
    jellyfin_movie_path,
    jellyfin_tv_path,
    parse_loose_filename,
)
from localcable.scan import is_video_file

log = logging.getLogger(__name__)

OpenFn = Callable[..., Any]


@dataclass
class OrganizeMove:
    source: Path
    dest: Path
    kind: str
    title: str


@dataclass
class OrganizeResult:
    moved: list[OrganizeMove] = field(default_factory=list)
    skipped: list[tuple[Path, str]] = field(default_factory=list)


def _open(req: urllib.request.Request, opener: OpenFn | None, timeout: float):
    open_fn = opener or urllib.request.urlopen
    return open_fn(req, timeout=timeout)


def _json_get(url: str, opener: OpenFn | None, timeout: float = 4.0) -> Any:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _open(req, opener, timeout) as resp:
            return json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return None


def fetch_tv_metadata(
    show: str,
    season: int,
    episode: int,
    opener: OpenFn | None = None,
) -> dict[str, Any]:
    """Look up a series/episode on TVMaze. Returns whatever fields are available."""
    query = urllib.parse.quote(show)
    payload = _json_get(f"https://api.tvmaze.com/singlesearch/shows?q={query}", opener)
    if not isinstance(payload, dict):
        return {}
    name = str(payload.get("name") or show).strip() or show
    premiered = str(payload.get("premiered") or "")
    year = premiered[:4] if len(premiered) >= 4 and premiered[:4].isdigit() else None
    summary = _strip_html(payload.get("summary"))
    show_id = payload.get("id")
    image = payload.get("image") if isinstance(payload.get("image"), dict) else {}
    art_url = (image or {}).get("original") or (image or {}).get("medium")
    episode_title = None
    episode_summary = None
    if show_id is not None:
        ep = _json_get(
            f"https://api.tvmaze.com/shows/{show_id}/episodebynumber?season={int(season)}&number={int(episode)}",
            opener,
        )
        if isinstance(ep, dict):
            episode_title = str(ep.get("name") or "").strip() or None
            episode_summary = _strip_html(ep.get("summary"))
    genres = payload.get("genres") if isinstance(payload.get("genres"), list) else []
    genre = ", ".join(str(g) for g in genres if g) or None
    return {
        "kind": "tv",
        "show": name,
        "year": year,
        "episode_title": episode_title,
        "description": episode_summary or summary,
        "art_url": art_url,
        "genre": genre,
    }


def fetch_movie_metadata(
    title: str,
    year: str | None = None,
    opener: OpenFn | None = None,
) -> dict[str, Any]:
    term = f"{title} {year}" if year else title
    query = urllib.parse.quote(term)
    payload = _json_get(
        f"https://itunes.apple.com/search?term={query}&media=movie&entity=movie&limit=1",
        opener,
    )
    if not isinstance(payload, dict):
        return {}
    results = payload.get("results") or []
    if not results or not isinstance(results[0], dict):
        return {}
    row = results[0]
    name = str(row.get("trackName") or title).strip() or title
    release = str(row.get("releaseDate") or "")
    found_year = release[:4] if len(release) >= 4 and release[:4].isdigit() else year
    art = row.get("artworkUrl100") or row.get("artworkUrl60")
    if isinstance(art, str):
        art = re_hires(art)
    return {
        "kind": "movie",
        "title": name,
        "year": found_year,
        "description": str(row.get("longDescription") or row.get("shortDescription") or "").strip() or None,
        "art_url": art,
        "genre": str(row.get("primaryGenreName") or "").strip() or None,
    }


def re_hires(url: str) -> str:
    return re.sub(r"\d+x\d+bb", "600x600bb", url)


def _strip_html(value: Any) -> str | None:
    if not value:
        return None
    text = re.sub(r"<[^>]+>", " ", str(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def write_nfo(dest_video: Path, parsed: dict[str, Any], meta: dict[str, Any]) -> None:
    nfo = dest_video.with_suffix(".nfo")
    if nfo.exists():
        return
    if parsed.get("kind") == "tv":
        title = meta.get("episode_title") or parsed.get("episode_title") or dest_video.stem
        plot = meta.get("description") or ""
        body = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
            "<episodedetails>\n"
            f"  <title>{_xml(title)}</title>\n"
            f"  <showtitle>{_xml(meta.get('show') or parsed.get('show'))}</showtitle>\n"
            f"  <season>{int(parsed.get('season') or 0)}</season>\n"
            f"  <episode>{int(parsed.get('episode') or 0)}</episode>\n"
            f"  <year>{_xml(meta.get('year') or '')}</year>\n"
            f"  <plot>{_xml(plot)}</plot>\n"
            "</episodedetails>\n"
        )
    else:
        title = meta.get("title") or parsed.get("title") or dest_video.stem
        plot = meta.get("description") or ""
        year = meta.get("year") or parsed.get("year") or ""
        body = (
            "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>\n"
            "<movie>\n"
            f"  <title>{_xml(title)}</title>\n"
            f"  <year>{_xml(year)}</year>\n"
            f"  <plot>{_xml(plot)}</plot>\n"
            "</movie>\n"
        )
    try:
        nfo.write_text(body, encoding="utf-8")
    except OSError as exc:
        log.debug("could not write nfo %s: %s", nfo, exc)


def _xml(value: Any) -> str:
    text = "" if value is None else str(value)
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def save_poster(folder: Path, url: str | None, opener: OpenFn | None) -> None:
    if not url:
        return
    dest = folder / "poster.jpg"
    if dest.exists():
        return
    try:
        _download_image(str(url), dest, opener)
    except Exception as exc:  # noqa: BLE001
        log.debug("poster download failed: %s", exc)


def library_destinations(config: Any) -> tuple[Path | None, Path | None]:
    """Return (tv_root, movies_root) from config libraries."""
    tv: Path | None = None
    movies: Path | None = None
    roots = []
    getter = getattr(config, "library_roots", None)
    if callable(getter):
        roots = list(getter())
    else:
        roots = list(getattr(config, "libraries", []) or [])
    for lib in roots:
        kind = getattr(lib, "kind", "channels")
        path = Path(getattr(lib, "path"))
        if kind == "tv" and tv is None:
            tv = path
        elif kind == "movies" and movies is None:
            movies = path
        elif kind == "jellyfin":
            if tv is None:
                tv = path / "Shows"
            if movies is None:
                movies = path / "Movies"
    return tv, movies


def collect_videos(root: Path, *, recursive: bool = True) -> list[Path]:
    if not root.is_dir():
        return []
    found: list[Path] = []
    try:
        children = list(root.iterdir())
    except OSError as exc:
        log.warning("cannot list %s: %s", root, exc)
        return []
    for child in children:
        if child.name.startswith("."):
            continue
        if child.is_dir():
            if child.name.lower() in SKIP_DIR_NAMES:
                continue
            if recursive:
                found.extend(collect_videos(child, recursive=True))
        elif is_video_file(child):
            found.append(child)
    return found


def planned_destination(
    parsed: dict[str, Any],
    *,
    tv_root: Path | None,
    movies_root: Path | None,
    source: Path,
    meta: dict[str, Any] | None = None,
) -> Path | None:
    meta = meta or {}
    ext = source.suffix
    if parsed.get("kind") == "tv":
        if tv_root is None:
            return None
        show = meta.get("show") or parsed.get("show") or "Unknown"
        year = meta.get("year") or parsed.get("year")
        episode_title = meta.get("episode_title") or parsed.get("episode_title")
        return jellyfin_tv_path(
            tv_root,
            show,
            year,
            int(parsed["season"]),
            int(parsed["episode"]),
            ext,
            episode_title,
        )
    if movies_root is None:
        return None
    title = meta.get("title") or parsed.get("title") or source.stem
    year = meta.get("year") or parsed.get("year")
    return jellyfin_movie_path(movies_root, title, year, ext)


def organize_library(
    config: Any,
    *,
    opener: OpenFn | None = None,
    dry_run: bool = False,
) -> OrganizeResult:
    """Move inbox + loose library files into the Jellyfin folder layout."""
    result = OrganizeResult()
    library_cfg = getattr(config, "library", None)
    if library_cfg is None or not getattr(library_cfg, "auto_organize", False):
        return result
    tv_root, movies_root = library_destinations(config)
    if tv_root is None and movies_root is None:
        log.warning("auto-organize is on but no tv/movies/jellyfin library is configured")
        return result
    fetch = bool(getattr(library_cfg, "fetch_metadata", True))
    sources: list[tuple[Path, str]] = []
    inbox = getattr(library_cfg, "inbox", None)
    if inbox is not None:
        inbox_path = Path(inbox).expanduser()
        for path in collect_videos(inbox_path, recursive=True):
            sources.append((path, "inbox"))
    if tv_root is not None and tv_root.is_dir():
        for path in collect_videos(tv_root, recursive=True):
            if not is_already_jellyfin_tv(path, tv_root):
                sources.append((path, "tv"))
    if movies_root is not None and movies_root.is_dir():
        for path in collect_videos(movies_root, recursive=True):
            if not is_already_jellyfin_movie(path, movies_root):
                sources.append((path, "movies"))

    seen: set[Path] = set()
    for source, _origin in sources:
        try:
            resolved = source.resolve()
        except OSError:
            resolved = source
        if resolved in seen:
            continue
        seen.add(resolved)
        parsed = parse_loose_filename(source.name)
        if not parsed:
            result.skipped.append((source, "unrecognized filename"))
            continue
        if parsed["kind"] == "tv" and tv_root is None:
            result.skipped.append((source, "no tv library"))
            continue
        if parsed["kind"] == "movie" and movies_root is None:
            result.skipped.append((source, "no movies library"))
            continue
        meta: dict[str, Any] = {}
        if fetch:
            try:
                if parsed["kind"] == "tv":
                    meta = fetch_tv_metadata(parsed["show"], parsed["season"], parsed["episode"], opener=opener)
                else:
                    meta = fetch_movie_metadata(parsed.get("title") or source.stem, parsed.get("year"), opener=opener)
            except Exception as exc:  # noqa: BLE001
                log.debug("metadata lookup failed for %s: %s", source.name, exc)
                meta = {}
        dest = planned_destination(
            parsed,
            tv_root=tv_root,
            movies_root=movies_root,
            source=source,
            meta=meta,
        )
        if dest is None:
            result.skipped.append((source, "no destination library"))
            continue
        try:
            if source.resolve() == dest.resolve():
                result.skipped.append((source, "already in place"))
                continue
        except OSError:
            pass
        if dest.exists():
            result.skipped.append((source, "destination exists"))
            continue
        result.moved.append(
            OrganizeMove(
                source=source,
                dest=dest,
                kind=str(parsed["kind"]),
                title=str(meta.get("show") or meta.get("title") or parsed.get("show") or parsed.get("title") or source.stem),
            )
        )
        if dry_run:
            continue
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))
        except OSError as exc:
            log.warning("could not move %s → %s: %s", source, dest, exc)
            result.moved.pop()
            result.skipped.append((source, str(exc)))
            continue
        write_nfo(dest, parsed, meta)
        poster_folder = dest.parent if parsed["kind"] == "movie" else dest.parent.parent
        save_poster(poster_folder, meta.get("art_url"), opener)
        log.info("organized %s → %s", source.name, dest)

    return result
