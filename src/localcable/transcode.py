"""One-time in-place transcode to browser-native H.264 + AAC MP4."""

from __future__ import annotations

import logging
import os
import re
import subprocess
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
from localcable.metadata import codecs_from_probe, mse_copy_ok, run_ffprobe

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


@dataclass
class TranscodeJob:
    src: Path
    dest: Path
    height: int | None
    label: str
    skip: bool = False
    reason: str = ""


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
        jobs.append(TranscodeJob(src=src, dest=dest, height=height, label=label, skip=skip, reason=reason))
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
) -> TranscodeResult:
    from localcable.ffmpeg import fetch_ffmpeg

    rung_list = parse_rungs(rungs)
    codec = normalize_codec(codec)
    hw = normalize_hw(hw)
    result = TranscodeResult()
    if fetch:
        fetch_ffmpeg()
    binary = ffmpeg or resolve_ffmpeg(which=which)
    probe_bin = resolve_ffprobe(ffmpeg=binary, which=which)
    hw_name, encoder = pick_encoder(binary, codec=codec, hw=hw, runner=runner, smoke=smoke)
    log.info("transcode encoder=%s (%s) rungs=%s", encoder, hw_name, ",".join(rung_list))

    files: list[Path] = []
    for root in roots:
        files.extend(iter_videos(Path(root)))
    # Do not re-encode our own rung outputs as new sources when a sibling source exists.
    grouped = collapse_rendition_files(files)
    sources: list[Path] = []
    for primary, renditions in grouped:
        members = [primary] + [r.path for r in renditions]
        originals = [p for p in members if variant_height(p) is None]
        src = originals[0] if originals else primary
        sources.append(src)

    seen: set[Path] = set()
    for src in sources:
        resolved = src.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        plan = plan_file(
            src,
            rung_list,
            codec=codec,
            keep_original=keep_original,
            ffprobe=probe_bin,
            runner=runner,
        )
        data = run_ffprobe(src, runner=runner, binary=probe_bin)
        video, audio = codecs_from_probe(data)
        copy_audio = bool(audio) and all(name in {"aac", "mp4a"} for name in audio)
        failed_this = False
        for job in plan.jobs:
            result.planned += 1
            if job.skip:
                result.skipped += 1
                log.info("skip %s (%s)", job.dest.name, job.reason)
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
            if dry_run:
                result.skipped += 1
                continue
            try:
                job.dest.parent.mkdir(parents=True, exist_ok=True)
                _run_ffmpeg(argv, runner=runner)
                os.replace(tmp, job.dest)
                result.encoded += 1
            except Exception as exc:  # noqa: BLE001
                result.failed += 1
                failed_this = True
                result.errors.append(f"{src}: {exc}")
                log.error("transcode failed for %s: %s", src, exc)
                try:
                    tmp.unlink()
                except OSError:
                    pass
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
    return result
