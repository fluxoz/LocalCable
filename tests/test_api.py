"""HTTP schedule + play against the shipped FastAPI app (no test doubles for scan)."""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from localcable.app import AppState, create_app
from localcable.config import AppConfig, PlaybackConfig, ScheduleConfig, UiConfig
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
        playback=PlaybackConfig(mpv_args=[]),
        ui=UiConfig(auto_open_browser=False, bind_host="127.0.0.1", bind_port=8787),
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
