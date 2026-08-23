"""YAML configuration loading for LocalCable."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "localcable"
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_BIND_PORT = 8787
DEFAULT_LOGO_FILENAME = "provider_logo.png"


@dataclass
class ScheduleConfig:
    window_hours_before: float = 6.0
    window_hours_after: float = 18.0
    default_mode: str = "sequential"


@dataclass
class PlaybackConfig:
    player: str = "mpv"
    mpv_args: list[str] = field(default_factory=lambda: ["--fullscreen", "--hwdec=auto"])
    start_from: str = "beginning"
    ipc_socket: str | None = None


@dataclass
class UiConfig:
    theme: str = "xfinity"
    auto_open_browser: bool = True
    bind_host: str = DEFAULT_BIND_HOST
    bind_port: int = DEFAULT_BIND_PORT


@dataclass
class AppConfig:
    media_roots: list[Path] = field(default_factory=list)
    config_dir: Path = field(default_factory=lambda: DEFAULT_CONFIG_DIR)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    playback: PlaybackConfig = field(default_factory=PlaybackConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    logo_filename: str = DEFAULT_LOGO_FILENAME

    @property
    def logo_path(self) -> Path:
        return Path(self.config_dir) / self.logo_filename

    @property
    def socket_path(self) -> Path:
        if self.playback.ipc_socket:
            return Path(self.playback.ipc_socket).expanduser()
        return Path(self.config_dir) / "mpv.sock"

    @property
    def cache_dir(self) -> Path:
        return Path(self.config_dir) / "cache"


def _as_path(value: Any) -> Path:
    return Path(os.path.expanduser(str(value))).expanduser()


def _as_path_list(value: Any) -> list[Path]:
    if value is None:
        return []
    if isinstance(value, (str, Path)):
        return [_as_path(value)]
    return [_as_path(v) for v in value]


def _mode(value: Any, default: str = "sequential") -> str:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"sequential", "random"}:
        return text
    return default


def find_settings_path(explicit: str | Path | None = None) -> Path | None:
    """Resolve a settings.yaml path from CLI, env, or the default config dir."""
    if explicit:
        path = _as_path(explicit)
        if path.is_dir():
            return path / "settings.yaml"
        return path
    env = os.environ.get("LOCALCABLE_CONFIG")
    if env:
        path = _as_path(env)
        if path.is_dir():
            return path / "settings.yaml"
        return path
    default = DEFAULT_CONFIG_DIR / "settings.yaml"
    if default.is_file():
        return default
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    if not isinstance(data, dict):
        raise ValueError(f"settings file must be a mapping: {path}")
    return data


def load_config(
    explicit: str | Path | None = None,
    *,
    args: Any | None = None,
) -> AppConfig:
    """Load settings.yaml and apply CLI / env overrides."""
    settings_path = find_settings_path(explicit)
    raw: dict[str, Any] = {}
    config_dir = DEFAULT_CONFIG_DIR
    if settings_path is not None and settings_path.is_file():
        raw = _load_yaml(settings_path)
        config_dir = settings_path.parent

    if raw.get("config_dir"):
        config_dir = _as_path(raw["config_dir"])

    media_roots = _as_path_list(raw.get("media_roots"))
    env_root = os.environ.get("LOCALCABLE_MEDIA_ROOT")
    if env_root:
        media_roots = _as_path_list(env_root)

    sched_raw = raw.get("schedule") or {}
    play_raw = raw.get("playback") or {}
    ui_raw = raw.get("ui") or {}

    schedule = ScheduleConfig(
        window_hours_before=float(sched_raw.get("window_hours_before", 6)),
        window_hours_after=float(sched_raw.get("window_hours_after", 18)),
        default_mode=_mode(sched_raw.get("default_mode"), "sequential"),
    )
    mpv_args = play_raw.get("mpv_args", ["--fullscreen", "--hwdec=auto"])
    if isinstance(mpv_args, str):
        mpv_args = [mpv_args]
    playback = PlaybackConfig(
        player=str(play_raw.get("player", "mpv")),
        mpv_args=list(mpv_args),
        start_from=str(play_raw.get("start_from", "beginning")),
        ipc_socket=play_raw.get("ipc_socket"),
    )
    ui = UiConfig(
        theme=str(ui_raw.get("theme", "xfinity")),
        auto_open_browser=bool(ui_raw.get("auto_open_browser", True)),
        bind_host=str(ui_raw.get("bind_host", DEFAULT_BIND_HOST)),
        bind_port=int(ui_raw.get("bind_port", DEFAULT_BIND_PORT)),
    )
    logo_filename = str(raw.get("logo", DEFAULT_LOGO_FILENAME))

    config = AppConfig(
        media_roots=media_roots,
        config_dir=config_dir,
        schedule=schedule,
        playback=playback,
        ui=ui,
        logo_filename=logo_filename,
    )
    return apply_cli_overrides(config, args)


def apply_cli_overrides(config: AppConfig, args: Any | None) -> AppConfig:
    if args is None:
        return config
    roots = getattr(args, "media_root", None)
    if roots:
        config.media_roots = [_as_path(r) for r in roots]
    if getattr(args, "bind", None):
        config.ui.bind_host = str(args.bind)
    if getattr(args, "port", None) is not None:
        config.ui.bind_port = int(args.port)
    if getattr(args, "mode", None):
        config.schedule.default_mode = _mode(args.mode, config.schedule.default_mode)
    if getattr(args, "headless", False):
        config.ui.auto_open_browser = False
    if getattr(args, "headed", False):
        config.ui.auto_open_browser = True
    if getattr(args, "no_browser", False):
        config.ui.auto_open_browser = False
    return config
