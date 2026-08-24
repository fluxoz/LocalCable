"""mpv playback from the beginning, via IPC when a socket is live, else spawn."""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from localcable.crt import find_frei0r_ntscrs, mpv_filter_args, normalize_filter

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
MPV_SCRIPT = PACKAGE_DIR / "mpv" / "localcable.lua"
SHOW_GUIDE_HELPER = PACKAGE_DIR / "mpv" / "show_guide.py"
DEFAULT_BASE_ARGS = [
    "--idle=yes",
    "--force-window=yes",
    "--keep-open=yes",
    "--osc=no",
    "--osd-bar=no",
]
DEFAULT_GUIDE_URL = "http://127.0.0.1:8787"


def default_guide_env(
    guide_url: str | None = None,
    osd_path: str | Path | None = None,
) -> dict[str, str]:
    """Env so the mpv lua script can raise the guide without changing the player."""
    env = {
        "LOCALCABLE_GUIDE_URL": (guide_url or DEFAULT_GUIDE_URL).rstrip("/"),
        "LOCALCABLE_SHOW_GUIDE": str(SHOW_GUIDE_HELPER),
        "LOCALCABLE_PYTHON": sys.executable,
    }
    if osd_path:
        env["LOCALCABLE_OSD_PATH"] = str(osd_path)
    return env


def _script_args(extra: list[str]) -> list[str]:
    if not MPV_SCRIPT.is_file():
        return []
    marker = str(MPV_SCRIPT)
    for arg in extra:
        if arg == f"--script={marker}" or arg.endswith("localcable.lua"):
            return []
    return [f"--script={marker}"]


class MpvError(Exception):
    """Base error for mpv control."""


class MpvNotFoundError(MpvError):
    def __init__(self, message: str, *, argv: list[str], path: str):
        super().__init__(message)
        self.argv = argv
        self.path = path


@dataclass
class PlayResult:
    path: str
    argv: list[str]
    method: str
    ipc_commands: list[list[Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "argv": self.argv,
            "method": self.method,
            "ipc_commands": self.ipc_commands,
        }


def ipc_commands_for_play(path: str, start_seconds: float = 0.0) -> list[list[Any]]:
    """JSON IPC command list that loads *path* and seeks to *start_seconds*."""
    seek = max(0.0, float(start_seconds or 0.0))
    return [
        ["loadfile", path, "replace"],
        ["seek", seek, "absolute"],
        ["set_property", "pause", False],
    ]


def build_mpv_argv(
    file_path: str,
    socket_path: str | Path,
    extra_args: list[str] | None = None,
    *,
    filter_mode: str = "off",
    filter_preset: str | Path | None = None,
    start_seconds: float = 0.0,
) -> list[str]:
    """Argv that starts mpv on *file_path*, with IPC enabled."""
    extra = [str(a) for a in (extra_args or [])]
    mode = normalize_filter(filter_mode)
    filt = mpv_filter_args(mode, explicit_preset=filter_preset)
    start = max(0.0, float(start_seconds or 0.0))
    start_args = [f"--start={start:.3f}"] if start > 0.05 else []
    return [
        "mpv",
        f"--input-ipc-server={socket_path}",
        *DEFAULT_BASE_ARGS,
        *_script_args(extra),
        *extra,
        *filt,
        *start_args,
        "--",
        str(file_path),
    ]


def _default_popen(argv: list[str], **kwargs: Any) -> subprocess.Popen:
    return subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        env=kwargs.get("env"),
    )


class MpvController:
    """Launch / drive mpv. Injectable ``popen``, ``which``, and ``sleep`` for tests."""

    def __init__(
        self,
        socket_path: Path | str,
        extra_args: list[str] | None = None,
        *,
        popen: Callable[..., Any] | None = None,
        which: Callable[[str], str | None] | None = None,
        sleep: Callable[[float], None] | None = None,
        extra_env: dict[str, str] | None = None,
        guide_url: str | None = None,
        osd_path: str | Path | None = None,
        filter_mode: str = "off",
        filter_preset: str | Path | None = None,
    ) -> None:
        self.socket_path = Path(socket_path)
        self.extra_args = list(extra_args or [])
        self.filter_mode = normalize_filter(filter_mode)
        self.filter_preset = filter_preset
        self._popen = popen or _default_popen
        self._which = which or shutil.which
        self._sleep = sleep or time.sleep
        self._proc: Any | None = None
        self._sock: socket.socket | None = None
        env = default_guide_env(guide_url, osd_path)
        if extra_env:
            env.update(extra_env)
        plugin = find_frei0r_ntscrs(env)
        if plugin is not None:
            folder = str(plugin.parent)
            existing = env.get("FREI0R_PATH", "")
            if folder not in existing.split(":"):
                env["FREI0R_PATH"] = f"{folder}:{existing}" if existing else folder
        self.extra_env = env

    def _child_env(self) -> dict[str, str]:
        merged = os.environ.copy()
        merged.update(self.extra_env)
        return merged

    def build_argv(self, file_path: str, start_seconds: float = 0.0) -> list[str]:
        return build_mpv_argv(
            file_path,
            self.socket_path,
            self.extra_args,
            filter_mode=self.filter_mode,
            filter_preset=self.filter_preset,
            start_seconds=start_seconds,
        )

    def play_file(self, file_path: str | Path, start_seconds: float = 0.0) -> PlayResult:
        """Play *file_path* from *start_seconds*. Prefers IPC; otherwise spawns mpv."""
        path = str(Path(file_path).expanduser().resolve())
        argv = self.build_argv(path, start_seconds)
        commands = ipc_commands_for_play(path, start_seconds)
        if self._try_ipc(path, start_seconds):
            return PlayResult(path=path, argv=argv, method="ipc", ipc_commands=commands)

        binary = self._which("mpv")
        if not binary:
            raise MpvNotFoundError(
                "mpv not found on PATH",
                argv=argv,
                path=path,
            )
        self._cleanup_socket()
        exec_argv = [binary, *argv[1:]]
        log.info("starting mpv: %s", " ".join(exec_argv))
        self._proc = self._popen(exec_argv, env=self._child_env())
        return PlayResult(path=path, argv=exec_argv, method="spawn", ipc_commands=commands)

    def send_command(self, command: list[Any]) -> bool:
        """Best-effort IPC command (OSD / script-message). Never required for play."""
        try:
            sock = self._sock if self._sock is not None else self._connect()
            self._send(sock, command)
            self._sock = sock
            return True
        except OSError:
            self._close_ipc()
            return False

    def _try_ipc(self, path: str, start_seconds: float = 0.0) -> bool:
        try:
            sock = self._connect()
        except OSError:
            self._close_ipc()
            return False
        try:
            for command in ipc_commands_for_play(path, start_seconds):
                self._send(sock, command)
        except OSError:
            self._close_ipc()
            return False
        self._sock = sock
        return True

    def _connect(self) -> socket.socket:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(1.0)
        sock.connect(str(self.socket_path))
        return sock

    def _send(self, sock: socket.socket, command: list[Any]) -> dict[str, Any]:
        payload = json.dumps({"command": command}) + "\n"
        sock.sendall(payload.encode("utf-8"))
        buf = b""
        while b"\n" not in buf:
            chunk = sock.recv(4096)
            if not chunk:
                raise ConnectionError("mpv IPC closed")
            buf += chunk
        line, _rest = buf.split(b"\n", 1)
        if not line:
            return {}
        try:
            return json.loads(line.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _cleanup_socket(self) -> None:
        self._close_ipc()
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except OSError:
            pass

    def _close_ipc(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None


def play_from_beginning(
    file_path: str | Path,
    *,
    socket_path: Path | str,
    extra_args: list[str] | None = None,
    controller: MpvController | None = None,
    **kwargs: Any,
) -> PlayResult:
    """Shipped play entry: play *file_path* from the start via mpv."""
    player = controller or MpvController(socket_path, extra_args=extra_args, **kwargs)
    return player.play_file(file_path)
