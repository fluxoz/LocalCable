"""mpv playback from the beginning, via IPC when a socket is live, else spawn."""

from __future__ import annotations

import json
import logging
import shutil
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)

DEFAULT_BASE_ARGS = ["--idle=yes", "--force-window=yes", "--keep-open=yes"]


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


def ipc_commands_for_play(path: str) -> list[list[Any]]:
    """JSON IPC command list that loads *path* and seeks to the start."""
    return [
        ["loadfile", path, "replace"],
        ["seek", 0, "absolute"],
        ["set_property", "pause", False],
    ]


def build_mpv_argv(
    file_path: str,
    socket_path: str | Path,
    extra_args: list[str] | None = None,
) -> list[str]:
    """Argv that starts mpv on *file_path* from the beginning, with IPC enabled."""
    extra = [str(a) for a in (extra_args or [])]
    return [
        "mpv",
        f"--input-ipc-server={socket_path}",
        *DEFAULT_BASE_ARGS,
        *extra,
        "--",
        str(file_path),
    ]


def _default_popen(argv: list[str], **_kwargs: Any) -> subprocess.Popen:
    return subprocess.Popen(
        argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
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
    ) -> None:
        self.socket_path = Path(socket_path)
        self.extra_args = list(extra_args or [])
        self._popen = popen or _default_popen
        self._which = which or shutil.which
        self._sleep = sleep or time.sleep
        self._proc: Any | None = None
        self._sock: socket.socket | None = None

    def build_argv(self, file_path: str) -> list[str]:
        return build_mpv_argv(file_path, self.socket_path, self.extra_args)

    def play_file(self, file_path: str | Path) -> PlayResult:
        """Play *file_path* from the beginning. Prefers IPC; otherwise spawns mpv."""
        path = str(Path(file_path).expanduser().resolve())
        argv = self.build_argv(path)
        commands = ipc_commands_for_play(path)
        if self._try_ipc(path):
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
        self._proc = self._popen(exec_argv)
        return PlayResult(path=path, argv=exec_argv, method="spawn", ipc_commands=commands)

    def _try_ipc(self, path: str) -> bool:
        try:
            sock = self._connect()
        except OSError:
            self._close_ipc()
            return False
        try:
            for command in ipc_commands_for_play(path):
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
