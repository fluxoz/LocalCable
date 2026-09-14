from __future__ import annotations

from localcable.themes import (
    COLOR_KEYS,
    PRESET_NAMES,
    THEMES,
    normalize_theme,
    resolve_theme,
)


def test_six_named_presets():
    assert PRESET_NAMES == (
        "default",
        "dark",
        "modern",
        "retro-green",
        "miami-vice",
        "dark-blue",
    )
    for name in PRESET_NAMES:
        assert name in THEMES
        preset = THEMES[name]
        for key in COLOR_KEYS:
            assert key in preset["colors"], f"{name} missing {key}"
        assert len(preset["palette"]) >= 6


def test_miami_vice_uses_published_palette():
    colors = THEMES["miami-vice"]["colors"]
    assert colors["header_bg"].lower() == "#0bd3d3"
    assert colors["selected"].lower() == "#f890e7"
    assert colors["page_bg"].lower() == "#000000"


def test_color_overrides_win_over_preset():
    resolved = resolve_theme("dark", {"selected": "#ffffff", "now": "#00ff00"})
    assert resolved["theme"] == "dark"
    assert resolved["colors"]["selected"] == "#ffffff"
    assert resolved["colors"]["now"] == "#00ff00"
    assert resolved["colors"]["page_bg"] == THEMES["dark"]["colors"]["page_bg"]


def test_unknown_theme_falls_back_to_default():
    assert normalize_theme("not-a-theme") == "default"
    assert resolve_theme("nope")["theme"] == "default"
