"""Startup scan must finish even if a request already holds the library lock."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from localcable.app import AppState
from tests.test_api import _config, _fake_player


def _library(tmp_path: Path) -> Path:
    root = tmp_path / "media"
    folder = root / "101_News"
    folder.mkdir(parents=True)
    (folder / "clip.mp4").write_bytes(b"not-a-real-video")
    return root


def _probe_result():
    class Result:
        returncode = 0
        stdout = json.dumps(
            {
                "format": {"duration": "12"},
                "streams": [
                    {"codec_type": "video", "codec_name": "h264"},
                    {"codec_type": "audio", "codec_name": "aac"},
                ],
            }
        )
        stderr = ""

    return Result()


def test_refresh_while_holding_the_lock_does_not_stall_boot(tmp_path: Path):
    root = _library(tmp_path)
    config = _config(tmp_path, root)
    player, _recorded = _fake_player(tmp_path)
    state = AppState(config, player=player, probe_runner=lambda *_a, **_k: _probe_result())
    state._boot_started = True
    state._boot_phase = "scanning"
    state._boot_message = "Scanning media…"

    waiting = threading.Event()
    real_wait = state._boot_done.wait

    def wait(timeout=None):
        waiting.set()
        return real_wait(timeout)

    state._boot_done.wait = wait  # type: ignore[method-assign]

    outcome: dict[str, object] = {}

    def caller() -> None:
        try:
            outcome["result"] = state.preview("missing-program")
        except KeyError:
            outcome["missing"] = True
        except Exception as exc:  # noqa: BLE001 — the test reports it
            outcome["error"] = repr(exc)

    caller_thread = threading.Thread(target=caller, name="preview-during-boot")
    caller_thread.start()
    assert waiting.wait(2), "preview never reached the boot wait"

    def boot() -> None:
        state._boot_thread_id = threading.get_ident()
        try:
            state.refresh(force=True)
            state._boot_phase = "ready"
            state._boot_message = "Ready"
            state._boot_progress = 1.0
        finally:
            state._boot_done.set()

    boot_thread = threading.Thread(target=boot, name="localcable-boot")
    boot_thread.start()
    boot_thread.join(3)
    caller_thread.join(3)
    assert not boot_thread.is_alive(), "boot scan deadlocked"
    assert not caller_thread.is_alive(), "preview deadlocked"
    assert outcome.get("missing") is True, outcome
    assert state.boot_status()["ready"] is True
    assert state.schedule is not None


def test_boot_names_the_file_it_is_probing(tmp_path: Path):
    root = _library(tmp_path)
    config = _config(tmp_path, root)
    player, _recorded = _fake_player(tmp_path)
    messages: list[str] = []

    def runner(*_args, **_kwargs):
        messages.append(state.boot_status()["message"])
        return _probe_result()

    state = AppState(config, player=player, probe_runner=runner)
    state.start_boot()
    assert state._boot_done.wait(5)
    status = state.boot_status()
    assert status["ready"] is True
    assert status["phase"] == "ready"
    assert any("Probing" in message and "clip.mp4" in message for message in messages), messages
