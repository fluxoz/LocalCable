"""Package a media file as MPEG-DASH for the in-page dash.js player."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

SAFE_ID = re.compile(r"^[0-9a-fA-F]{8,64}$")
SAFE_NAME = re.compile(r"^[\w.\-]+$")
DIRECT_SUFFIXES = {".mp4", ".m4v", ".mov"}
COPY_VIDEO = {"h264", "avc1"}
COPY_AUDIO = {"aac", "mp4a"}
PACK_FORMAT = "3"

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
    run = runner or subprocess.run
    argv = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name",
        "-of",
        "json",
        str(src),
    ]
    try:
        proc = run(argv, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False
    if getattr(proc, "returncode", 1) != 0:
        return False
    try:
        payload = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return False
    streams = payload.get("streams") or []
    video = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"]
    audio = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]
    if not video:
        return False
    if str(video[0].get("codec_name") or "").lower() not in COPY_VIDEO:
        return False
    for item in audio:
        if str(item.get("codec_name") or "").lower() not in COPY_AUDIO:
            return False
    return True


def can_direct_play(path: Path | str, *, copy_ok: Callable[[Path], bool] | None = None) -> bool:
    """True when the browser can play the original file with HTTP Range (no DASH)."""
    src = Path(path)
    if src.suffix.lower() not in DIRECT_SUFFIXES:
        return False
    check = copy_ok or codecs_allow_copy
    try:
        return bool(check(src))
    except Exception:  # noqa: BLE001
        return False


def content_id(path: Path | str, *, start_seconds: float = 0.0) -> str:
    src = Path(path).expanduser()
    try:
        resolved = src.resolve()
        stat = resolved.stat()
        token = f"{PACK_FORMAT}|{resolved}|{stat.st_mtime_ns}|{stat.st_size}|{int(start_seconds)}"
    except OSError:
        token = f"{PACK_FORMAT}|{src}|{int(start_seconds)}"
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:20]


def dash_argv(
    src: Path,
    dest_dir: Path,
    *,
    transcode: bool = False,
    start_seconds: float = 0.0,
) -> list[str]:
    mpd = dest_dir / "manifest.mpd"
    argv = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
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
            "scale=-2:'min(720,ih)'",
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
    else:
        argv += ["-c", "copy"]
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
        runner: RunFn | None = None,
    ) -> None:
        self.root = Path(cache_dir) / "dash"
        self._popen = popen or subprocess.Popen
        self._which = which or shutil.which
        self._sleep = sleep or time.sleep
        self._runner = runner
        self._copy_ok = copy_ok or (lambda path: codecs_allow_copy(path, runner=self._runner))
        self._procs: dict[str, Any] = {}

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

    def ensure(
        self,
        program_id: str,
        file_path: Path | str,
        *,
        wait: float = 6.0,
        start_seconds: float = 0.0,
    ) -> Path:
        src = Path(file_path).expanduser().resolve()
        offset = max(0.0, float(start_seconds or 0.0))
        if offset < 3:
            offset = 0.0
        else:
            offset = float(int(offset // 10) * 10)
        pack_id = content_id(src, start_seconds=offset)
        dest = self.root / pack_id
        dest.mkdir(parents=True, exist_ok=True)
        mpd = dest / "manifest.mpd"
        stamp = dest / ".source"
        token = f"{PACK_FORMAT}|{src}|{src.stat().st_mtime_ns}|{offset}"
        if mpd.is_file() and mpd.stat().st_size > 40 and stamp.is_file():
            try:
                if stamp.read_text(encoding="utf-8") == token:
                    return mpd
            except OSError:
                pass
        self._stop(pack_id)
        for child in dest.iterdir():
            if child.name.startswith("."):
                continue
            try:
                child.unlink()
            except OSError:
                pass
        binary = self._which("ffmpeg")
        if not binary:
            raise FileNotFoundError("ffmpeg not found on PATH")
        use_copy = False
        try:
            use_copy = bool(self._copy_ok(src)) and offset == 0.0
        except Exception as exc:  # noqa: BLE001
            log.debug("DASH codec probe failed for %s: %s", src.name, exc)
        if use_copy:
            argv = dash_argv(src, dest, transcode=False, start_seconds=0.0)
            argv[0] = binary
            log.info("DASH package (copy): %s", src.name)
            proc = self._popen(
                argv,
                cwd=str(dest),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL,
            )
            self._procs[pack_id] = proc
            if self._wait_mpd(mpd, wait=min(wait, 2.0)):
                stamp.write_text(token, encoding="utf-8")
                return mpd
            self._stop(pack_id)
        argv = dash_argv(src, dest, transcode=True, start_seconds=offset)
        argv[0] = binary
        log.info("DASH package (transcode from %.0fs): %s", offset, src.name)
        proc = self._popen(
            argv,
            cwd=str(dest),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
        )
        self._procs[pack_id] = proc
        if not self._wait_mpd(mpd, wait=wait):
            raise TimeoutError("DASH manifest was not ready in time")
        stamp.write_text(token, encoding="utf-8")
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
