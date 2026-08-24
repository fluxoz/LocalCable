"""Escape / show-guide focuses the guide and never alters the player window."""

from __future__ import annotations

from types import SimpleNamespace

from localcable.guide_focus import focus_guide_window
from localcable.mpv.show_guide import main as show_guide_helper_main


def test_kdotool_activates_guide_without_resizing():
    calls: list[list[str]] = []

    def which(name: str) -> str | None:
        return "/usr/bin/kdotool" if name == "kdotool" else None

    def run(argv, **_kwargs):
        calls.append(list(argv))
        if argv[:2] == ["kdotool", "search"]:
            return SimpleNamespace(returncode=0, stdout="0x1234\n")
        return SimpleNamespace(returncode=0, stdout="")

    opened: list[str] = []
    result = focus_guide_window(
        title="LocalCable Guide",
        url="http://127.0.0.1:8787/",
        run=run,
        which=which,
        open_url=opened.append,
        environ={},
    )
    assert result == {"ok": True, "method": "kdotool"}
    assert opened == []
    assert calls[0][:3] == ["kdotool", "search", "--title"]
    assert calls[1] == ["kdotool", "windowactivate", "0x1234"]
    joined = " ".join(" ".join(c) for c in calls)
    assert "mpv" not in joined
    assert "fullscreen" not in joined
    assert "minimize" not in joined
    assert "windowsize" not in joined
    assert "quit" not in joined


def test_niri_focuses_matching_title(monkeypatch):
    calls: list[list[str]] = []

    def which(name: str) -> str | None:
        return "/usr/bin/niri" if name == "niri" else None

    def run(argv, **_kwargs):
        calls.append(list(argv))
        if argv == ["niri", "msg", "--json", "windows"]:
            return SimpleNamespace(
                returncode=0,
                stdout='[{"id": 9, "title": "LocalCable Guide — Chromium"}]',
            )
        return SimpleNamespace(returncode=0, stdout="")

    result = focus_guide_window(
        run=run,
        which=which,
        open_url=lambda _u: None,
        environ={"NIRI_SOCKET": "/tmp/niri.sock"},
    )
    assert result == {"ok": True, "method": "niri"}
    assert ["niri", "msg", "action", "focus-window", "--id", "9"] in calls


def test_falls_back_to_opening_guide_url():
    opened: list[str] = []
    result = focus_guide_window(
        url="http://127.0.0.1:8787/",
        run=lambda *_a, **_k: SimpleNamespace(returncode=1, stdout=""),
        which=lambda _n: None,
        open_url=opened.append,
        environ={},
    )
    assert result == {"ok": True, "method": "open_url"}
    assert opened == ["http://127.0.0.1:8787/"]


def test_helper_posts_show_guide_only(monkeypatch):
    seen: list[str] = []

    class Dummy:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_urlopen(request, timeout=3):
        seen.append(request.full_url)
        assert request.get_method() == "POST"
        return Dummy()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert show_guide_helper_main(["http://127.0.0.1:8787"]) == 0
    assert seen == ["http://127.0.0.1:8787/api/show-guide"]


def test_helper_posts_channel_up_to_remote(monkeypatch):
    seen: list[tuple[str, str | None]] = []

    class Dummy:
        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def fake_urlopen(request, timeout=3):
        body = request.data.decode("utf-8") if request.data else None
        seen.append((request.full_url, body))
        return Dummy()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert show_guide_helper_main(["http://127.0.0.1:8787", "channel-up"]) == 0
    assert seen[0][0] == "http://127.0.0.1:8787/api/remote"
    assert seen[0][1] and "channel-up" in seen[0][1]
