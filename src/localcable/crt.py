"""CRT / VHS look for mpv: vendored ntsc-rs (frei0r), else a 480p analog chain.

https://ntsc.rs/  — authentic NTSC/VHS via the ntscrs frei0r plugin + JSON presets.
The plugin is shipped under vendor/ntscrs/. If this CPU/OS has no binary, LocalCable
still applies a scanline / chroma-noise approximation so the option works.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PRESETS_DIR = PACKAGE_DIR / "presets"
VENDOR_FREI0R = PACKAGE_DIR / "vendor" / "ntscrs" / "frei0r"

LAVFI_NTSC = (
    "scale=-2:480:flags=lanczos,"
    "format=yuv422p,"
    "eq=contrast=1.04:saturation=0.88:gamma=1.06,"
    "noise=c0s=5:c0f=t:c1s=8:c1f=t:c2s=8:c2f=t,"
    "hue=h=1.2"
)

LAVFI_VHS = (
    "scale=-2:480:flags=lanczos,"
    "format=yuv422p,"
    "avgblur=1:0:1:0,"
    "eq=contrast=1.08:brightness=0.02:saturation=0.72:gamma=1.12,"
    "noise=c0s=10:c0f=t+u:c1s=14:c1f=t:c2s=14:c2f=t,"
    "drawgrid=w=iw:h=2:t=1:c=black@0.18"
)

FREI0R_NAMES = (
    "ntscrs.so",
    "libntscrs.so",
    "ntscrs.dylib",
    "libntscrs.dylib",
    "ntscrs.dll",
)


def normalize_filter(value: object, default: str = "off") -> str:
    text = str(value if value is not None else default).strip().lower()
    if text in {"ntsc", "crt", "tv", "analog", "broadcast"}:
        return "ntsc"
    if text in {"vhs", "tape", "on", "true", "1", "yes"}:
        return "vhs"
    if text in {"off", "none", "false", "0", "no", ""}:
        return "off"
    return default if default in {"off", "ntsc", "vhs"} else "off"


def _vendor_plugin_dirs() -> list[Path]:
    """Shipped ntscrs binaries for this OS/CPU, then any other vendored copies."""
    system = sys.platform
    machine = os.uname().machine.lower() if hasattr(os, "uname") else ""
    preferred: list[Path] = []
    if system.startswith("linux"):
        if machine in {"x86_64", "amd64"}:
            preferred.append(VENDOR_FREI0R / "linux-x86_64")
        elif machine in {"aarch64", "arm64"}:
            preferred.append(VENDOR_FREI0R / "linux-aarch64")
    elif system == "darwin":
        if machine in {"arm64", "aarch64"}:
            preferred.append(VENDOR_FREI0R / "macos-arm64")
        preferred.append(VENDOR_FREI0R / "macos-x86_64")
        preferred.append(VENDOR_FREI0R / "macos-arm64")
    elif system.startswith("win"):
        preferred.append(VENDOR_FREI0R / "windows-x86_64")
    extra = []
    if VENDOR_FREI0R.is_dir():
        extra = [p for p in sorted(VENDOR_FREI0R.iterdir()) if p.is_dir() and p not in preferred]
    return preferred + extra


def find_frei0r_ntscrs(
    environ: dict[str, str] | None = None,
    *,
    include_system: bool = True,
    include_vendor: bool = True,
) -> Path | None:
    env = environ if environ is not None else os.environ
    dirs: list[Path] = []
    raw = env.get("FREI0R_PATH") or ""
    for part in raw.split(":"):
        if part.strip():
            dirs.append(Path(part.strip()))
    if include_vendor:
        dirs.extend(_vendor_plugin_dirs())
    if include_system:
        dirs.extend(
            [
                Path.home() / ".frei0r-1" / "lib",
                Path("/usr/lib/frei0r-1"),
                Path("/usr/lib64/frei0r-1"),
                Path("/usr/local/lib/frei0r-1"),
                Path("/usr/lib/x86_64-linux-gnu/frei0r-1"),
                Path("/usr/lib/aarch64-linux-gnu/frei0r-1"),
            ]
        )
    seen: set[Path] = set()
    for folder in dirs:
        try:
            resolved = folder.resolve()
        except OSError:
            resolved = folder
        if resolved in seen:
            continue
        seen.add(resolved)
        if not folder.is_dir():
            continue
        for name in FREI0R_NAMES:
            candidate = folder / name
            if candidate.is_file():
                return candidate
    return None


def preset_path(mode: str, explicit: str | Path | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser()
    name = "vhs.json" if mode == "vhs" else "ntsc.json"
    return PRESETS_DIR / name


def lavfi_graph(
    mode: str,
    *,
    explicit_preset: str | Path | None = None,
    environ: dict[str, str] | None = None,
    include_system: bool = True,
) -> str:
    """libavfilter graph: real ntsc-rs via frei0r, else a built-in analog chain."""
    if mode not in {"ntsc", "vhs"}:
        return ""
    plugin = find_frei0r_ntscrs(
        environ,
        include_system=include_system,
        include_vendor=include_system,
    )
    preset = preset_path(mode, explicit_preset)
    if plugin is not None and preset.is_file():
        return f"scale=-2:480:flags=lanczos,frei0r=ntscrs:{preset}"
    return LAVFI_VHS if mode == "vhs" else LAVFI_NTSC


def mpv_filter_args(
    mode: str,
    *,
    explicit_preset: str | Path | None = None,
    environ: dict[str, str] | None = None,
    include_system: bool = True,
) -> list[str]:
    """Extra mpv argv. Later flags win over user ``--hwdec=auto``."""
    graph = lavfi_graph(
        mode,
        explicit_preset=explicit_preset,
        environ=environ,
        include_system=include_system,
    )
    if not graph:
        return []
    return [
        "--hwdec=no",
        f"--vf-add=lavfi=[{graph}]",
    ]
