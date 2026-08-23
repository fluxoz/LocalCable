from __future__ import annotations

from pathlib import Path

from localcable.config import load_config


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
    assert config.logo_filename == "mylogo.png"
    assert config.config_dir == tmp_path
    assert config.logo_path == tmp_path / "mylogo.png"
