"""Evaluate shipped guide.js with a window global (no Node module/require)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parents[1] / "src" / "localcable" / "static"

SCHEDULE = {
    "now": "2026-08-23T15:00:00+00:00",
    "window_start": "2026-08-23T14:50:00+00:00",
    "window_end": "2026-08-23T18:00:00+00:00",
    "channels": [
        {
            "number": 101,
            "name": "CNN",
            "folder_path": "/media/101_CNN",
            "schedule_mode": "sequential",
            "programs": [
                {
                    "id": "p-news",
                    "title": "Evening News",
                    "description": "A fixture newscast.",
                    "rating": "TV-G",
                    "genre": None,
                    "duration_seconds": 600,
                    "file_path": "/media/101_CNN/evening_news.mp4",
                    "start_time": "2026-08-23T14:50:00+00:00",
                    "end_time": "2026-08-23T15:00:00+00:00",
                    "channel_number": 101,
                    "channel_name": "CNN",
                },
                {
                    "id": "p-late",
                    "title": "Late Edition",
                    "description": "More news after now.",
                    "rating": None,
                    "genre": None,
                    "duration_seconds": 1200,
                    "file_path": "/media/101_CNN/late_edition.mp4",
                    "start_time": "2026-08-23T15:00:00+00:00",
                    "end_time": "2026-08-23T15:20:00+00:00",
                    "channel_number": 101,
                    "channel_name": "CNN",
                },
                {
                    "id": "p-night",
                    "title": "Night Desk",
                    "description": "Hours later on the timeline.",
                    "rating": None,
                    "genre": None,
                    "duration_seconds": 3600,
                    "file_path": "/media/101_CNN/night_desk.mp4",
                    "start_time": "2026-08-23T17:00:00+00:00",
                    "end_time": "2026-08-23T18:00:00+00:00",
                    "channel_number": 101,
                    "channel_name": "CNN",
                },
            ],
        }
    ],
}


def _chromium() -> str | None:
    return shutil.which("chromium") or shutil.which("chromium-browser")


@pytest.mark.skipif(_chromium() is None, reason="chromium not installed")
def test_guide_js_installs_and_click_updates_detail(tmp_path: Path):
    js = (STATIC / "guide.js").read_text(encoding="utf-8")
    html_src = (STATIC / "index.html").read_text(encoding="utf-8")
    # Drop the external script tag; we inline so this works without a server.
    html_src = re.sub(r'<script src="/static/guide.js"></script>', "", html_src)
    html_src = html_src.replace(
        '<link rel="stylesheet" href="/static/guide.css">',
        "<style>" + (STATIC / "guide.css").read_text(encoding="utf-8") + "</style>",
    )
    payload = json.dumps(SCHEDULE)
    boot = f"""
<script>
window.LocalCableSkipAutoLoad = true;
window.__pageErrors = [];
window.onerror = function (msg) {{ window.__pageErrors.push(String(msg)); }};
</script>
<script>
{js}
</script>
<script>
(function () {{
  var errors = window.__pageErrors.slice();
  try {{
    var scroller0 = document.getElementById("grid-scroll");
    if (scroller0) {{
      scroller0.style.cssText = "position:relative;width:640px;max-width:640px;min-width:0;height:240px;overflow:scroll;";
    }}
    window.LocalCableGuide.render({payload});
    var late = document.querySelector('[data-program-id="p-late"]');
    if (!late) throw new Error("late program block missing");
    late.dispatchEvent(new MouseEvent("click", {{ bubbles: true }}));
    var night = document.querySelector('[data-program-id="p-night"]');
    if (!night) throw new Error("night program block missing");
    night.dispatchEvent(new MouseEvent("click", {{ bubbles: true }}));
    if (window.LocalCableGuide.scrollProgramIntoView) window.LocalCableGuide.scrollProgramIntoView("p-night");
  }} catch (err) {{
    errors.push(String(err));
  }}
  var title = document.getElementById("detail-title");
  var time = document.getElementById("detail-time");
  var scroller = document.getElementById("grid-scroll");
  var report = {{
    installed: !!(window.LocalCableGuide && window.LocalCableGuide.selectProgram && window.LocalCableGuide.scrollProgramIntoView),
    errors: errors,
    title: title ? title.textContent : "",
    time: time ? time.textContent : "",
    programs: document.querySelectorAll(".program").length,
    selected: document.querySelectorAll(".program.selected").length,
    nowLine: !!document.getElementById("now-line"),
    channels: document.querySelectorAll(".channel-cell").length,
    hasHud: !!document.getElementById("hud"),
    hasPlayer: !!document.getElementById("player"),
    scrollLeft: scroller ? scroller.scrollLeft : -1
  }};
  var el = document.createElement("pre");
  el.id = "eval-report";
  el.textContent = JSON.stringify(report);
  document.body.appendChild(el);
}})();
</script>
"""
    html_src = html_src.replace("</body>", boot + "</body>")
    page = tmp_path / "guide.html"
    page.write_text(html_src, encoding="utf-8")

    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    proc = subprocess.run(
        [
            _chromium(),
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--user-data-dir={profile}",
            "--window-size=1400,900",
            "--virtual-time-budget=3000",
            "--dump-dom",
            str(page),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-1000:]
    match = re.search(r'<pre id="eval-report">([^<]+)</pre>', proc.stdout)
    assert match, proc.stdout[-2000:]
    report = json.loads(match.group(1).replace("&quot;", '"'))
    assert report["installed"] is True
    assert report["errors"] == []
    assert report["programs"] >= 2
    assert report["channels"] == 1
    assert report["nowLine"] is True
    assert report["title"] == "Night Desk"
    assert report["time"]
    assert report["selected"] == 1
    assert report["hasHud"] is True
    assert report["hasPlayer"] is True
    assert report["scrollLeft"] > 200


@pytest.mark.skipif(_chromium() is None, reason="chromium not installed")
def test_guide_js_auto_advances_on_media_end(tmp_path: Path):
    js = (STATIC / "guide.js").read_text(encoding="utf-8")
    html_src = (STATIC / "index.html").read_text(encoding="utf-8")
    html_src = re.sub(r'<script src="/static/guide.js"></script>', "", html_src)
    html_src = html_src.replace(
        '<link rel="stylesheet" href="/static/guide.css">',
        "<style>" + (STATIC / "guide.css").read_text(encoding="utf-8") + "</style>",
    )
    payload = json.dumps(SCHEDULE)
    boot = f"""
<script>
window.LocalCableSkipAutoLoad = true;
window.__pageErrors = [];
window.onerror = function (msg) {{ window.__pageErrors.push(String(msg)); }};
</script>
<script>
{js}
</script>
<script>
(function () {{
  var errors = window.__pageErrors.slice();
  var guide = window.LocalCableGuide;
  var state = guide.getState();
  var nextTitle = "";
  var advancedTitle = "";
  try {{
    guide.render({payload});
    var late = guide.getState().programs["p-late"];
    var computed = guide.nextProgram(late);
    nextTitle = computed ? computed.title : "";
    // Simulate watching p-late, then the media file finishing.
    guide.selectProgram("p-late");
    guide.enterWatching(late);
    var video = document.getElementById("player");
    video.dispatchEvent(new Event("ended"));
    var advanced = guide.getState().selectedId;
    var prog = guide.getState().programs[advanced];
    advancedTitle = prog ? prog.title : "";
  }} catch (err) {{
    errors.push(String(err));
  }}
  var report = {{
    errors: errors,
    nextTitle: nextTitle,
    advancedTitle: advancedTitle,
  }};
  var el = document.createElement("pre");
  el.id = "eval-report";
  el.textContent = JSON.stringify(report);
  document.body.appendChild(el);
}})();
</script>
"""
    html_src = html_src.replace("</body>", boot + "</body>")
    page = tmp_path / "guide.html"
    page.write_text(html_src, encoding="utf-8")

    profile = tmp_path / "chrome-profile"
    profile.mkdir()
    proc = subprocess.run(
        [
            _chromium(),
            "--headless=new",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            f"--user-data-dir={profile}",
            "--window-size=1400,900",
            "--virtual-time-budget=3000",
            "--dump-dom",
            str(page),
        ],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr[-1000:]
    match = re.search(r'<pre id="eval-report">([^<]+)</pre>', proc.stdout)
    assert match, proc.stdout[-2000:]
    report = json.loads(match.group(1).replace("&quot;", '"'))
    assert report["errors"] == []
    assert report["nextTitle"] == "Night Desk"
    assert report["advancedTitle"] == "Night Desk"

