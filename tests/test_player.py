"""mpv controller: argv / IPC against a fake player, never requiring a video window."""

from __future__ import annotations

import json
import socket
import threading
from pathlib import Path

import pytest

from localcable.player import (
    MPV_SCRIPT,
    SHOW_GUIDE_HELPER,
    MpvController,
    MpvNotFoundError,
    build_mpv_argv,
    ipc_commands_for_play,
    play_from_beginning,
)


def test_build_argv_plays_path_from_beginning(tmp_path: Path):
    media = tmp_path / "evening_news.mp4"
    media.write_bytes(b"not-a-real-video")
    sock = tmp_path / "mpv.sock"
    argv = build_mpv_argv(str(media), sock, extra_args=["--hwdec=auto"])
    assert argv[0] == "mpv"
    assert argv[-1] == str(media)
    assert "--" in argv
    assert any(a.startswith("--input-ipc-server=") for a in argv)
    assert any(a == f"--script={MPV_SCRIPT}" for a in argv)
    assert "--osc=no" in argv
    assert "--osd-bar=no" in argv
    for arg in argv:
        if arg.startswith("--start="):
            assert arg in {"--start=0", "--start=0%"}


def test_ipc_commands_loadfile_and_seek_zero():
    path = "/media/101_CNN/evening_news.mp4"
    commands = ipc_commands_for_play(path)
    assert ["loadfile", path, "replace"] in commands
    assert ["seek", 0, "absolute"] in commands
    live = ipc_commands_for_play(path, start_seconds=20)
    assert ["seek", 20, "absolute"] in live


def test_play_from_beginning_spawn_argv(tmp_path: Path):
    media = tmp_path / "show.mp4"
    media.write_bytes(b"x")
    recorded: list[list[str]] = []

    class Proc:
        def poll(self):
            return None

    def popen(argv, **_kwargs):
        recorded.append(list(argv))
        return Proc()

    result = play_from_beginning(
        media,
        socket_path=tmp_path / "mpv.sock",
        extra_args=["--fullscreen"],
        popen=popen,
        which=lambda _name: "/usr/bin/mpv",
    )
    assert result.method == "spawn"
    assert recorded
    argv = recorded[0]
    assert argv[0].endswith("mpv")
    assert argv[-1] == str(media.resolve())
    assert "--fullscreen" in argv
    assert any(a == f"--script={MPV_SCRIPT}" for a in argv)
    assert result.path == str(media.resolve())
    assert ["loadfile", result.path, "replace"] in result.ipc_commands
    assert ["seek", 0, "absolute"] in result.ipc_commands


def test_play_ipc_against_fake_socket(tmp_path: Path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"x")
    sock_path = tmp_path / "mpv.sock"
    received: list[dict] = []
    ready = threading.Event()

    def server() -> None:
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(sock_path))
        srv.listen(1)
        ready.set()
        conn, _ = srv.accept()
        conn.settimeout(2)
        buf = b""
        try:
            while len(received) < 3:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buf += chunk
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line:
                        continue
                    received.append(json.loads(line.decode("utf-8")))
                    conn.sendall(b'{"data":null,"error":"success"}\n')
        finally:
            conn.close()
            srv.close()

    thread = threading.Thread(target=server, daemon=True)
    thread.start()
    assert ready.wait(2)

    def boom(*_a, **_k):
        raise AssertionError("mpv should not be spawned when IPC works")

    player = MpvController(
        sock_path,
        extra_args=[],
        popen=boom,
        which=lambda _n: "/usr/bin/mpv",
    )
    result = player.play_file(media)
    thread.join(2)
    assert result.method == "ipc"
    commands = [row["command"] for row in received]
    target = str(media.resolve())
    assert ["loadfile", target, "replace"] in commands
    assert ["seek", 0, "absolute"] in commands


def test_mpv_missing_still_exposes_argv(tmp_path: Path):
    media = tmp_path / "show.mp4"
    media.write_bytes(b"x")

    def boom(*_a, **_k):
        raise AssertionError("should not spawn when mpv is missing")

    player = MpvController(
        tmp_path / "mpv.sock",
        extra_args=[],
        popen=boom,
        which=lambda _n: None,
    )
    with pytest.raises(MpvNotFoundError) as caught:
        player.play_file(media)
    assert caught.value.path == str(media.resolve())
    assert caught.value.argv[-1] == str(media.resolve())
    assert caught.value.argv[0] == "mpv"


def test_spawn_passes_guide_env_and_does_not_alter_window(tmp_path: Path):
    media = tmp_path / "show.mp4"
    media.write_bytes(b"x")
    recorded_env: list[dict] = []

    class Proc:
        def poll(self):
            return None

    def popen(argv, **kwargs):
        recorded_env.append(kwargs.get("env") or {})
        return Proc()

    player = MpvController(
        tmp_path / "mpv.sock",
        extra_args=["--fullscreen"],
        popen=popen,
        which=lambda _n: "/usr/bin/mpv",
        guide_url="http://127.0.0.1:9191",
    )
    player.play_file(media)
    assert recorded_env
    env = recorded_env[0]
    assert env["LOCALCABLE_GUIDE_URL"] == "http://127.0.0.1:9191"
    assert env["LOCALCABLE_SHOW_GUIDE"] == str(SHOW_GUIDE_HELPER)
    assert Path(env["LOCALCABLE_SHOW_GUIDE"]).is_file()
    assert MPV_SCRIPT.is_file()
    lua = MPV_SCRIPT.read_text(encoding="utf-8")
    assert "localcable-show-guide" in lua
    assert '"esc"' in lua
    assert "commandv" in lua and '"run"' in lua
    assert "create_osd_overlay" in lua
    assert "localcable-info" in lua
    assert "CHANNEL_UP" in lua
    esc_fn = lua.split("local function show_guide")[1].split("local function aesc")[0]
    assert "quit" not in esc_fn
    assert "fullscreen" not in esc_fn
