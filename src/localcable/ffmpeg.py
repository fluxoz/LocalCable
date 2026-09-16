"""Resolve a portable ffmpeg/ffprobe binary and pick a GPU encoder when present."""

from __future__ import annotations

import logging
import os
import platform
import shutil
import stat
import subprocess
import tarfile
import zipfile
from pathlib import Path
from typing import Any, Callable
from urllib.request import urlopen

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
VENDOR_FFMPEG = PACKAGE_DIR / "vendor" / "ffmpeg"

RunFn = Callable[..., Any]
WhichFn = Callable[[str], str | None]
OpenUrlFn = Callable[..., Any]

# GPU first, then CPU. Names must match `ffmpeg -encoders`.
H264_ENCODERS: tuple[tuple[str, str], ...] = (
    ("nvenc", "h264_nvenc"),
    ("qsv", "h264_qsv"),
    ("amf", "h264_amf"),
    ("videotoolbox", "h264_videotoolbox"),
    ("vaapi", "h264_vaapi"),
    ("cpu", "libx264"),
)
HEVC_ENCODERS: tuple[tuple[str, str], ...] = (
    ("nvenc", "hevc_nvenc"),
    ("qsv", "hevc_qsv"),
    ("amf", "hevc_amf"),
    ("videotoolbox", "hevc_videotoolbox"),
    ("vaapi", "hevc_vaapi"),
    ("cpu", "libx265"),
)

HW_ALIASES = {
    "auto": "auto",
    "gpu": "auto",
    "cpu": "cpu",
    "software": "cpu",
    "libx264": "cpu",
    "libx265": "cpu",
    "off": "cpu",
    "nvenc": "nvenc",
    "cuda": "nvenc",
    "nvidia": "nvenc",
    "qsv": "qsv",
    "intel": "qsv",
    "amf": "amf",
    "amd": "amf",
    "vaapi": "vaapi",
    "videotoolbox": "videotoolbox",
    "vt": "videotoolbox",
    "metal": "videotoolbox",
}


def platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux":
        if machine in {"aarch64", "arm64"}:
            return "linux-arm64"
        return "linux-x86_64"
    if system == "darwin":
        if machine in {"arm64", "aarch64"}:
            return "macos-arm64"
        return "macos-x86_64"
    if system == "windows":
        return "windows-x86_64"
    return f"{system}-{machine or 'unknown'}"


def vendor_dir(tag: str | None = None) -> Path:
    return VENDOR_FFMPEG / (tag or platform_tag())


def _exe_name(probe: bool = False) -> str:
    base = "ffprobe" if probe else "ffmpeg"
    if platform.system().lower() == "windows":
        return f"{base}.exe"
    return base


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def ffmpeg_release_url(tag: str | None = None) -> tuple[str, str]:
    """Return (url, archive_kind) for a static GPL ffmpeg build."""
    key = tag or platform_tag()
    latest = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest"
    table = {
        "linux-x86_64": (f"{latest}/ffmpeg-master-latest-linux64-gpl.tar.xz", "tar.xz"),
        "linux-arm64": (f"{latest}/ffmpeg-master-latest-linuxarm64-gpl.tar.xz", "tar.xz"),
        "windows-x86_64": (f"{latest}/ffmpeg-master-latest-win64-gpl.zip", "zip"),
        "macos-arm64": ("https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip", "zip"),
        "macos-x86_64": ("https://evermeet.cx/ffmpeg/getrelease/ffmpeg/zip", "zip"),
    }
    if key not in table:
        raise RuntimeError(f"no vendored ffmpeg build published for {key}")
    return table[key]


def ffprobe_release_url(tag: str | None = None) -> tuple[str, str] | None:
    key = tag or platform_tag()
    if key.startswith("macos"):
        return ("https://evermeet.cx/ffmpeg/getrelease/ffprobe/zip", "zip")
    return None


def normalize_hw(value: Any, default: str = "auto") -> str:
    if value is None:
        return default
    text = str(value).strip().lower().replace("-", "_")
    return HW_ALIASES.get(text, default)


def list_encoders(ffmpeg: str, *, runner: RunFn | None = None) -> set[str]:
    run = runner or subprocess.run
    try:
        proc = run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
    except TypeError:
        proc = run([ffmpeg, "-hide_banner", "-encoders"], capture_output=True, text=True, check=False)
    except Exception as exc:  # noqa: BLE001
        log.debug("ffmpeg -encoders failed: %s", exc)
        return set()
    blob = (getattr(proc, "stdout", "") or "") + "\n" + (getattr(proc, "stderr", "") or "")
    found: set[str] = set()
    for raw in blob.splitlines():
        line = raw.strip()
        if not line or line.startswith("-") or line.startswith("Encoders") or line.startswith("V...."):
            continue
        parts = line.split()
        if len(parts) >= 2:
            found.add(parts[1])
        elif len(parts) == 1:
            found.add(parts[0])
    return found


def smoke_encoder(
    ffmpeg: str,
    encoder: str,
    extra: list[str] | None = None,
    *,
    runner: RunFn | None = None,
) -> bool:
    """Tiny lavfi encode; True when the encoder actually works on this machine."""
    run = runner or subprocess.run
    argv = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=64x64:d=0.2:r=10",
    ]
    if extra:
        argv += list(extra)
    argv += ["-c:v", encoder, "-frames:v", "2", "-f", "null", "-"]
    try:
        proc = run(argv, capture_output=True, text=True, check=False, timeout=30)
    except TypeError:
        proc = run(argv, capture_output=True, text=True, check=False)
    except Exception:
        return False
    return getattr(proc, "returncode", 1) == 0


def pick_encoder(
    ffmpeg: str,
    *,
    codec: str = "h264",
    hw: str = "auto",
    runner: RunFn | None = None,
    smoke: bool = True,
) -> tuple[str, str]:
    """Return (hw_name, ffmpeg_encoder). Falls back to CPU."""
    codec = "hevc" if str(codec).lower() in {"hevc", "h265", "h.265", "x265"} else "h264"
    wanted = normalize_hw(hw)
    table = HEVC_ENCODERS if codec == "hevc" else H264_ENCODERS
    available = list_encoders(ffmpeg, runner=runner)
    ordered = list(table)
    if wanted != "auto":
        preferred = [row for row in ordered if row[0] == wanted]
        rest = [row for row in ordered if row[0] != wanted]
        ordered = preferred + rest
    for name, encoder in ordered:
        if available and encoder not in available and name != "cpu":
            continue
        extra: list[str] = []
        if name == "vaapi" and Path("/dev/dri/renderD128").exists():
            extra = ["-vaapi_device", "/dev/dri/renderD128"]
        if smoke and name != "cpu":
            if not smoke_encoder(ffmpeg, encoder, extra, runner=runner):
                log.info("ffmpeg encoder %s listed but smoke test failed; skipping", encoder)
                continue
        elif smoke and name == "cpu":
            if available and encoder not in available:
                continue
        log.info("using %s encoder %s", name, encoder)
        return name, encoder
    fallback = "libx265" if codec == "hevc" else "libx264"
    return "cpu", fallback


def encoder_args(hw_name: str, encoder: str, *, crf: int = 20, maxrate: str | None = None) -> list[str]:
    """Output-side video flags (no -i)."""
    args = ["-c:v", encoder]
    if encoder in {"libx264", "libx265"}:
        args += ["-preset", "medium", "-crf", str(crf), "-pix_fmt", "yuv420p"]
        if encoder == "libx264":
            args += ["-profile:v", "high"]
        if maxrate:
            args += ["-maxrate", maxrate, "-bufsize", _double_rate(maxrate)]
        return args
    if "nvenc" in encoder:
        args += ["-preset", "p5", "-rc", "vbr", "-cq", str(crf), "-b:v", "0", "-pix_fmt", "yuv420p"]
        if "h264" in encoder:
            args += ["-profile:v", "high"]
        if maxrate:
            args += ["-maxrate", maxrate, "-bufsize", _double_rate(maxrate)]
        return args
    if "qsv" in encoder:
        args += ["-global_quality", str(crf), "-look_ahead", "1", "-pix_fmt", "nv12"]
        if maxrate:
            args += ["-maxrate", maxrate]
        return args
    if "amf" in encoder:
        args += ["-quality", "quality", "-rc", "cqp", "-qp_i", str(crf), "-qp_p", str(crf)]
        return args
    if "videotoolbox" in encoder:
        q = max(20, min(70, 70 - crf))
        args += ["-q:v", str(q), "-pix_fmt", "yuv420p"]
        if "h264" in encoder:
            args += ["-profile:v", "high"]
        return args
    if "vaapi" in encoder:
        args += ["-qp", str(crf)]
        return args
    args += ["-pix_fmt", "yuv420p"]
    return args


def scale_filter(hw_name: str, height: int | None) -> str | None:
    if not height:
        return None
    if hw_name == "vaapi":
        return f"format=nv12,hwupload,scale_vaapi=-2:{int(height)}"
    return f"scale=-2:{int(height)}:flags=lanczos"


def _double_rate(rate: str) -> str:
    text = str(rate).strip().lower()
    try:
        if text.endswith("m"):
            return f"{float(text[:-1]) * 2:.0f}M"
        if text.endswith("k"):
            return f"{float(text[:-1]) * 2:.0f}k"
        return str(int(float(text) * 2))
    except ValueError:
        return rate


def resolve_ffmpeg(
    *,
    explicit: str | Path | None = None,
    which: WhichFn | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    """LOCALCABLE_FFMPEG → vendored binary → PATH."""
    env = environ if environ is not None else os.environ
    if explicit:
        path = Path(os.path.expanduser(str(explicit)))
        if path.is_file():
            return str(path)
        raise FileNotFoundError(f"ffmpeg not found: {path}")
    env_path = env.get("LOCALCABLE_FFMPEG")
    if env_path:
        path = Path(os.path.expanduser(env_path))
        if path.is_file():
            return str(path)
    vendored = vendor_dir() / _exe_name(False)
    if _is_executable(vendored) or vendored.is_file():
        return str(vendored)
    finder = which or shutil.which
    found = finder("ffmpeg")
    if found:
        return found
    raise FileNotFoundError(
        "ffmpeg not found. Run `localcable transcode --fetch-ffmpeg` or set LOCALCABLE_FFMPEG."
    )


def resolve_ffprobe(
    *,
    ffmpeg: str | None = None,
    which: WhichFn | None = None,
    environ: dict[str, str] | None = None,
) -> str:
    env = environ if environ is not None else os.environ
    env_path = env.get("LOCALCABLE_FFPROBE")
    if env_path:
        path = Path(os.path.expanduser(env_path))
        if path.is_file():
            return str(path)
    if ffmpeg:
        sibling = Path(ffmpeg).with_name(_exe_name(True))
        if sibling.is_file():
            return str(sibling)
    vendored = vendor_dir() / _exe_name(True)
    if vendored.is_file():
        return str(vendored)
    finder = which or shutil.which
    found = finder("ffprobe")
    if found:
        return found
    if ffmpeg:
        return ffmpeg
    raise FileNotFoundError("ffprobe not found")


def _extract_member(archive: Path, kind: str, dest: Path, names: tuple[str, ...]) -> Path | None:
    dest.mkdir(parents=True, exist_ok=True)
    if kind == "zip":
        with zipfile.ZipFile(archive) as zf:
            for info in zf.infolist():
                base = Path(info.filename).name.lower()
                if base in names and not info.is_dir():
                    target = dest / Path(info.filename).name
                    target.write_bytes(zf.read(info))
                    return target
    else:
        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                if not member.isfile():
                    continue
                base = Path(member.name).name.lower()
                if base in names:
                    extracted = tf.extractfile(member)
                    if extracted is None:
                        continue
                    target = dest / Path(member.name).name
                    target.write_bytes(extracted.read())
                    return target
    return None


def _chmod_exec(path: Path) -> None:
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def fetch_ffmpeg(
    *,
    dest_dir: Path | None = None,
    opener: OpenUrlFn | None = None,
    tag: str | None = None,
) -> Path:
    """Download a static ffmpeg into the vendor dir. Returns the ffmpeg path."""
    tag = tag or platform_tag()
    dest = dest_dir or vendor_dir(tag)
    dest.mkdir(parents=True, exist_ok=True)
    url, kind = ffmpeg_release_url(tag)
    open_url = opener or urlopen
    archive = dest / f"ffmpeg-download.{kind.replace('.', '')}"
    log.info("downloading ffmpeg for %s", tag)
    with open_url(url, timeout=120) as resp:
        data = resp.read()
    archive.write_bytes(data)
    names = ("ffmpeg.exe", "ffmpeg")
    binary = _extract_member(archive, kind, dest, names)
    if binary is None:
        # evermeet zip is a single `ffmpeg` file at the archive root
        if kind == "zip":
            with zipfile.ZipFile(archive) as zf:
                members = [n for n in zf.namelist() if not n.endswith("/")]
                if len(members) == 1:
                    binary = dest / _exe_name(False)
                    binary.write_bytes(zf.read(members[0]))
    if binary is None:
        raise RuntimeError(f"ffmpeg binary missing from archive {url}")
    final = dest / _exe_name(False)
    if binary != final:
        final.write_bytes(binary.read_bytes())
        if binary.name != final.name:
            try:
                binary.unlink()
            except OSError:
                pass
    _chmod_exec(final)
    probe_url = ffprobe_release_url(tag)
    if probe_url:
        p_url, p_kind = probe_url
        p_archive = dest / f"ffprobe-download.{p_kind.replace('.', '')}"
        with open_url(p_url, timeout=120) as resp:
            p_archive.write_bytes(resp.read())
        probe = _extract_member(p_archive, p_kind, dest, ("ffprobe.exe", "ffprobe"))
        if probe is None and p_kind == "zip":
            with zipfile.ZipFile(p_archive) as zf:
                members = [n for n in zf.namelist() if not n.endswith("/")]
                if len(members) == 1:
                    probe = dest / _exe_name(True)
                    probe.write_bytes(zf.read(members[0]))
        if probe is not None:
            probe_final = dest / _exe_name(True)
            if probe != probe_final:
                probe_final.write_bytes(probe.read_bytes())
            _chmod_exec(probe_final)
            try:
                p_archive.unlink()
            except OSError:
                pass
    try:
        archive.unlink()
    except OSError:
        pass
    return final
