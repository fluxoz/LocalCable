"""YAML configuration loading for LocalCable."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from localcable.crt import normalize_filter

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "localcable"
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_BIND_PORT = 8787
DEFAULT_LOGO_FILENAME = "provider_logo.png"
DEFAULT_BANNER = "TV Listings"
DEFAULT_PLAYER = "browser"
DEFAULT_START_FROM = "live"
VALID_LIBRARY_KINDS = ("channels", "tv", "movies", "jellyfin", "auto")
VALID_PLAYERS = ("browser", "mpv", "both")


def banner_text(value: Any, default: str = DEFAULT_BANNER) -> str:
    text = str(value if value is not None else default).strip()
    if not text:
        return default
    if len(text) > 80:
        return text[:80].rstrip()
    return text


@dataclass
class ScheduleConfig:
    window_hours_before: float = 6.0
    window_hours_after: float = 18.0
    default_mode: str = "sequential"


@dataclass
class PlaybackConfig:
    player: str = DEFAULT_PLAYER
    mpv_args: list[str] = field(default_factory=lambda: ["--fullscreen", "--hwdec=auto"])
    start_from: str = DEFAULT_START_FROM
    ipc_socket: str | None = None
    filter: str = "off"
    filter_preset: str | None = None


@dataclass
class LibraryRoot:
    path: Path
    kind: str = "channels"


@dataclass
class LineupConfig:
    """Rename or replace the auto genre channels."""

    names: dict[str, str] = field(default_factory=dict)
    channels: list[dict[str, Any]] = field(default_factory=list)
    fallback: str | None = None
    fallback_number: int | None = None


@dataclass
class LibraryConfig:
    """Jellyfin-layout libraries, auto channel lineup, and optional auto-organize."""

    auto_organize: bool = False
    inbox: Path | None = None
    fetch_metadata: bool = True
    auto_channels: bool = True


@dataclass
class UiConfig:
    theme: str = "xfinity"
    auto_open_browser: bool = True
    bind_host: str = DEFAULT_BIND_HOST
    bind_port: int = DEFAULT_BIND_PORT
    banner: str = DEFAULT_BANNER


@dataclass
class RemoteConfig:
    """IR remote. Empty device = keyboard-style remotes (ir-keytable) only."""

    device: str | None = None
    digit_timeout_ms: int = 1400


@dataclass
class ArtworkConfig:
    """Cover art. User sidecars always win; online fetch is keyless and optional."""

    fetch: bool = True


@dataclass
class AppConfig:
    media_roots: list[Path] = field(default_factory=list)
    libraries: list[LibraryRoot] = field(default_factory=list)
    library: LibraryConfig = field(default_factory=LibraryConfig)
    lineup: LineupConfig = field(default_factory=LineupConfig)
    config_dir: Path = field(default_factory=lambda: DEFAULT_CONFIG_DIR)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    playback: PlaybackConfig = field(default_factory=PlaybackConfig)
    ui: UiConfig = field(default_factory=UiConfig)
    remote: RemoteConfig = field(default_factory=RemoteConfig)
    artwork: ArtworkConfig = field(default_factory=ArtworkConfig)
    logo_filename: str = DEFAULT_LOGO_FILENAME

    def library_roots(self) -> list[LibraryRoot]:
        if self.libraries:
            return list(self.libraries)
        return [LibraryRoot(path=path, kind="channels") for path in self.media_roots]

    @property
    def logo_path(self) -> Path:
        return Path(self.config_dir) / self.logo_filename

    @property
    def socket_path(self) -> Path:
        if self.playback.ipc_socket:
            return Path(self.playback.ipc_socket).expanduser()
        return Path(self.config_dir) / "mpv.sock"

    @property
    def public_base_url(self) -> str:
        host = self.ui.bind_host
        shown = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
        return f"http://{shown}:{int(self.ui.bind_port)}"

    @property
    def cache_dir(self) -> Path:
        return Path(self.config_dir) / "cache"

    @property
    def osd_path(self) -> Path:
        return Path(self.config_dir) / "osd.json"


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


def normalize_player(value: Any, default: str = DEFAULT_PLAYER) -> str:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"browser", "dash", "web", "html"}:
        return "browser"
    if text in {"mpv"}:
        return "mpv"
    if text in {"both", "all"}:
        return "both"
    return default


def normalize_start_from(value: Any, default: str = DEFAULT_START_FROM) -> str:
    if value is None:
        return default
    text = str(value).strip().lower().replace("-", "_")
    if text in {"live", "now", "guide", "join"}:
        return "live"
    if text in {"beginning", "start", "zero", "0", "from_start", "fromstart"}:
        return "beginning"
    return default


def normalize_kind(value: Any, default: str = "channels") -> str:
    if value is None:
        return default
    text = str(value).strip().lower()
    if text in {"channel", "channels", "legacy"}:
        return "channels"
    if text in {"tv", "show", "shows", "series"}:
        return "tv"
    if text in {"movie", "movies", "film", "films"}:
        return "movies"
    if text in {"jellyfin", "media"}:
        return "jellyfin"
    if text in {"auto", "lineup", "cable"}:
        return "auto"
    return default


def _parse_libraries(value: Any) -> list[LibraryRoot]:
    if not value:
        return []
    if isinstance(value, (str, Path)):
        return [LibraryRoot(path=_as_path(value), kind="channels")]
    roots: list[LibraryRoot] = []
    for item in value:
        if isinstance(item, (str, Path)):
            roots.append(LibraryRoot(path=_as_path(item), kind="channels"))
            continue
        if not isinstance(item, dict):
            continue
        path = item.get("path") or item.get("root")
        if not path:
            continue
        roots.append(LibraryRoot(path=_as_path(path), kind=normalize_kind(item.get("kind"))))
    return roots


def _parse_lineup(value: Any) -> LineupConfig:
    if not value:
        return LineupConfig()
    if not isinstance(value, dict):
        return LineupConfig()
    reserved = {"names", "channels", "fallback", "fallback_number"}
    names_raw = value.get("names")
    extra_names = {k: v for k, v in value.items() if k not in reserved and isinstance(v, str)}
    names: dict[str, str] = {}
    if isinstance(names_raw, dict):
        names.update({str(k): str(v) for k, v in names_raw.items() if v is not None})
    names.update({str(k): str(v) for k, v in extra_names.items()})
    channels_raw = value.get("channels") or []
    channels: list[dict[str, Any]] = []
    if isinstance(channels_raw, list):
        for row in channels_raw:
            if isinstance(row, dict) and row.get("name"):
                channels.append(row)
    fallback_number = value.get("fallback_number")
    return LineupConfig(
        names=names,
        channels=channels,
        fallback=str(value["fallback"]).strip() if value.get("fallback") else None,
        fallback_number=int(fallback_number) if fallback_number is not None else None,
    )


def _sync_roots(media_roots: list[Path], libraries: list[LibraryRoot]) -> tuple[list[Path], list[LibraryRoot]]:
    if libraries and not media_roots:
        media_roots = [lib.path for lib in libraries]
    elif media_roots and not libraries:
        libraries = [LibraryRoot(path=path, kind="channels") for path in media_roots]
    elif libraries and media_roots:
        known = {str(path) for path in media_roots}
        for lib in libraries:
            if str(lib.path) not in known:
                media_roots.append(lib.path)
                known.add(str(lib.path))
    return media_roots, libraries


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
    libraries = _parse_libraries(raw.get("libraries"))
    media_roots, libraries = _sync_roots(media_roots, libraries)

    sched_raw = raw.get("schedule") or {}
    play_raw = raw.get("playback") or {}
    ui_raw = raw.get("ui") or {}
    remote_raw = raw.get("remote") or {}
    art_raw = raw.get("artwork") or {}
    lib_raw = raw.get("library") or {}
    lineup_raw = raw.get("lineup") or {}

    schedule = ScheduleConfig(
        window_hours_before=float(sched_raw.get("window_hours_before", 6)),
        window_hours_after=float(sched_raw.get("window_hours_after", 18)),
        default_mode=_mode(sched_raw.get("default_mode"), "sequential"),
    )
    mpv_args = play_raw.get("mpv_args", ["--fullscreen", "--hwdec=auto"])
    if isinstance(mpv_args, str):
        mpv_args = [mpv_args]
    preset = play_raw.get("filter_preset")
    playback = PlaybackConfig(
        player=normalize_player(play_raw.get("player", DEFAULT_PLAYER)),
        mpv_args=list(mpv_args),
        start_from=normalize_start_from(play_raw.get("start_from", DEFAULT_START_FROM)),
        ipc_socket=play_raw.get("ipc_socket"),
        filter=normalize_filter(play_raw.get("filter", "off")),
        filter_preset=str(preset) if preset else None,
    )
    ui = UiConfig(
        theme=str(ui_raw.get("theme", "xfinity")),
        auto_open_browser=bool(ui_raw.get("auto_open_browser", True)),
        bind_host=str(ui_raw.get("bind_host", DEFAULT_BIND_HOST)),
        bind_port=int(ui_raw.get("bind_port", DEFAULT_BIND_PORT)),
        banner=banner_text(ui_raw.get("banner", DEFAULT_BANNER)),
    )
    device = remote_raw.get("device")
    remote = RemoteConfig(
        device=str(device) if device else None,
        digit_timeout_ms=int(remote_raw.get("digit_timeout_ms", 1400)),
    )
    artwork = ArtworkConfig(fetch=bool(art_raw.get("fetch", True)))
    inbox = lib_raw.get("inbox") or lib_raw.get("organize_from")
    auto_channels = lib_raw.get("auto_channels")
    if auto_channels is None:
        auto_channels = True
    library = LibraryConfig(
        auto_organize=bool(lib_raw.get("auto_organize", False)),
        inbox=_as_path(inbox) if inbox else None,
        fetch_metadata=bool(lib_raw.get("fetch_metadata", True)),
        auto_channels=bool(auto_channels),
    )
    lineup = _parse_lineup(lineup_raw)
    logo_filename = str(raw.get("logo", DEFAULT_LOGO_FILENAME))

    config = AppConfig(
        media_roots=media_roots,
        libraries=libraries,
        library=library,
        lineup=lineup,
        config_dir=config_dir,
        schedule=schedule,
        playback=playback,
        ui=ui,
        remote=remote,
        artwork=artwork,
        logo_filename=logo_filename,
    )
    return apply_cli_overrides(config, args)


def apply_cli_overrides(config: AppConfig, args: Any | None) -> AppConfig:
    if args is None:
        return config
    roots = getattr(args, "media_root", None)
    if roots:
        config.media_roots = [_as_path(r) for r in roots]
        config.libraries = [LibraryRoot(path=path, kind="channels") for path in config.media_roots]
    for kind, attr in (("tv", "tv_root"), ("movies", "movies_root")):
        extra = getattr(args, attr, None) or []
        for raw_path in extra:
            path = _as_path(raw_path)
            config.libraries.append(LibraryRoot(path=path, kind=kind))
            if path not in config.media_roots:
                config.media_roots.append(path)
    if getattr(args, "organize", False):
        config.library.auto_organize = True
    if getattr(args, "inbox", None):
        config.library.inbox = _as_path(args.inbox)
        config.library.auto_organize = True
    if getattr(args, "player", None):
        config.playback.player = normalize_player(args.player, config.playback.player)
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
