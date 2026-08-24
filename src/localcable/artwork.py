"""Cover art: user sidecars first, then embedded stills, then keyless online fetch."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
SIDECAR_SUFFIXES = ("", "-poster", "-cover", "-thumb", ".poster", ".cover")
FOLDER_STEMS = ("poster", "cover", "folder", "show", "thumbnail", "thumb")
USER_AGENT = "LocalCable/0.1 (offline-first; keyless artwork)"

OpenFn = Callable[..., Any]
RunFn = Callable[..., Any]


def _is_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTS and path.stat().st_size > 24


def find_sidecar(video_path: Path | str) -> Path | None:
    """Image next to the video: ``show.jpg``, ``show-poster.png``, etc."""
    video = Path(video_path)
    parent = video.parent
    stem = video.stem
    for suffix in SIDECAR_SUFFIXES:
        for ext in IMAGE_EXTS:
            for name in (f"{stem}{suffix}{ext}", f"{stem}{suffix}{ext.upper()}"):
                candidate = parent / name
                if _is_image(candidate):
                    return candidate
    return None


def find_folder_poster(folder: Path | str) -> Path | None:
    """Channel-level ``poster.jpg`` / ``cover.png`` / ``folder.jpg``."""
    root = Path(folder)
    if not root.is_dir():
        return None
    for stem in FOLDER_STEMS:
        for ext in IMAGE_EXTS:
            for name in (f"{stem}{ext}", f"{stem}{ext.upper()}"):
                candidate = root / name
                if _is_image(candidate):
                    return candidate
    return None


def find_local_art(video_path: Path | str, folder: Path | str | None = None) -> Path | None:
    video = Path(video_path)
    sidecar = find_sidecar(video)
    if sidecar is not None:
        return sidecar
    return find_folder_poster(folder if folder is not None else video.parent)


def _cache_path(cache_dir: Path, kind: str, key: str, ext: str = ".jpg") -> Path:
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:20]
    return Path(cache_dir) / "art" / kind / f"{digest}{ext}"


def extract_embedded_art(
    video_path: Path | str,
    dest: Path,
    *,
    runner: RunFn | None = None,
) -> bool:
    """Copy an attached poster stream from the media file, if one exists."""
    run = runner or subprocess.run
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    maps = (
        ["-map", "0:v:m:mimetype:image/jpeg"],
        ["-map", "0:v:m:mimetype:image/png"],
        ["-map", "0:v:m:attached_pic"],
    )
    for mapping in maps:
        if dest.exists():
            try:
                dest.unlink()
            except OSError:
                pass
        argv = [
            "ffmpeg",
            "-y",
            "-i",
            str(video_path),
            *mapping,
            "-an",
            "-frames:v",
            "1",
            str(dest),
        ]
        try:
            proc = run(argv, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            return False
        except Exception as exc:  # noqa: BLE001
            log.debug("embedded art extract failed for %s: %s", video_path, exc)
            return False
        if getattr(proc, "returncode", 1) == 0 and _is_image(dest):
            return True
    return False


def _open(req: urllib.request.Request, opener: OpenFn | None, timeout: float):
    open_fn = opener or urllib.request.urlopen
    return open_fn(req, timeout=timeout)


def _download_image(url: str, dest: Path, opener: OpenFn | None, timeout: float = 4.0) -> bool:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _open(req, opener, timeout) as resp:
            data = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return False
    if not isinstance(data, (bytes, bytearray)) or len(data) < 32:
        return False
    head = bytes(data[:16])
    if not (
        head.startswith(b"\xff\xd8")
        or head.startswith(b"\x89PNG\r\n\x1a\n")
        or head.startswith(b"RIFF")
        or head.startswith(b"GIF8")
        or b"WEBP" in head
    ):
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(bytes(data))
    tmp.replace(dest)
    return _is_image(dest)


def fetch_tvmaze_art(title: str, dest: Path, opener: OpenFn | None = None) -> bool:
    query = urllib.parse.quote(title)
    url = f"https://api.tvmaze.com/singlesearch/shows?q={query}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with _open(req, opener, 4.0) as resp:
            payload = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    image = payload.get("image") or {}
    if not isinstance(image, dict):
        return False
    art_url = image.get("original") or image.get("medium")
    if not art_url:
        return False
    return _download_image(str(art_url), dest, opener)


def _itunes_hires(url: str) -> str:
    return re.sub(r"\d+x\d+bb", "600x600bb", url)


def fetch_itunes_art(title: str, dest: Path, opener: OpenFn | None = None) -> bool:
    query = urllib.parse.quote(title)
    searches = (
        f"https://itunes.apple.com/search?term={query}&media=tvShow&entity=tvSeason&limit=1",
        f"https://itunes.apple.com/search?term={query}&media=movie&entity=movie&limit=1",
    )
    for url in searches:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with _open(req, opener, 4.0) as resp:
                payload = json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        results = payload.get("results") or []
        if not results or not isinstance(results[0], dict):
            continue
        art_url = results[0].get("artworkUrl100") or results[0].get("artworkUrl60")
        if not art_url:
            continue
        if _download_image(_itunes_hires(str(art_url)), dest, opener):
            return True
    return False


def resolve_artwork(
    *,
    video_path: Path | str | None,
    title: str | None,
    folder: Path | str | None = None,
    cache_dir: Path | str | None = None,
    fetch: bool = True,
    opener: OpenFn | None = None,
    runner: RunFn | None = None,
) -> Path | None:
    """Pick cover art. User files win; network is a last resort and never required."""
    video = Path(video_path) if video_path else None
    if video is not None:
        local = find_local_art(video, folder if folder is not None else video.parent)
        if local is not None:
            return local

    if folder is not None and video is None:
        folder_art = find_folder_poster(folder)
        if folder_art is not None:
            return folder_art

    cache_root = Path(cache_dir) if cache_dir is not None else None
    if cache_root is not None and video is not None:
        try:
            key = str(video.resolve())
        except OSError:
            key = str(video)
        embedded = _cache_path(cache_root, "embedded", key)
        if _is_image(embedded):
            return embedded
        if extract_embedded_art(video, embedded, runner=runner) and _is_image(embedded):
            return embedded

    if fetch and title and cache_root is not None:
        fetched = _cache_path(cache_root, "fetch", title.strip().lower())
        if _is_image(fetched):
            return fetched
        if fetch_tvmaze_art(title, fetched, opener=opener) and _is_image(fetched):
            return fetched
        if fetch_itunes_art(title, fetched, opener=opener) and _is_image(fetched):
            return fetched

    return None
