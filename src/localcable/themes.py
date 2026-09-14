"""EPG color themes and per-key overrides from settings.yaml."""

from __future__ import annotations

from typing import Any

# CSS custom-property names for every EPG color the guide uses.
COLOR_TO_CSS: dict[str, str] = {
    "page_bg": "--page-bg",
    "header_bg": "--header-bg",
    "header_bg_2": "--header-bg-2",
    "header_bg_3": "--header-bg-3",
    "detail_bg": "--detail-bg",
    "detail_panel_from": "--detail-panel-from",
    "detail_panel_to": "--detail-panel-to",
    "timebar_bg": "--timebar-bg",
    "channel_bg": "--channel-bg",
    "channel_bg_alt": "--channel-bg-alt",
    "channel_selected": "--channel-selected",
    "grid_bg": "--grid-bg",
    "row_a": "--row-a",
    "row_b": "--row-b",
    "text": "--text",
    "muted": "--muted",
    "now": "--now",
    "selected": "--selected",
    "selected_text": "--selected-text",
    "footer_bg": "--footer-bg",
    "footer_text": "--footer-text",
    "footer_border": "--footer-border",
    "grid_line": "--grid-line",
    "clock": "--clock",
    "detail_channel": "--detail-channel",
    "detail_desc": "--detail-desc",
    "program_text": "--program-text",
    "tick_text": "--tick-text",
    "thumb_bg": "--thumb-bg",
    "thumb_border": "--thumb-border",
    "overlay_from": "--overlay-from",
    "overlay_to": "--overlay-to",
    "live_badge": "--live-badge",
    "time_nav_bg": "--time-nav-bg",
    "time_nav_hover": "--time-nav-hover",
    "scrollbar_thumb": "--scrollbar-thumb",
    "scrollbar_track": "--scrollbar-track",
    "info_banner_bg": "--info-banner-bg",
}

COLOR_KEYS: tuple[str, ...] = tuple(COLOR_TO_CSS)

DEFAULT_FONT = 'Tahoma, "Segoe UI", "Trebuchet MS", Arial, sans-serif'
MODERN_FONT = '"Segoe UI", system-ui, -apple-system, sans-serif'
RETRO_FONT = '"IBM Plex Mono", "Courier New", Courier, monospace'
MIAMI_FONT = '"Trebuchet MS", "Segoe UI", Tahoma, sans-serif'

# 1. Default — current Xfinity-style EPG.
DEFAULT_COLORS: dict[str, str] = {
    "page_bg": "#041428",
    "header_bg": "#123a78",
    "header_bg_2": "#1d5aaa",
    "header_bg_3": "#3a8fd0",
    "detail_bg": "#0e3a7c",
    "detail_panel_from": "rgba(8, 40, 90, 0.35)",
    "detail_panel_to": "rgba(8, 40, 90, 0.15)",
    "timebar_bg": "#1a56a8",
    "channel_bg": "#1c4f96",
    "channel_bg_alt": "#174888",
    "channel_selected": "#1d6ad0",
    "grid_bg": "#08244c",
    "row_a": "#0b2e5e",
    "row_b": "#092850",
    "text": "#ffffff",
    "muted": "#b7d3f5",
    "now": "#ff2d2d",
    "selected": "#f5c518",
    "selected_text": "#1a1a1a",
    "footer_bg": "#0c2d62",
    "footer_text": "#c5ddf8",
    "footer_border": "#2a5aa0",
    "grid_line": "#0a2d62",
    "clock": "#e8f3ff",
    "detail_channel": "#d5e8ff",
    "detail_desc": "#e6f0ff",
    "program_text": "#f4fbff",
    "tick_text": "#eaf3ff",
    "thumb_bg": "#0a2a55",
    "thumb_border": "rgba(255, 255, 255, 0.25)",
    "overlay_from": "#0b3a72",
    "overlay_to": "#1a5a9a",
    "live_badge": "#e12626",
    "time_nav_bg": "rgba(12, 45, 98, 0.92)",
    "time_nav_hover": "#1d5cb8",
    "scrollbar_thumb": "#2a6cc0",
    "scrollbar_track": "#071e40",
    "info_banner_bg": "rgba(6, 24, 56, 0.92)",
}

DEFAULT_PALETTE: tuple[str, ...] = (
    "#2e8b6e",
    "#247a9e",
    "#3a9d5c",
    "#1e6b8a",
    "#2d9c8a",
    "#246b7a",
    "#3d8b5c",
    "#1a5f7a",
    "#2a7d9e",
    "#1f7a64",
)

# 2. Dark — near-black guide with a cool accent.
DARK_COLORS: dict[str, str] = {
    "page_bg": "#0a0a0c",
    "header_bg": "#121218",
    "header_bg_2": "#1c1c24",
    "header_bg_3": "#2a2a36",
    "detail_bg": "#16161e",
    "detail_panel_from": "rgba(20, 20, 28, 0.55)",
    "detail_panel_to": "rgba(20, 20, 28, 0.2)",
    "timebar_bg": "#1a1a22",
    "channel_bg": "#18181f",
    "channel_bg_alt": "#14141a",
    "channel_selected": "#2a3348",
    "grid_bg": "#0c0c10",
    "row_a": "#14141a",
    "row_b": "#101016",
    "text": "#f0f0f4",
    "muted": "#9aa0b0",
    "now": "#ff4d4d",
    "selected": "#e8c547",
    "selected_text": "#121212",
    "footer_bg": "#101014",
    "footer_text": "#a8aebc",
    "footer_border": "#2a2a36",
    "grid_line": "#22222c",
    "clock": "#d8dce8",
    "detail_channel": "#c4c8d4",
    "detail_desc": "#d8dce8",
    "program_text": "#f4f4f8",
    "tick_text": "#d0d4e0",
    "thumb_bg": "#1a1a22",
    "thumb_border": "rgba(255, 255, 255, 0.18)",
    "overlay_from": "#1a1a22",
    "overlay_to": "#2a2a36",
    "live_badge": "#e12626",
    "time_nav_bg": "rgba(18, 18, 24, 0.94)",
    "time_nav_hover": "#2a2a36",
    "scrollbar_thumb": "#3a3a48",
    "scrollbar_track": "#0a0a0c",
    "info_banner_bg": "rgba(12, 12, 16, 0.94)",
}

DARK_PALETTE: tuple[str, ...] = (
    "#3d5a80",
    "#2f4a6e",
    "#4a6741",
    "#5a4a78",
    "#3a6a6a",
    "#6a4a4a",
    "#4a5a78",
    "#2a5a4a",
    "#5a3a5a",
    "#3a4a6a",
)

# 3. Modern — flat slate with a single blue accent.
MODERN_COLORS: dict[str, str] = {
    "page_bg": "#0f1419",
    "header_bg": "#1a2332",
    "header_bg_2": "#243044",
    "header_bg_3": "#2e3d56",
    "detail_bg": "#1c2736",
    "detail_panel_from": "rgba(36, 48, 68, 0.45)",
    "detail_panel_to": "rgba(36, 48, 68, 0.15)",
    "timebar_bg": "#243044",
    "channel_bg": "#1e2a3a",
    "channel_bg_alt": "#192433",
    "channel_selected": "#2f4a6e",
    "grid_bg": "#121820",
    "row_a": "#1a222c",
    "row_b": "#161c26",
    "text": "#f5f7fa",
    "muted": "#9eb0c4",
    "now": "#ff5a5a",
    "selected": "#3d8bfd",
    "selected_text": "#ffffff",
    "footer_bg": "#141a22",
    "footer_text": "#9eb0c4",
    "footer_border": "#2e3d56",
    "grid_line": "#243044",
    "clock": "#d6e2f0",
    "detail_channel": "#c5d4e6",
    "detail_desc": "#dce6f0",
    "program_text": "#f5f7fa",
    "tick_text": "#d6e2f0",
    "thumb_bg": "#1a2332",
    "thumb_border": "rgba(255, 255, 255, 0.2)",
    "overlay_from": "#1a2332",
    "overlay_to": "#243044",
    "live_badge": "#e12626",
    "time_nav_bg": "rgba(26, 35, 50, 0.94)",
    "time_nav_hover": "#2e3d56",
    "scrollbar_thumb": "#3d8bfd",
    "scrollbar_track": "#0f1419",
    "info_banner_bg": "rgba(15, 20, 25, 0.94)",
}

MODERN_PALETTE: tuple[str, ...] = (
    "#2b6cb0",
    "#2c7a7b",
    "#2f855a",
    "#6b46c1",
    "#c05621",
    "#2b6cb0",
    "#319795",
    "#553c9a",
    "#2c5282",
    "#276749",
)

# 4. Retro Green — old-school terminal phosphor.
RETRO_GREEN_COLORS: dict[str, str] = {
    "page_bg": "#001400",
    "header_bg": "#002200",
    "header_bg_2": "#003300",
    "header_bg_3": "#004400",
    "detail_bg": "#001a00",
    "detail_panel_from": "rgba(0, 40, 0, 0.5)",
    "detail_panel_to": "rgba(0, 40, 0, 0.15)",
    "timebar_bg": "#003300",
    "channel_bg": "#002800",
    "channel_bg_alt": "#001e00",
    "channel_selected": "#005500",
    "grid_bg": "#000e00",
    "row_a": "#001800",
    "row_b": "#001200",
    "text": "#33ff66",
    "muted": "#1a9933",
    "now": "#ff3333",
    "selected": "#66ff99",
    "selected_text": "#001400",
    "footer_bg": "#001000",
    "footer_text": "#1a9933",
    "footer_border": "#004400",
    "grid_line": "#003300",
    "clock": "#66ff99",
    "detail_channel": "#33cc55",
    "detail_desc": "#44ee77",
    "program_text": "#44ff77",
    "tick_text": "#33ff66",
    "thumb_bg": "#001a00",
    "thumb_border": "rgba(51, 255, 102, 0.35)",
    "overlay_from": "#002200",
    "overlay_to": "#003300",
    "live_badge": "#ff3333",
    "time_nav_bg": "rgba(0, 34, 0, 0.94)",
    "time_nav_hover": "#005500",
    "scrollbar_thumb": "#1a9933",
    "scrollbar_track": "#000e00",
    "info_banner_bg": "rgba(0, 20, 0, 0.94)",
}

RETRO_GREEN_PALETTE: tuple[str, ...] = (
    "#145a28",
    "#0e4a20",
    "#1a6a30",
    "#0a3a18",
    "#227838",
    "#124820",
    "#1e6030",
    "#0c4020",
    "#186028",
    "#0e5024",
)

# 5. Miami Vice — palette https://www.color-hex.com/color-palette/45581
#    #0bd3d3  #f890e7  #ffffff  #d0d0d0  #000000
MIAMI_VICE_COLORS: dict[str, str] = {
    "page_bg": "#000000",
    "header_bg": "#0bd3d3",
    "header_bg_2": "#089999",
    "header_bg_3": "#f890e7",
    "detail_bg": "#0a0a0a",
    "detail_panel_from": "rgba(11, 211, 211, 0.18)",
    "detail_panel_to": "rgba(248, 144, 231, 0.12)",
    "timebar_bg": "#111111",
    "channel_bg": "#0a2222",
    "channel_bg_alt": "#081818",
    "channel_selected": "#0bd3d3",
    "grid_bg": "#050505",
    "row_a": "#101010",
    "row_b": "#0a0a0a",
    "text": "#ffffff",
    "muted": "#d0d0d0",
    "now": "#f890e7",
    "selected": "#f890e7",
    "selected_text": "#000000",
    "footer_bg": "#000000",
    "footer_text": "#d0d0d0",
    "footer_border": "#0bd3d3",
    "grid_line": "#1a1a1a",
    "clock": "#ffffff",
    "detail_channel": "#0bd3d3",
    "detail_desc": "#d0d0d0",
    "program_text": "#ffffff",
    "tick_text": "#0bd3d3",
    "thumb_bg": "#111111",
    "thumb_border": "#0bd3d3",
    "overlay_from": "#000000",
    "overlay_to": "#0a2222",
    "live_badge": "#f890e7",
    "time_nav_bg": "rgba(0, 0, 0, 0.94)",
    "time_nav_hover": "#0bd3d3",
    "scrollbar_thumb": "#f890e7",
    "scrollbar_track": "#000000",
    "info_banner_bg": "rgba(0, 0, 0, 0.92)",
}

MIAMI_VICE_PALETTE: tuple[str, ...] = (
    "#087a7a",
    "#8a3a7a",
    "#0a6a6a",
    "#6a2a5a",
    "#0bd3d3",
    "#c060b0",
    "#055555",
    "#f890e7",
    "#0a4444",
    "#aa5088",
)

# 6. Dark Blue — classic DirecTV-style navy EPG.
DARK_BLUE_COLORS: dict[str, str] = {
    "page_bg": "#021030",
    "header_bg": "#0a3d7a",
    "header_bg_2": "#1568b0",
    "header_bg_3": "#1e86c8",
    "detail_bg": "#0a3270",
    "detail_panel_from": "rgba(10, 50, 110, 0.45)",
    "detail_panel_to": "rgba(10, 50, 110, 0.15)",
    "timebar_bg": "#0e4a90",
    "channel_bg": "#0d3d7a",
    "channel_bg_alt": "#0a3368",
    "channel_selected": "#1a68c0",
    "grid_bg": "#041c40",
    "row_a": "#072650",
    "row_b": "#051e44",
    "text": "#ffffff",
    "muted": "#9ec4ea",
    "now": "#ff2d2d",
    "selected": "#f5c518",
    "selected_text": "#102040",
    "footer_bg": "#031830",
    "footer_text": "#9ec4ea",
    "footer_border": "#1a5a9a",
    "grid_line": "#0a2d62",
    "clock": "#e8f3ff",
    "detail_channel": "#c5ddf8",
    "detail_desc": "#e0eefc",
    "program_text": "#f4fbff",
    "tick_text": "#eaf3ff",
    "thumb_bg": "#08244c",
    "thumb_border": "rgba(255, 255, 255, 0.28)",
    "overlay_from": "#0a3d7a",
    "overlay_to": "#1568b0",
    "live_badge": "#e12626",
    "time_nav_bg": "rgba(8, 36, 80, 0.94)",
    "time_nav_hover": "#1a68c0",
    "scrollbar_thumb": "#1a6eb8",
    "scrollbar_track": "#021030",
    "info_banner_bg": "rgba(4, 28, 64, 0.94)",
}

DARK_BLUE_PALETTE: tuple[str, ...] = (
    "#1a5a8a",
    "#164e7a",
    "#1e6a70",
    "#145070",
    "#226888",
    "#184860",
    "#1c6080",
    "#124058",
    "#1a5878",
    "#165068",
)

THEMES: dict[str, dict[str, Any]] = {
    "default": {
        "label": "Default",
        "font": DEFAULT_FONT,
        "colors": DEFAULT_COLORS,
        "palette": DEFAULT_PALETTE,
    },
    "dark": {
        "label": "Dark",
        "font": DEFAULT_FONT,
        "colors": DARK_COLORS,
        "palette": DARK_PALETTE,
    },
    "modern": {
        "label": "Modern",
        "font": MODERN_FONT,
        "colors": MODERN_COLORS,
        "palette": MODERN_PALETTE,
    },
    "retro-green": {
        "label": "Retro Green",
        "font": RETRO_FONT,
        "colors": RETRO_GREEN_COLORS,
        "palette": RETRO_GREEN_PALETTE,
    },
    "miami-vice": {
        "label": "Miami Vice",
        "font": MIAMI_FONT,
        "colors": MIAMI_VICE_COLORS,
        "palette": MIAMI_VICE_PALETTE,
    },
    "dark-blue": {
        "label": "Dark Blue",
        "font": DEFAULT_FONT,
        "colors": DARK_BLUE_COLORS,
        "palette": DARK_BLUE_PALETTE,
    },
}

THEME_ALIASES: dict[str, str] = {
    "default": "default",
    "xfinity": "default",
    "classic": "default",
    "dark": "dark",
    "night": "dark",
    "modern": "modern",
    "sleek": "modern",
    "retro-green": "retro-green",
    "retro_green": "retro-green",
    "retrogreen": "retro-green",
    "terminal": "retro-green",
    "green": "retro-green",
    "miami-vice": "miami-vice",
    "miami_vice": "miami-vice",
    "miamivice": "miami-vice",
    "miami": "miami-vice",
    "dark-blue": "dark-blue",
    "dark_blue": "dark-blue",
    "darkblue": "dark-blue",
    "directv": "dark-blue",
    "direc": "dark-blue",
    "dtv": "dark-blue",
}

PRESET_NAMES: tuple[str, ...] = (
    "default",
    "dark",
    "modern",
    "retro-green",
    "miami-vice",
    "dark-blue",
)


def normalize_theme(value: Any, default: str = "default") -> str:
    if value is None:
        return default
    text = str(value).strip().lower().replace(" ", "-").replace("_", "-")
    return THEME_ALIASES.get(text, default if text not in THEMES else text)


def _parse_color(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text


def resolve_theme(
    name: Any = "default",
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the fully resolved theme: name, label, font, colors, palette."""
    key = normalize_theme(name)
    if key not in THEMES:
        key = "default"
    preset = THEMES[key]
    colors = dict(preset["colors"])
    palette = list(preset["palette"])
    extra = overrides or {}
    for color_key in COLOR_KEYS:
        parsed = _parse_color(extra.get(color_key))
        if parsed:
            colors[color_key] = parsed
    raw_palette = extra.get("palette")
    if isinstance(raw_palette, (list, tuple)) and raw_palette:
        cleaned = [str(item).strip() for item in raw_palette if str(item).strip()]
        if cleaned:
            palette = cleaned
    return {
        "theme": key,
        "label": preset["label"],
        "font": extra.get("font") or preset["font"],
        "colors": colors,
        "palette": palette,
        "presets": list(PRESET_NAMES),
    }
