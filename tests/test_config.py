from __future__ import annotations

from pathlib import Path

from localcable.config import (
    DEFAULT_MPV_ARGS,
    PlaybackConfig,
    banner_text,
    load_config,
    normalize_inpage_filter,
    normalize_player,
    normalize_start_from,
)
from localcable.themes import PRESET_NAMES, normalize_theme


def test_load_yaml_settings(tmp_path: Path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        "\n".join(
            [
                f"media_roots:",
                f"  - {tmp_path / 'media'}",
                "schedule:",
                "  window_hours_before: 1",
                "  window_hours_after: 2",
                "  default_mode: random",
                "ui:",
                "  bind_host: 127.0.0.1",
                "  bind_port: 9191",
                "  auto_open_browser: false",
                "  banner: Coyote Cable",
                "logo: mylogo.png",
                "",
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(settings)
    assert config.media_roots == [tmp_path / "media"]
    assert config.schedule.default_mode == "random"
    assert config.schedule.window_hours_before == 1
    assert config.ui.bind_port == 9191
    assert config.ui.auto_open_browser is False
    assert config.ui.banner == "Coyote Cable"
    assert config.logo_filename == "mylogo.png"
    assert config.config_dir == tmp_path
    assert config.logo_path == tmp_path / "mylogo.png"
    assert config.public_base_url == "http://127.0.0.1:9191"
    assert config.remote.device is None
    assert config.remote.digit_timeout_ms == 1400
    assert config.artwork.fetch is True
    assert "--profile=fast" in config.playback.mpv_args
    assert config.playback.mpv_args == list(DEFAULT_MPV_ARGS)
    assert config.library.transcode.codec == "h264"
    assert config.library.transcode.hw == "auto"


def test_libraries_and_browser_player_from_yaml(tmp_path: Path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        "\n".join(
            [
                "libraries:",
                f"  - path: {tmp_path / 'Shows'}",
                "    kind: tv",
                f"  - path: {tmp_path / 'Movies'}",
                "    kind: movies",
                "library:",
                "  auto_organize: true",
                "  min_channels: 24",
                f"  inbox: {tmp_path / 'inbox'}",
                "playback:",
                "  player: browser",
                "",
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(settings)
    assert [lib.kind for lib in config.libraries] == ["tv", "movies"]
    assert config.library.auto_organize is True
    assert config.library.min_channels == 24
    assert config.library.inbox == tmp_path / "inbox"
    assert config.playback.player == "browser"
    assert config.media_roots == [tmp_path / "Shows", tmp_path / "Movies"]


def test_lineup_names_from_yaml(tmp_path: Path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        "\n".join(
            [
                f"media_roots:",
                f"  - {tmp_path / 'media'}",
                "lineup:",
                "  Chuckle: Comedy Central",
                "  Thunderbolt: TNT",
                "  fallback: WXYZ 8",
                "playback:",
                "  start_from: live",
                "",
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(settings)
    assert config.lineup.names["Chuckle"] == "Comedy Central"
    assert config.lineup.names["Thunderbolt"] == "TNT"
    assert config.lineup.fallback == "WXYZ 8"
    assert config.playback.start_from == "live"


def test_default_mpv_args_include_fast_profile():
    assert "--profile=fast" in DEFAULT_MPV_ARGS
    assert "--fullscreen" in DEFAULT_MPV_ARGS
    assert "--hwdec=auto" in DEFAULT_MPV_ARGS
    assert PlaybackConfig().mpv_args == list(DEFAULT_MPV_ARGS)


def test_example_settings_keep_crt_under_playback():
    settings = Path(__file__).resolve().parents[1] / "example" / "settings.yaml"
    text = settings.read_text(encoding="utf-8")
    playback = text.split("playback:", 1)[1].split("\nlineup:", 1)[0]
    lineup = text.split("\nlineup:", 1)[1].split("\nui:", 1)[0]
    assert "inpage_filter:" in playback
    assert "filter:" in playback
    assert "inpage_filter:" not in lineup
    config = load_config(settings)
    assert config.playback.inpage_filter == "css"
    assert config.playback.filter == "off"
    assert "--profile=fast" in config.playback.mpv_args


def test_normalize_inpage_filter():
    assert normalize_inpage_filter("css") == "css"
    assert normalize_inpage_filter("fast") == "css"
    assert normalize_inpage_filter("ntscrs") == "ntscrs"
    assert normalize_inpage_filter("off") == "off"


def test_normalize_start_from():
    assert normalize_start_from("now") == "live"
    assert normalize_start_from("beginning") == "beginning"
    assert normalize_start_from(None) == "live"


def test_normalize_player_aliases():
    assert normalize_player("dash") == "browser"
    assert normalize_player("mpv") == "mpv"
    assert normalize_player("both") == "both"
    assert normalize_player(None) == "browser"


def test_theme_and_color_overrides_from_yaml(tmp_path: Path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        "\n".join(
            [
                f"media_roots:",
                f"  - {tmp_path / 'media'}",
                "ui:",
                "  theme: miami-vice",
                "  colors:",
                "    selected: '#ff00aa'",
                "    header_bg: '#0bd3d3'",
                "",
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(settings)
    assert config.ui.theme == "miami-vice"
    assert config.ui.colors["selected"] == "#ff00aa"
    theme = config.ui.resolved_theme()
    assert theme["theme"] == "miami-vice"
    assert theme["colors"]["selected"] == "#ff00aa"
    assert theme["colors"]["header_bg"] == "#0bd3d3"
    assert theme["colors"]["page_bg"] == "#000000"
    assert set(PRESET_NAMES) <= set(theme["presets"])


def test_xfinity_theme_alias_is_default():
    assert normalize_theme("xfinity") == "default"
    assert normalize_theme("Retro Green") == "retro-green"
    assert normalize_theme("directv") == "dark-blue"


def test_banner_text_strips_and_falls_back():
    assert banner_text("  guide  ") == "guide"
    assert banner_text("") == "TV Listings"
    assert banner_text(None) == "TV Listings"
    assert len(banner_text("x" * 200)) == 80
