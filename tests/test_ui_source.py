"""Static fallback: shipped page source contains every required guide landmark."""

from __future__ import annotations

from pathlib import Path

STATIC = Path(__file__).resolve().parents[1] / "src" / "localcable" / "static"


def test_html_has_guide_landmarks():
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    for needle in (
        'id="provider-logo"',
        'id="detail-panel"',
        'id="detail-title"',
        'id="detail-time"',
        'id="detail-rating"',
        'id="detail-description"',
        'id="detail-thumb"',
        'id="detail-art"',
        'id="video-overlay"',
        'id="video-overlay-title"',
        'id="time-axis"',
        'id="channel-column"',
        'id="program-grid"',
        'id="now-line"',
        'id="play-button"',
        'id="header-label"',
        'id="player"',
        'id="hud"',
        'id="hud-restart"',
        'id="hud-crt"',
        'id="stage"',
        "TV Listings",
        "/static/vendor/dash.all.min.js",
    ):
        assert needle in html, needle
    assert "cdn.dashjs.org" not in html
    assert "unpkg.com" not in html
    assert "jsdelivr" not in html
    assert "cdnjs" not in html


def test_css_has_layout_hooks():
    css = (STATIC / "guide.css").read_text(encoding="utf-8")
    for needle in (
        "#provider-logo",
        "#channel-column",
        "#time-axis",
        ".program",
        "#now-line",
        "#detail-panel",
        ".no-media",
        "#video-overlay",
        "#detail-art",
        ".with-mail",
        "#stage",
        "#hud",
        "#hud-crt-label",
        ".crt-vhs",
        "#player",
        "body.watching",
    ):
        assert needle in css, needle


def test_js_is_browser_script_without_node_modules():
    js = (STATIC / "guide.js").read_text(encoding="utf-8")
    assert "require(" not in js
    assert "module.exports" not in js
    assert "module.exports" not in js
    assert "from '" not in js
    assert "from \"" not in js
    assert "export " not in js
    assert "LocalCableGuide" in js
    assert "selectProgram" in js
    assert "now-line" in js
    assert "Escape" in js
    assert "returnToGuide" in js
    assert "schedulePreview" in js
    assert "loadPreview" in js
    on_return = js.split("function returnToGuide", 1)[1].split("function cancelPreview", 1)[0]
    assert "/api/show-guide" not in on_return
    assert "leaveWatching" in on_return
    assert "No programming" in js
    assert "no-media" in js
    assert "showVideoOverlay" in js
    assert "showArt" in js
    assert "applyUi" in js
    assert "/api/ui" in js
    assert "/art/" in js
    assert "video-overlay" in js
    assert "ChannelUp" in js
    assert "typeChannelDigit" in js
    assert "isGuideKey" in js
    assert "scrollProgramIntoView" in js
    assert "/api/stream" in js
    assert "dashjs" in js
    assert "enterWatching" in js
    assert "handleWatchKey" in js
    assert "restartFromBeginning" in js
    assert "liveOffset" in js
    assert "from_start" in js
    assert "hud-crt" in js
    assert "activeFilter" in js
    assert "/api/preview/" in js
    assert "applyCrtClass" in js
    on_key = js.split("function onKey", 1)[1].split("function currentChannelIndex", 1)[0]
    assert "isGuideKey" in on_key
    assert "playProgram" in on_key


def test_stage_click_ignores_hud_controls_before_reentering_watching():
    """The stage click handler must skip HUD-control clicks (e.g. the Guide
    button) before the not-watching branch, otherwise the bubbled click would
    re-enter the large player right after returnToGuide() shrank it."""
    js = (STATIC / "guide.js").read_text(encoding="utf-8")
    handler = js.split('stage.addEventListener("click"', 1)[1].split("});", 1)[0]
    guard = handler.find('closest("#hud-row')
    reenter = handler.find("enterWatching(currentProgram())")
    assert guard != -1, "stage click handler lost its HUD-control guard"
    assert reenter != -1, "stage click handler lost its watch re-entry"
    assert guard < reenter, "HUD-control guard must run before re-entering watching"


def test_mpv_esc_script_only_runs_helper():
    lua = (STATIC.parent / "mpv" / "localcable.lua").read_text(encoding="utf-8")
    helper = (STATIC.parent / "mpv" / "show_guide.py").read_text(encoding="utf-8")
    assert "add_forced_key_binding" in lua
    assert "esc" in lua
    assert "create_osd_overlay" in lua
    assert "localcable-info" in lua
    assert "CHANNEL_UP" in lua
    assert "channel-up" in lua
    assert "/api/show-guide" in helper
    assert "play_file" not in helper
    assert "fullscreen" not in helper
    assert "subprocess" not in helper
    assert "urllib.request" in helper
