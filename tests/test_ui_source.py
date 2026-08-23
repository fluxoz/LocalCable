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
        'id="time-axis"',
        'id="channel-column"',
        'id="program-grid"',
        'id="now-line"',
        'id="play-button"',
    ):
        assert needle in html, needle


def test_css_has_layout_hooks():
    css = (STATIC / "guide.css").read_text(encoding="utf-8")
    for needle in (
        "#provider-logo",
        "#channel-column",
        "#time-axis",
        ".program",
        "#now-line",
        "#detail-panel",
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
