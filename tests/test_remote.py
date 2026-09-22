"""Channel tune / CH+/− / digit buffer — the IR remote action layer."""

from __future__ import annotations

import random
from datetime import datetime
from pathlib import Path

from fastapi.testclient import TestClient

from localcable.app import AppState, create_app
from localcable.remote import match_channel_number, max_channel_digits, normalize_action, step_channel
from localcable.scan import format_channel_number
from tests.test_api import _config, _fake_player


def test_match_channel_number_exact_prefix_closest():
    numbers = [1, 101, 205, 310]
    assert match_channel_number(numbers, "101") == 101
    assert match_channel_number(numbers, "2") == 205
    assert match_channel_number(numbers, "3") == 310
    assert match_channel_number(numbers, "1") == 1
    assert match_channel_number(numbers, "9") == 1
    assert match_channel_number([7, 101], "007") == 7
    assert match_channel_number([7, 101], "00") == 7
    assert format_channel_number(7) == "007"
    assert format_channel_number(100) == "100"
    assert format_channel_number(101) == "101"
    assert max_channel_digits([7]) == 3


def test_step_channel_wraps():
    numbers = [1, 101, 205]
    assert step_channel(numbers, 101, 1) == 205
    assert step_channel(numbers, 205, 1) == 1
    assert step_channel(numbers, 1, -1) == 205
    assert step_channel(numbers, None, 1) == 1


def test_normalize_action_keys_and_digits():
    assert normalize_action(key="ChannelUp") == ("channel-up", None)
    assert normalize_action(key="Escape") == ("guide", None)
    assert normalize_action(key="Enter") == ("ok", None)
    assert normalize_action(key="5") == ("digit", "5")
    assert normalize_action("ch+") == ("channel-up", None)
    assert normalize_action("digit", digit="7") == ("digit", "7")
    assert normalize_action("next") == ("next", None)


def test_remote_channel_up_plays_next_channel(
    tmp_path: Path, media_root: Path, frozen_now: datetime
):
    config = _config(tmp_path, media_root)
    player, recorded = _fake_player(tmp_path)
    state = AppState(config, now_fn=lambda: frozen_now, player=player, rng=random.Random(0))
    state.refresh(force=True)
    first = min(ch.number for ch in state.schedule.channels)
    state.selected_channel = first
    result = state.handle_remote("channel-up")
    assert result["ok"] is True
    assert result["played"] is True
    assert result["channel"] != first
    assert recorded


def test_remote_digits_tune_exact_channel(
    tmp_path: Path, media_root: Path, frozen_now: datetime
):
    config = _config(tmp_path, media_root)
    player, recorded = _fake_player(tmp_path)
    state = AppState(config, now_fn=lambda: frozen_now, player=player, rng=random.Random(0))
    state.refresh(force=True)
    state.handle_remote(key="1")
    state.handle_remote(key="0")
    result = state.handle_remote(key="1")
    assert result["ok"] is True
    assert result.get("channel") == 101
    assert recorded


def test_remote_api_guide_and_select(
    tmp_path: Path, media_root: Path, frozen_now: datetime
):
    config = _config(tmp_path, media_root)
    player, _ = _fake_player(tmp_path)
    focused: list[dict] = []
    state = AppState(
        config,
        now_fn=lambda: frozen_now,
        player=player,
        focus_guide=lambda **k: focused.append(k) or {"method": "test"},
    )
    app = create_app(state=state)
    with TestClient(app) as client:
        body = client.get("/api/schedule").json()
        program = body["channels"][0]["programs"][0]
        sel = client.post("/api/select", json={"program_id": program["id"]})
        assert sel.status_code == 200, sel.text
        guide = client.post("/api/remote", json={"action": "guide"})
        assert guide.status_code == 200
        assert guide.json()["ok"] is True
        assert focused
        ch = client.post("/api/remote", json={"action": "tune", "channel": program["channel_number"]})
        assert ch.status_code == 200
        assert ch.json()["ok"] is True
        assert ch.json()["played"] is True
    state.stop_remote_listener()
