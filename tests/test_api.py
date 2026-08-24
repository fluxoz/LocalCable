"""HTTP schedule + play against the shipped FastAPI app (no test doubles for scan)."""

from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from localcable.app import AppState, create_app
from localcable.config import (
    AppConfig,
    ArtworkConfig,
    LibraryConfig,
    PlaybackConfig,
    ScheduleConfig,
    UiConfig,
)
from localcable.player import MpvController


def _config(tmp_path: Path, media_root: Path, mode: str = "sequential") -> AppConfig:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "provider_logo.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"><rect width="10" height="10" fill="red"/></svg>',
        encoding="utf-8",
    )
    return AppConfig(
        media_roots=[media_root],
        config_dir=config_dir,
        schedule=ScheduleConfig(
            window_hours_before=10 / 3600,
            window_hours_after=20 / 3600,
            default_mode=mode,
        ),
        playback=PlaybackConfig(player="mpv", start_from="beginning", mpv_args=[]),
        ui=UiConfig(auto_open_browser=False, bind_host="127.0.0.1", bind_port=8787),
        artwork=ArtworkConfig(fetch=False),
        library=LibraryConfig(fetch_metadata=False),
        logo_filename="provider_logo.svg",
    )


def _fake_player(tmp_path: Path) -> tuple[MpvController, list[list[str]]]:
    recorded: list[list[str]] = []

    class Proc:
        def poll(self):
            return None

    def popen(argv, **_kwargs):
        recorded.append(list(argv))
        return Proc()

    player = MpvController(
        tmp_path / "config" / "mpv.sock",
        extra_args=[],
        popen=popen,
        which=lambda _n: "/usr/bin/mpv",
    )
    return player, recorded


def test_schedule_api_lists_fixture_channels(
    tmp_path: Path, media_root: Path, frozen_now: datetime
):
    config = _config(tmp_path, media_root)
    player, _recorded = _fake_player(tmp_path)
    state = AppState(config, now_fn=lambda: frozen_now, player=player, rng=random.Random(0))
    app = create_app(state=state)
    with TestClient(app) as client:
        response = client.get("/api/schedule")
        assert response.status_code == 200
        body = response.json()
        assert body.get("channels"), body
        names = {ch["name"] for ch in body["channels"]}
        numbers = {ch["name"]: ch["number"] for ch in body["channels"]}
        assert "CNN" in names
        assert "HBO" in names
        assert numbers["CNN"] == 101
        now = datetime.fromisoformat(body["now"])
        spanned = False
        for channel in body["channels"]:
            assert channel["programs"], channel
            for program in channel["programs"]:
                assert program["title"]
                assert program["start_time"]
                assert program["end_time"]
                start = datetime.fromisoformat(program["start_time"])
                end = datetime.fromisoformat(program["end_time"])
                if start <= now < end:
                    spanned = True
        assert spanned, "no program airing at frozen now"


def test_index_and_logo(tmp_path: Path, media_root: Path, frozen_now: datetime):
    config = _config(tmp_path, media_root)
    player, _ = _fake_player(tmp_path)
    state = AppState(config, now_fn=lambda: frozen_now, player=player)
    app = create_app(state=state)
    with TestClient(app) as client:
        page = client.get("/")
        assert page.status_code == 200
        html = page.text
        for needle in (
            "provider-logo",
            "detail-panel",
            "time-axis",
            "channel-column",
            "program-grid",
            "now-line",
            "play-button",
        ):
            assert needle in html
        logo = client.get("/logo")
        assert logo.status_code == 200
        assert "image" in logo.headers.get("content-type", "")
        js = client.get("/static/guide.js")
        assert js.status_code == 200
        assert "LocalCableGuide" in js.text
        assert "TV Listings" in html
        assert "/static/vendor/dash.all.min.js" in html
        assert "cdn.dashjs.org" not in html
        assert 'id="player"' in html
        assert 'id="hud"' in html
        ui = client.get("/api/ui")
        assert ui.status_code == 200
        assert ui.json()["banner"] == "TV Listings"
        assert ui.json()["player"] == "mpv"
        vendor = client.get("/static/vendor/dash.all.min.js")
        assert vendor.status_code == 200
        assert "dashjs" in vendor.text[:500]


def test_custom_banner_text(tmp_path: Path, media_root: Path, frozen_now: datetime):
    config = _config(tmp_path, media_root)
    config.ui.banner = "Coyote Cable"
    player, _ = _fake_player(tmp_path)
    state = AppState(config, now_fn=lambda: frozen_now, player=player)
    app = create_app(state=state)
    with TestClient(app) as client:
        html = client.get("/").text
        assert "Coyote Cable" in html
        assert "TV Listings" not in html
        assert "with-mail" not in html
        ui = client.get("/api/ui").json()
        assert ui["banner"] == "Coyote Cable"


def test_play_endpoint_invokes_mpv_on_fixture_path(
    tmp_path: Path, media_root: Path, frozen_now: datetime
):
    config = _config(tmp_path, media_root)
    player, recorded = _fake_player(tmp_path)
    state = AppState(config, now_fn=lambda: frozen_now, player=player)
    app = create_app(state=state)
    with TestClient(app) as client:
        body = client.get("/api/schedule").json()
        program = body["channels"][0]["programs"][0]
        response = client.post("/api/play", json={"program_id": program["id"]})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["ok"] is True
        assert payload["path"] == program["file_path"]
        assert Path(payload["path"]).exists()
        assert recorded, "mpv was not spawned"
        argv = recorded[0]
        assert argv[-1] == program["file_path"]
        assert any("mpv" in part for part in argv)
        assert ["loadfile", payload["path"], "replace"] in payload["ipc_commands"]
        assert ["seek", 0, "absolute"] in payload["ipc_commands"]
        osd = json.loads((config.config_dir / "osd.json").read_text(encoding="utf-8"))
        assert osd["title"] == program["title"]
        assert str(osd["channel_number"]) == str(program["channel_number"])


def test_empty_channel_folder_listed_without_programs(
    tmp_path: Path, frozen_now: datetime
):
    media_root = tmp_path / "media"
    (media_root / "101_CNN").mkdir(parents=True)
    (media_root / "Weather").mkdir(parents=True)
    config = _config(tmp_path, media_root)
    player, _ = _fake_player(tmp_path)
    state = AppState(config, now_fn=lambda: frozen_now, player=player)
    app = create_app(state=state)
    with TestClient(app) as client:
        body = client.get("/api/schedule").json()
        by_name = {ch["name"]: ch for ch in body["channels"]}
        assert set(by_name) == {"CNN", "Weather"}
        assert by_name["CNN"]["number"] == 101
        assert by_name["CNN"]["programs"] == []
        assert by_name["Weather"]["programs"] == []
        listed = client.get("/api/channels").json()
        assert {row["name"] for row in listed} == {"CNN", "Weather"}


def test_show_guide_does_not_touch_player(
    tmp_path: Path, media_root: Path, frozen_now: datetime
):
    config = _config(tmp_path, media_root)
    player, _recorded = _fake_player(tmp_path)

    def boom(*_a, **_k):
        raise AssertionError("show-guide must not talk to the player")

    player.play_file = boom  # type: ignore[method-assign]
    focused: list[dict] = []

    def fake_focus(**kwargs):
        focused.append(kwargs)
        return {"method": "test"}

    state = AppState(
        config,
        now_fn=lambda: frozen_now,
        player=player,
        focus_guide=fake_focus,
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        response = client.post("/api/show-guide")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["ok"] is True
        assert body["method"] == "test"
        assert "8787" in body["url"]
    assert focused
    assert focused[0]["title"] == "LocalCable Guide"
    assert "mpv" not in str(focused).lower()


class _FakePackager:
    def __init__(self, root: Path):
        self.root = Path(root) / "dash"

    def manifest_url(self, program_id: str) -> str:
        return f"/dash/{program_id}/manifest.mpd"

    def resolve_file(self, program_id: str, name: str):
        path = self.root / program_id / name
        return path if path.is_file() else None

    def ensure(self, program_id: str, file_path, *, wait: float = 8.0, start_seconds: float = 0.0):
        dest = self.root / program_id
        dest.mkdir(parents=True, exist_ok=True)
        mpd = dest / "manifest.mpd"
        mpd.write_text('<?xml version="1.0"?><MPD profiles="urn:mpeg:dash:profile:isoff-on-demand:2011"/>' + "x" * 40)
        (dest / "init-0.m4s").write_bytes(b"fake-segment")
        return mpd


def test_stream_endpoint_serves_vendored_dash_manifest(
    tmp_path: Path, media_root: Path, frozen_now: datetime
):
    config = _config(tmp_path, media_root)
    config.playback.player = "browser"
    player, recorded = _fake_player(tmp_path)
    state = AppState(
        config,
        now_fn=lambda: frozen_now,
        player=player,
        packager=_FakePackager(config.cache_dir),
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        body = client.get("/api/schedule").json()
        program = body["channels"][0]["programs"][0]
        response = client.post("/api/stream", json={"program_id": program["id"]})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["ok"] is True
        assert payload["manifest"] == f"/dash/{program['id']}/manifest.mpd"
        assert recorded == []
        mpd = client.get(payload["manifest"])
        assert mpd.status_code == 200
        assert "dash" in mpd.headers.get("content-type", "").lower()
        seg = client.get(f"/dash/{program['id']}/init-0.m4s")
        assert seg.status_code == 200
        missing = client.get(f"/dash/{program['id']}/../passwd")
        assert missing.status_code in {404, 422}
