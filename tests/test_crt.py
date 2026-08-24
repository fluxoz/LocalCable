"""CRT/VHS mpv filter: ntsc-rs frei0r when present, else lavfi analog chain."""

from __future__ import annotations

from pathlib import Path

from localcable.config import load_config
from localcable.crt import lavfi_graph, mpv_filter_args, normalize_filter, preset_path
from localcable.player import build_mpv_argv


def test_normalize_filter_aliases():
    assert normalize_filter("off") == "off"
    assert normalize_filter("CRT") == "ntsc"
    assert normalize_filter("VHS") == "vhs"
    assert normalize_filter("true") == "vhs"
    assert normalize_filter("nope", default="off") == "off"


def test_lavfi_fallback_without_frei0r(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FREI0R_PATH", str(tmp_path / "empty"))
    ntsc = lavfi_graph(
        "ntsc",
        environ={"FREI0R_PATH": str(tmp_path / "empty")},
        include_system=False,
    )
    vhs = lavfi_graph(
        "vhs",
        environ={"FREI0R_PATH": str(tmp_path / "empty")},
        include_system=False,
    )
    assert "frei0r" not in ntsc
    assert "scale=-2:480" in ntsc
    assert "noise=" in vhs
    assert "drawgrid=" in vhs


def test_lavfi_uses_ntscrs_when_plugin_exists(tmp_path: Path):
    plugin_dir = tmp_path / "frei0r"
    plugin_dir.mkdir()
    (plugin_dir / "ntscrs.so").write_bytes(b"x")
    graph = lavfi_graph(
        "vhs",
        environ={"FREI0R_PATH": str(plugin_dir)},
        include_system=False,
    )
    assert "frei0r=ntscrs:" in graph
    assert str(preset_path("vhs")) in graph
    assert preset_path("vhs").is_file()
    assert preset_path("ntsc").is_file()


def test_build_argv_off_has_no_filter(tmp_path: Path):
    media = tmp_path / "a.mp4"
    media.write_bytes(b"x")
    argv = build_mpv_argv(str(media), tmp_path / "mpv.sock", extra_args=["--hwdec=auto"])
    assert not any(a.startswith("--vf-add=") for a in argv)
    assert argv.count("--hwdec=no") == 0


def test_build_argv_vhs_disables_hwdec(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FREI0R_PATH", str(tmp_path / "none"))
    media = tmp_path / "a.mp4"
    media.write_bytes(b"x")
    argv = build_mpv_argv(
        str(media),
        tmp_path / "mpv.sock",
        extra_args=["--fullscreen", "--hwdec=auto"],
        filter_mode="vhs",
    )
    assert "--hwdec=auto" in argv
    assert "--hwdec=no" in argv
    assert argv.index("--hwdec=no") > argv.index("--hwdec=auto")
    vf = [a for a in argv if a.startswith("--vf-add=lavfi=")]
    assert vf
    assert "scale=-2:480" in vf[0]


def test_load_filter_from_yaml(tmp_path: Path):
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        "\n".join(
            [
                f"media_roots:",
                f"  - {tmp_path / 'media'}",
                "playback:",
                "  filter: ntsc",
                "",
            ]
        ),
        encoding="utf-8",
    )
    config = load_config(settings)
    assert config.playback.filter == "ntsc"
