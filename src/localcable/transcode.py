"""One-time in-place transcode to browser-native H.264 + AAC MP4."""

from __future__ import annotations

import copy
import logging
import os
import re
import subprocess
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from localcable.ffmpeg import (
    encoder_args,
    normalize_hw,
    pick_encoder,
    resolve_ffmpeg,
    resolve_ffprobe,
    scale_filter,
)
from localcable.metadata import codecs_from_probe, duration_from_probe, mse_copy_ok, run_ffprobe

log = logging.getLogger(__name__)

RunFn = Callable[..., Any]

NAMED_HEIGHTS: tuple[int, ...] = (2160, 1440, 1080, 720, 480)
RUNG_STEM = re.compile(r"^(?P<base>.+)\.(?P<h>2160|1440|1080|720|480)p$", re.I)
DIRECT_SUFFIXES = {".mp4", ".m4v"}

# CRF / cap per output height. Native uses the 1080p row unless taller.
RUNG_QUALITY: dict[int, tuple[int, str]] = {
    2160: (20, "20M"),
    1440: (20, "12M"),
    1080: (20, "8M"),
    720: (21, "4M"),
    480: (23, "2M"),
}

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


@dataclass
class Rendition:
    height: int | None
    path: Path
    label: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "height": self.height,
            "path": str(self.path),
            "label": self.label,
        }


class TranscodeCancelled(Exception):
    """Raised when a GUI/CLI cancel stops an in-flight encode."""


@dataclass
class TranscodeJob:
    src: Path
    dest: Path
    height: int | None
    label: str
    skip: bool = False
    reason: str = ""
    duration_seconds: float = 0.0


@dataclass
class TranscodePlan:
    src: Path
    jobs: list[TranscodeJob] = field(default_factory=list)
    replace: list[Path] = field(default_factory=list)


@dataclass
class TranscodeResult:
    planned: int = 0
    encoded: int = 0
    skipped: int = 0
    failed: int = 0
    removed: int = 0
    errors: list[str] = field(default_factory=list)


def normalize_codec(value: Any, default: str = "h264") -> str:
    text = str(value or default).strip().lower().replace(".", "").replace("-", "")
    if text in {"hevc", "h265", "x265"}:
        return "hevc"
    return "h264"


def parse_rungs(value: Any, default: tuple[str, ...] = ("native",)) -> list[str]:
    if value is None:
        items = list(default)
    elif isinstance(value, str):
        items = [part.strip() for part in value.replace(";", ",").split(",")]
    elif isinstance(value, (list, tuple)):
        items = [str(part).strip() for part in value]
    else:
        items = list(default)
    out: list[str] = []
    seen: set[str] = set()
    for raw in items:
        if not raw:
            continue
        key = raw.lower().lstrip()
        if key in {"native", "source", "orig", "original"}:
            label = "native"
        else:
            digits = re.sub(r"[^0-9]", "", key)
            if not digits:
                continue
            height = int(digits)
            if height not in NAMED_HEIGHTS:
                # allow exact source-like values we still treat as a cap
                if height < 144:
                    continue
            label = str(height)
        if label not in seen:
            seen.add(label)
            out.append(label)
    return out or ["native"]


def variant_base(path: Path) -> str:
    match = RUNG_STEM.match(path.stem)
    return match.group("base") if match else path.stem


def variant_height(path: Path) -> int | None:
    match = RUNG_STEM.match(path.stem)
    return int(match.group("h")) if match else None


def variant_key(path: Path) -> tuple[str, str]:
    parent = str(path.parent.resolve()) if path.parent.exists() else str(path.parent)
    return parent, variant_base(path).lower()


def output_name(src: Path, label: str) -> Path:
    base = variant_base(src)
    if label == "native":
        return src.with_name(f"{base}.mp4")
    height = int(re.sub(r"[^0-9]", "", label) or "0")
    return src.with_name(f"{base}.{height}p.mp4")


def collapse_rendition_files(files: Iterable[Path]) -> list[tuple[Path, list[Rendition]]]:
    """Group `Name.1080p.mp4` + `Name.720p.mp4` (+ leftover source) into one title."""
    groups: dict[tuple[str, str], list[Path]] = {}
    order: list[tuple[str, str]] = []
    for path in files:
        key = variant_key(path)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(path)
    collapsed: list[tuple[Path, list[Rendition]]] = []
    for key in order:
        members = groups[key]
        mp4s = [p for p in members if p.suffix.lower() in DIRECT_SUFFIXES]
        playable = mp4s or members
        renditions: list[Rendition] = []
        for path in playable:
            height = variant_height(path)
            label = f"{height}p" if height else "native"
            renditions.append(Rendition(height=height, path=path, label=label))
        renditions.sort(key=lambda r: r.height or 0, reverse=True)
        primary = renditions[0].path if renditions else members[0]
        collapsed.append((primary, renditions))
    return collapsed


def _skip_dir(name: str) -> bool:
    return name.startswith(".") or name.lower() in SKIP_DIR_NAMES


def iter_videos(root: Path) -> list[Path]:
    from localcable.scan import is_video_file

    found: list[Path] = []
    if not root.is_dir():
        return found
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [name for name in dirnames if not _skip_dir(name)]
        folder = Path(dirpath)
        for name in filenames:
            path = folder / name
            if is_video_file(path):
                found.append(path)
    found.sort(key=lambda p: str(p).lower())
    return found


def _video_geometry(probe: dict[str, Any]) -> tuple[int | None, int | None]:
    for stream in probe.get("streams") or []:
        if stream.get("codec_type") == "video":
            try:
                width = int(stream.get("width") or 0) or None
            except (TypeError, ValueError):
                width = None
            try:
                height = int(stream.get("height") or 0) or None
            except (TypeError, ValueError):
                height = None
            return width, height
    return None, None


def _quality_for(height: int | None) -> tuple[int, str]:
    if height is None:
        return RUNG_QUALITY[1080]
    for cap in NAMED_HEIGHTS:
        if height >= cap:
            return RUNG_QUALITY[cap]
    return RUNG_QUALITY[480]


def target_heights(src_height: int | None, rungs: list[str]) -> list[tuple[str, int | None]]:
    """Map requested rungs onto output heights, never upscaling, no duplicates."""
    wanted: list[tuple[str, int | None]] = []
    seen: set[int | None] = set()
    for rung in rungs:
        if rung == "native":
            height = src_height
            label = "native"
        else:
            cap = int(rung)
            if src_height is not None and cap >= src_height:
                height = src_height
                label = "native"
            else:
                height = cap
                label = str(cap)
        if height in seen:
            continue
        seen.add(height)
        wanted.append((label, height))
    return wanted


def already_native(path: Path, probe: dict[str, Any], *, codec: str = "h264") -> bool:
    if path.suffix.lower() not in DIRECT_SUFFIXES:
        return False
    video, audio = codecs_from_probe(probe)
    if codec == "h264":
        return mse_copy_ok(video, audio)
    return (video or "") in {"hevc", "h265"} and all(name in {"aac", "mp4a"} for name in (audio or []))


def dest_for(src: Path, label: str, height: int | None, src_height: int | None, rungs: list[str]) -> Path:
    mixed = any(rung != "native" for rung in rungs)
    if height is None or height == src_height:
        if mixed and src_height in NAMED_HEIGHTS:
            return output_name(src, str(src_height))
        return output_name(src, "native")
    return output_name(src, str(height))


def plan_file(
    src: Path,
    rungs: list[str],
    *,
    codec: str = "h264",
    keep_original: bool = False,
    probe: dict[str, Any] | None = None,
    ffprobe: str | None = None,
    runner: RunFn | None = None,
) -> TranscodePlan:
    data = probe if probe is not None else run_ffprobe(src, runner=runner, binary=ffprobe)
    _width, src_height = _video_geometry(data)
    jobs: list[TranscodeJob] = []
    outputs: list[Path] = []
    for label, height in target_heights(src_height, rungs):
        dest = dest_for(src, label, height, src_height, rungs)
        skip = False
        reason = ""
        dest_res = dest.resolve()
        src_res = src.resolve()
        if dest_res != src_res and dest.exists():
            existing = run_ffprobe(dest, runner=runner, binary=ffprobe)
            if already_native(dest, existing, codec=codec):
                skip = True
                reason = "already exists"
        elif dest_res == src_res and already_native(src, data, codec=codec):
            skip = True
            reason = "already browser-native"
        jobs.append(
            TranscodeJob(
                src=src,
                dest=dest,
                height=height,
                label=label,
                skip=skip,
                reason=reason,
                duration_seconds=float(duration_from_probe(data) or 0.0),
            )
        )
        outputs.append(dest)
    replace: list[Path] = []
    if not keep_original:
        out_res = {path.resolve() for path in outputs}
        if src.resolve() not in out_res:
            replace.append(src)
    return TranscodePlan(src=src, jobs=jobs, replace=replace)


def transcode_argv(
    src: Path,
    dest: Path,
    *,
    ffmpeg: str,
    encoder: str,
    hw_name: str,
    height: int | None,
    crf: int,
    maxrate: str | None,
    copy_audio: bool,
) -> list[str]:
    argv = [
        ffmpeg,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-sn",
        "-dn",
    ]
    vf = scale_filter(hw_name, height)
    if vf:
        argv += ["-vf", vf]
    argv += encoder_args(hw_name, encoder, crf=crf, maxrate=maxrate)
    if copy_audio:
        argv += ["-c:a", "copy"]
    else:
        argv += ["-c:a", "aac", "-ac", "2", "-b:a", "192k"]
    argv += ["-movflags", "+faststart", str(dest)]
    return argv


def _run_ffmpeg(argv: list[str], *, runner: RunFn | None = None) -> None:
    run = runner or subprocess.run
    try:
        proc = run(argv, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg not found") from exc
    if getattr(proc, "returncode", 1) != 0:
        err = (getattr(proc, "stderr", "") or getattr(proc, "stdout", "") or "").strip()
        raise RuntimeError(err[-800:] or f"ffmpeg exit {proc.returncode}")


def _parse_hms(value: str) -> float | None:
    parts = str(value).strip().split(":")
    try:
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + float(parts[2])
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(value)
    except ValueError:
        return None


def progress_seconds(fields: dict[str, str]) -> float | None:
    """Best-effort current output time from an ffmpeg -progress block."""
    if fields.get("out_time_us"):
        try:
            return max(0.0, int(fields["out_time_us"]) / 1_000_000)
        except ValueError:
            return None
    if fields.get("out_time_ms"):
        try:
            raw = int(fields["out_time_ms"])
        except ValueError:
            return None
        # Older ffmpeg labeled microseconds as out_time_ms.
        return max(0.0, raw / 1_000_000 if raw > 10_000_000 else raw / 1000)
    if fields.get("out_time"):
        return _parse_hms(fields["out_time"])
    return None


def _run_ffmpeg_with_progress(
    argv: list[str],
    *,
    duration_seconds: float = 0.0,
    on_progress: Callable[[float], None] | None = None,
    cancel_event: threading.Event | None = None,
    proc_holder: list[Any] | None = None,
    runner: RunFn | None = None,
    popen: Callable[..., Any] | None = None,
) -> None:
    if runner is not None:
        if on_progress:
            on_progress(1.0)
        _run_ffmpeg(argv, runner=runner)
        return
    cmd = list(argv)
    if "-progress" not in cmd:
        cmd[-1:-1] = ["-progress", "pipe:1", "-nostats"]
    spawn = popen or subprocess.Popen
    try:
        proc = spawn(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    except FileNotFoundError as exc:
        raise RuntimeError("ffmpeg not found") from exc
    if proc_holder is not None:
        proc_holder.clear()
        proc_holder.append(proc)
    err_chunks: list[str] = []

    def _drain_err() -> None:
        stream = getattr(proc, "stderr", None)
        if stream is None:
            return
        try:
            err_chunks.append(stream.read() or "")
        except Exception:  # noqa: BLE001
            return

    drain = threading.Thread(target=_drain_err, daemon=True)
    drain.start()
    block: dict[str, str] = {}
    stdout = getattr(proc, "stdout", None)
    try:
        if stdout is not None:
            for raw in stdout:
                if cancel_event is not None and cancel_event.is_set():
                    proc.terminate()
                    raise TranscodeCancelled("cancelled")
                line = raw.strip()
                if not line:
                    continue
                if "=" not in line:
                    continue
                key, value = line.split("=", 1)
                block[key] = value
                if key != "progress":
                    continue
                seconds = progress_seconds(block)
                if on_progress and duration_seconds > 0 and seconds is not None:
                    on_progress(min(1.0, max(0.0, seconds / duration_seconds)))
                elif on_progress and block.get("progress") == "end":
                    on_progress(1.0)
                block = {}
        code = proc.wait()
    finally:
        drain.join(timeout=2)
        if proc_holder is not None:
            proc_holder.clear()
    if cancel_event is not None and cancel_event.is_set():
        raise TranscodeCancelled("cancelled")
    if code not in (0, None):
        err = "".join(err_chunks).strip()
        raise RuntimeError(err[-800:] or f"ffmpeg exit {code}")
    if on_progress:
        on_progress(1.0)


def transcode_library(
    roots: Iterable[Path],
    *,
    rungs: list[str] | None = None,
    codec: str = "h264",
    hw: str = "auto",
    keep_original: bool = False,
    dry_run: bool = False,
    fetch: bool = False,
    ffmpeg: str | None = None,
    runner: RunFn | None = None,
    which: Callable[[str], str | None] | None = None,
    smoke: bool = True,
    on_progress: Callable[[dict[str, Any]], None] | None = None,
    cancel_event: threading.Event | None = None,
    proc_holder: list[Any] | None = None,
    popen: Callable[..., Any] | None = None,
) -> TranscodeResult:
    from localcable.ffmpeg import fetch_ffmpeg

    def emit(payload: dict[str, Any]) -> None:
        if cancel_event is not None and cancel_event.is_set():
            raise TranscodeCancelled("cancelled")
        if on_progress:
            on_progress(payload)

    rung_list = parse_rungs(rungs)
    codec = normalize_codec(codec)
    hw = normalize_hw(hw)
    result = TranscodeResult()
    emit({"phase": "preparing", "library_percent": 0, "file_percent": 0, "message": "Starting"})
    if fetch:
        emit({"phase": "preparing", "message": "Downloading ffmpeg"})
        fetch_ffmpeg()
    binary = ffmpeg or resolve_ffmpeg(which=which)
    probe_bin = resolve_ffprobe(ffmpeg=binary, which=which)
    hw_name, encoder = pick_encoder(binary, codec=codec, hw=hw, runner=runner, smoke=smoke)
    log.info("transcode encoder=%s (%s) rungs=%s", encoder, hw_name, ",".join(rung_list))
    emit({"phase": "scanning", "encoder": encoder, "hw": hw_name, "message": f"Using {encoder}"})

    files: list[Path] = []
    for root in roots:
        files.extend(iter_videos(Path(root)))
    grouped = collapse_rendition_files(files)
    sources: list[Path] = []
    seen: set[Path] = set()
    for primary, renditions in grouped:
        members = [primary] + [r.path for r in renditions]
        originals = [p for p in members if variant_height(p) is None]
        src = originals[0] if originals else primary
        resolved = src.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        sources.append(src)

    work: list[tuple[Path, TranscodePlan, dict[str, Any]]] = []
    file_rows: list[dict[str, Any]] = []
    for src in sources:
        plan = plan_file(
            src,
            rung_list,
            codec=codec,
            keep_original=keep_original,
            ffprobe=probe_bin,
            runner=runner,
        )
        data = run_ffprobe(src, runner=runner, binary=probe_bin)
        work.append((src, plan, data))
        for job in plan.jobs:
            result.planned += 1
            file_rows.append(
                {
                    "src": src.name,
                    "dest": job.dest.name,
                    "label": job.label,
                    "status": "skipped" if job.skip else "pending",
                    "percent": 100 if job.skip else 0,
                    "reason": job.reason,
                }
            )
    total = max(len(file_rows), 1)
    emit(
        {
            "phase": "scanning",
            "encoder": encoder,
            "hw": hw_name,
            "library_total": len(file_rows),
            "library_done": 0,
            "library_percent": 0,
            "files": file_rows,
            "message": f"{len(file_rows)} outputs planned",
        }
    )

    done = 0
    row_i = 0
    for src, plan, data in work:
        video, audio = codecs_from_probe(data)
        copy_audio = bool(audio) and all(name in {"aac", "mp4a"} for name in audio)
        failed_this = False
        for job in plan.jobs:
            row = file_rows[row_i]
            if job.skip:
                result.skipped += 1
                row["status"] = "skipped"
                row["percent"] = 100
                done += 1
                emit(
                    {
                        "phase": "encoding",
                        "encoder": encoder,
                        "hw": hw_name,
                        "library_total": len(file_rows),
                        "library_done": done,
                        "library_percent": round(100.0 * done / total, 1),
                        "file_percent": 100,
                        "current_src": src.name,
                        "current_dest": job.dest.name,
                        "files": file_rows,
                        "message": f"Skipped {src.name}",
                    }
                )
                row_i += 1
                continue
            crf, maxrate = _quality_for(job.height)
            tmp = job.dest.with_name(job.dest.name + ".partial")
            argv = transcode_argv(
                src,
                tmp,
                ffmpeg=binary,
                encoder=encoder,
                hw_name=hw_name,
                height=job.height,
                crf=crf,
                maxrate=maxrate,
                copy_audio=copy_audio,
            )
            log.info("%s -> %s", src.name, job.dest.name)
            row["status"] = "encoding"
            emit(
                {
                    "phase": "encoding",
                    "encoder": encoder,
                    "hw": hw_name,
                    "library_total": len(file_rows),
                    "library_done": done,
                    "library_percent": round(100.0 * done / total, 1),
                    "file_percent": 0,
                    "current_src": str(src),
                    "current_dest": str(job.dest),
                    "files": file_rows,
                    "message": f"{src.name} → {job.dest.name}",
                }
            )
            if dry_run:
                result.skipped += 1
                row["status"] = "skipped"
                row["percent"] = 100
                row["reason"] = "dry-run"
                done += 1
                row_i += 1
                continue

            def _file_frac(frac: float, row=row, done=done, src=src, job=job) -> None:
                row["percent"] = round(100.0 * min(1.0, max(0.0, frac)), 1)
                emit(
                    {
                        "phase": "encoding",
                        "encoder": encoder,
                        "hw": hw_name,
                        "library_total": len(file_rows),
                        "library_done": done,
                        "library_percent": round(100.0 * (done + min(1.0, max(0.0, frac))) / total, 1),
                        "file_percent": row["percent"],
                        "current_src": str(src),
                        "current_dest": str(job.dest),
                        "files": file_rows,
                        "message": f"{src.name} → {job.dest.name}",
                    }
                )

            try:
                job.dest.parent.mkdir(parents=True, exist_ok=True)
                _run_ffmpeg_with_progress(
                    argv,
                    duration_seconds=job.duration_seconds,
                    on_progress=_file_frac,
                    cancel_event=cancel_event,
                    proc_holder=proc_holder,
                    runner=runner,
                    popen=popen,
                )
                os.replace(tmp, job.dest)
                result.encoded += 1
                row["status"] = "done"
                row["percent"] = 100
            except TranscodeCancelled:
                row["status"] = "cancelled"
                try:
                    tmp.unlink()
                except OSError:
                    pass
                raise
            except Exception as exc:  # noqa: BLE001
                result.failed += 1
                failed_this = True
                result.errors.append(f"{src}: {exc}")
                row["status"] = "failed"
                row["reason"] = str(exc)[:200]
                log.error("transcode failed for %s: %s", src, exc)
                try:
                    tmp.unlink()
                except OSError:
                    pass
            done += 1
            row_i += 1
        if dry_run or failed_this:
            continue
        if not keep_original:
            for old in plan.replace:
                if old.exists() and old.resolve() not in {job.dest.resolve() for job in plan.jobs}:
                    try:
                        old.unlink()
                        result.removed += 1
                        log.info("removed original %s", old)
                    except OSError as exc:
                        log.warning("could not remove %s: %s", old, exc)
    emit(
        {
            "phase": "done",
            "encoder": encoder,
            "hw": hw_name,
            "library_total": len(file_rows),
            "library_done": done,
            "library_percent": 100,
            "file_percent": 100,
            "files": file_rows,
            "encoded": result.encoded,
            "skipped": result.skipped,
            "failed": result.failed,
            "removed": result.removed,
            "message": "Finished",
        }
    )
    return result


def empty_transcode_status() -> dict[str, Any]:
    return {
        "running": False,
        "phase": "idle",
        "message": "",
        "library_total": 0,
        "library_done": 0,
        "library_percent": 0,
        "file_percent": 0,
        "current_src": "",
        "current_dest": "",
        "encoder": "",
        "hw": "",
        "files": [],
        "encoded": 0,
        "skipped": 0,
        "failed": 0,
        "removed": 0,
        "error": None,
        "cancelled": False,
    }


class TranscodeManager:
    """Background in-place transcode with a snapshot the GUI can poll."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._thread: threading.Thread | None = None
        self._proc_holder: list[Any] = []
        self._status = empty_transcode_status()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self._status)

    def _merge(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self._status.update(payload)
            self._status["running"] = True

    def start(
        self,
        roots: Iterable[Path],
        *,
        rungs: list[str] | None = None,
        codec: str = "h264",
        hw: str = "auto",
        keep_original: bool = False,
        dry_run: bool = False,
        fetch: bool = False,
        ffmpeg: str | None = None,
        runner: RunFn | None = None,
        smoke: bool = True,
        popen: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            if self._status.get("running"):
                raise RuntimeError("a transcode is already running")
            self._cancel.clear()
            self._status = empty_transcode_status()
            self._status["running"] = True
            self._status["phase"] = "preparing"
            self._status["message"] = "Starting"
        thread = threading.Thread(
            target=self._run,
            kwargs={
                "roots": list(roots),
                "rungs": rungs,
                "codec": codec,
                "hw": hw,
                "keep_original": keep_original,
                "dry_run": dry_run,
                "fetch": fetch,
                "ffmpeg": ffmpeg,
                "runner": runner,
                "smoke": smoke,
                "popen": popen,
            },
            daemon=True,
            name="localcable-transcode",
        )
        self._thread = thread
        thread.start()
        return self.snapshot()

    def cancel(self) -> dict[str, Any]:
        self._cancel.set()
        procs = list(self._proc_holder)
        for proc in procs:
            try:
                proc.terminate()
            except Exception:  # noqa: BLE001
                pass
        with self._lock:
            self._status["cancelled"] = True
            self._status["message"] = "Cancelling"
        return self.snapshot()

    def _run(self, **kwargs: Any) -> None:
        try:
            result = transcode_library(
                kwargs.pop("roots"),
                on_progress=self._merge,
                cancel_event=self._cancel,
                proc_holder=self._proc_holder,
                **kwargs,
            )
            with self._lock:
                self._status["running"] = False
                self._status["phase"] = "done"
                self._status["encoded"] = result.encoded
                self._status["skipped"] = result.skipped
                self._status["failed"] = result.failed
                self._status["removed"] = result.removed
                self._status["library_percent"] = 100
                self._status["file_percent"] = 100
                self._status["message"] = "Finished"
                if result.errors:
                    self._status["error"] = "; ".join(result.errors[:4])
        except TranscodeCancelled:
            with self._lock:
                self._status["running"] = False
                self._status["phase"] = "cancelled"
                self._status["cancelled"] = True
                self._status["message"] = "Cancelled"
        except Exception as exc:  # noqa: BLE001
            log.exception("transcode job failed")
            with self._lock:
                self._status["running"] = False
                self._status["phase"] = "error"
                self._status["error"] = str(exc)
                self._status["message"] = str(exc)
