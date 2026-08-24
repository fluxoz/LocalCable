"""Package a media file as MPEG-DASH for the in-page dash.js player."""

from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

from localcable.metadata import codecs_from_probe, copy_plan, mse_copy_ok, run_ffprobe

log = logging.getLogger(__name__)

SAFE_ID = re.compile(r"^[0-9a-fA-F]{8,64}$")
SAFE_NAME = re.compile(r"^[\w.\-]+$")
DIRECT_SUFFIXES = {".mp4", ".m4v", ".mov"}
PACK_FORMAT = "4"

PopenFn = Callable[..., Any]
RunFn = Callable[..., Any]

DASH_MIME = {
    ".mpd": "application/dash+xml",
    ".m4s": "video/iso.segment",
    ".mp4": "video/mp4",
    ".m4a": "audio/mp4",
    ".cmfv": "video/iso.segment",
    ".cmfa": "audio/mp4",
}


def mime_for(name: str) -> str:
    suffix = Path(name).suffix.lower()
    return DASH_MIME.get(suffix, "application/octet-stream")


def codecs_allow_copy(src: Path | str, *, runner: RunFn | None = None) -> bool:
    """True when MSE/dash.js can play a stream copy (H.264 + AAC, or H.264 silent)."""
    data = run_ffprobe(Path(src), runner=runner, streams_only=True)
    video, audio = codecs_from_probe(data)
    return mse_copy_ok(video, audio)


def classify_copy(src: Path | str, *, runner: RunFn | None = None) -> str:
    """Return ``copy``, ``audio``, or ``xcode`` from a bounded ffprobe."""
    data = run_ffprobe(Path(src), runner=runner, streams_only=True)
    video, audio = codecs_from_probe(data)
    return copy_plan(video, audio)


def can_direct_play(
    path: Path | str,
    *,
    copy_ok: Callable[[Path], bool] | None = None,
    mse_copy: bool | None = None,
) -> bool:
    """True when the browser can play the original file with HTTP Range (no DASH)."""
    src = Path(path)
    if src.suffix.lower() not in DIRECT_SUFFIXES:
        return False
    if mse_copy is not None:
        return bool(mse_copy)
    check = copy_ok or codecs_allow_copy
    try:
        return bool(check(src))
    except Exception:  # noqa: BLE001
        return False


def content_id(
    path: Path | str,
    *,
    start_seconds: float = 0.0,
    filter_mode: str = "off",
) -> str:
    src = Path(path).expanduser()
    filt = str(filter_mode or "off")
    try:
        resolved = src.resolve()
        stat = resolved.stat()
        token = f"{PACK_FORMAT}|{resolved}|{stat.st_mtime_ns}|{stat.st_size}|{int(start_seconds)}|{filt}"
    except OSError:
        token = f"{PACK_FORMAT}|{src}|{int(start_seconds)}|{filt}"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:20]


def dash_argv(
    src: Path,
    dest_dir: Path,
    *,
    transcode: bool = False,
    audio_transcode: bool = False,
    start_seconds: float = 0.0,
    video_filter: str | None = None,
) -> list[str]:
    mpd = dest_dir / "manifest.mpd"
    argv = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-probesize",
        "8000000",
        "-analyzeduration",
        "2000000",
        "-threads",
        "0",
    ]
    if start_seconds and start_seconds > 0.05:
        argv += ["-ss", f"{start_seconds:.3f}"]
    argv += [
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
    ]
    if transcode:
        vf = (video_filter or "").strip() or "scale=-2:'min(720,ih)'"
        argv += [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-pix_fmt",
            "yuv420p",
            "-vf",
            vf,
            "-g",
            "48",
            "-keyint_min",
            "48",
            "-sc_threshold",
            "0",
            "-b:v",
            "2500k",
            "-maxrate",
            "3000k",
            "-bufsize",
            "1500k",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-b:a",
            "96k",
        ]
    elif audio_transcode:
        argv += [
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-ac",
            "2",
            "-b:a",
            "96k",
        ]
        if start_seconds and start_seconds > 0.05:
            argv += ["-avoid_negative_ts", "make_zero"]
    else:
        argv += ["-c", "copy"]
        if start_seconds and start_seconds > 0.05:
            argv += ["-avoid_negative_ts", "make_zero"]
    argv += [
        "-f",
        "dash",
        "-seg_duration",
        "2",
        "-frag_duration",
        "2",
        "-use_template",
        "1",
        "-use_timeline",
        "1",
        "-init_seg_name",
        "init-$RepresentationID$.m4s",
        "-media_seg_name",
        "chunk-$RepresentationID$-$Number%05d$.m4s",
        str(mpd),
    ]
    return argv


class DashPackager:
    """Write DASH manifests under ``cache_dir/dash/<program_id>/``."""

    def __init__(
        self,
        cache_dir: Path | str,
        *,
        popen: PopenFn | None = None,
        which: Callable[[str], str | None] | None = None,
        sleep: Callable[[float], None] | None = None,
        copy_ok: Callable[[Path], bool] | None = None,
        copy_plan_fn: Callable[[Path], str | None] | None = None,
        runner: RunFn | None = None,
    ) -> None:
        self.root = Path(cache_dir) / "dash"
        self._popen = popen or subprocess.Popen
        self._which = which or shutil.which
        self._sleep = sleep or time.sleep
        self._runner = runner
        self._copy_ok = copy_ok or (lambda path: codecs_allow_copy(path, runner=self._runner))
        self._copy_plan_fn = copy_plan_fn
        self._procs: dict[str, Any] = {}
        self._copy_cache: dict[tuple[str, int, int], str] = {}
        self._pack_locks: dict[str, threading.Lock] = {}
        self._meta_lock = threading.Lock()
        self.filter_mode = "off"
        self.filter_preset: str | Path | None = None

    def _pack_lock(self, pack_id: str) -> threading.Lock:
        with self._meta_lock:
            lock = self._pack_locks.get(pack_id)
            if lock is None:
                lock = threading.Lock()
                self._pack_locks[pack_id] = lock
            return lock

    def _running(self, proc: Any) -> bool:
        poll = getattr(proc, "poll", None)
        if poll is None:
            return False
        try:
            return poll() is None
        except Exception:  # noqa: BLE001
            return False

    def _cached_plan(self, src: Path) -> str:
        try:
            stat = src.stat()
            key = (str(src), int(stat.st_mtime_ns), int(stat.st_size))
        except OSError:
            key = None
        if key is not None:
            hit = self._copy_cache.get(key)
            if hit is not None:
                return hit
        plan = "xcode"
        try:
            if self._copy_plan_fn is not None:
                hinted = self._copy_plan_fn(src)
                if hinted in {"copy", "audio", "xcode"}:
                    plan = hinted
                elif hinted is None and bool(self._copy_ok(src)):
                    plan = "copy"
                elif hinted is None:
                    plan = classify_copy(src, runner=self._runner)
            elif bool(self._copy_ok(src)):
                plan = "copy"
            else:
                plan = classify_copy(src, runner=self._runner)
        except Exception as exc:  # noqa: BLE001
            log.debug("DASH codec probe failed for %s: %s", src.name, exc)
            plan = "xcode"
        if key is not None:
            if len(self._copy_cache) >= 2048:
                self._copy_cache.clear()
            self._copy_cache[key] = plan
        return plan

    def _clean_dest(self, dest: Path) -> None:
        for child in dest.iterdir():
            if child.name.startswith("."):
                continue
            try:
                child.unlink()
            except OSError:
                pass

    def _stamp_matches(self, stamp: Path, token: str) -> bool:
        if not stamp.is_file():
            return False
        try:
            return stamp.read_text(encoding="utf-8") == token
        except OSError:
            return False

    def manifest_url(self, program_id: str) -> str:
        return f"/dash/{program_id}/manifest.mpd"

    def resolve_file(self, program_id: str, name: str) -> Path | None:
        if not SAFE_ID.match(program_id) or not SAFE_NAME.match(name):
            return None
        path = (self.root / program_id / name).resolve()
        try:
            path.relative_to(self.root.resolve())
        except ValueError:
            return None
        return path if path.is_file() else None

    def _child_env(self) -> dict[str, str]:
        from localcable.crt import find_frei0r_ntscrs

        env = os.environ.copy()
        plugin = find_frei0r_ntscrs(env)
        if plugin is not None:
            folder = str(plugin.parent)
            existing = env.get("FREI0R_PATH", "")
            sep = os.pathsep
            parts = [p for p in existing.split(sep) if p]
            if folder not in parts:
                env["FREI0R_PATH"] = folder if not existing else f"{folder}{sep}{existing}"
        return env

    def ensure(
        self,
        program_id: str,
        file_path: Path | str,
        *,
        wait: float = 20.0,
        start_seconds: float = 0.0,
        filter_mode: str | None = None,
        filter_preset: str | Path | None = None,
    ) -> Path:
        from localcable.crt import lavfi_graph, normalize_filter

        src = Path(file_path).expanduser().resolve()
        offset = max(0.0, float(start_seconds or 0.0))
        if offset < 3:
            offset = 0.0
        else:
            offset = float(int(offset // 10) * 10)
        mode = normalize_filter(filter_mode if filter_mode is not None else self.filter_mode)
        preset = filter_preset if filter_preset is not None else self.filter_preset
        vf = lavfi_graph(mode, explicit_preset=preset) if mode in {"ntsc", "vhs"} else ""
        pack_id = content_id(src, start_seconds=offset, filter_mode=mode)
        dest = self.root / pack_id
        dest.mkdir(parents=True, exist_ok=True)
        mpd = dest / "manifest.mpd"
        stamp = dest / ".source"
        token = f"{PACK_FORMAT}|{src}|{src.stat().st_mtime_ns}|{offset}|{mode}|{preset or ''}"
        with self._pack_lock(pack_id):
            return self._ensure_locked(
                pack_id,
                src,
                dest,
                mpd,
                stamp,
                token,
                wait=wait,
                offset=offset,
                mode=mode,
                vf=vf,
            )

    def _ensure_locked(
        self,
        pack_id: str,
        src: Path,
        dest: Path,
        mpd: Path,
        stamp: Path,
        token: str,
        *,
        wait: float,
        offset: float,
        mode: str,
        vf: str,
    ) -> Path:
        if mpd.is_file() and mpd.stat().st_size > 40 and self._stamp_matches(stamp, token):
            return mpd
        existing = self._procs.get(pack_id)
        if self._stamp_matches(stamp, token) and existing is not None and self._running(existing):
            if self._wait_mpd(mpd, wait=wait):
                return mpd
            raise TimeoutError("DASH manifest was not ready in time")
        self._stop(pack_id)
        self._clean_dest(dest)
        binary = self._which("ffmpeg")
        if not binary:
            raise FileNotFoundError("ffmpeg not found on PATH")
        plan = "xcode" if vf else self._cached_plan(src)
        child_env = self._child_env()
        if plan in {"copy", "audio"}:
            argv = dash_argv(
                src,
                dest,
                transcode=False,
                audio_transcode=plan == "audio",
                start_seconds=offset,
            )
            argv[0] = binary
            log.info("DASH package (%s from %.0fs): %s", plan, offset, src.name)
            proc = self._popen(
                argv,
                cwd=str(dest),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
                env=child_env,
            )
            self._procs[pack_id] = proc
            try:
                stamp.write_text(token, encoding="utf-8")
            except OSError:
                pass
            if self._wait_mpd(mpd, wait=wait):
                return mpd
            if self._running(proc):
                raise TimeoutError("DASH manifest was not ready in time")
            log.warning("DASH %s exited without a manifest; transcoding %s", plan, src.name)
            self._stop(pack_id)
            self._clean_dest(dest)
        argv = dash_argv(
            src,
            dest,
            transcode=True,
            start_seconds=offset,
            video_filter=vf or None,
        )
        argv[0] = binary
        log.info("DASH package (transcode from %.0fs filter=%s): %s", offset, mode, src.name)
        proc = self._popen(
            argv,
            cwd=str(dest),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            env=child_env,
        )
        self._procs[pack_id] = proc
        try:
            stamp.write_text(token, encoding="utf-8")
        except OSError:
            pass
        if not self._wait_mpd(mpd, wait=wait):
            raise TimeoutError("DASH manifest was not ready in time")
        return mpd

    def _wait_mpd(self, mpd: Path, *, wait: float) -> bool:
        deadline = time.time() + max(wait, 0.2)
        while time.time() < deadline:
            if mpd.is_file() and mpd.stat().st_size > 40:
                return True
            self._sleep(0.15)
        return mpd.is_file() and mpd.stat().st_size > 40

    def _stop(self, program_id: str) -> None:
        proc = self._procs.pop(program_id, None)
        if proc is None:
            return
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
