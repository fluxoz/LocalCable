"""FastAPI application: schedule JSON, play API, and the EPG UI."""

from __future__ import annotations

import logging
import random
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from localcable import __version__
from localcable.config import AppConfig
from localcable.models import GuideSchedule, ScheduledProgram
from localcable.player import MpvController, MpvNotFoundError, PlayResult, ipc_commands_for_play
from localcable.scan import scan_media_root
from localcable.schedule import generate_schedule

log = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
STATIC_DIR = PACKAGE_DIR / "static"
DEFAULT_LOGO = STATIC_DIR / "default_logo.svg"

LOGO_MIME = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


class PlayRequest(BaseModel):
    program_id: str | None = None
    path: str | None = Field(default=None, description="Absolute media path under a media root")


def _now_local() -> datetime:
    return datetime.now().astimezone()


def _is_under(path: Path, roots: list[Path]) -> bool:
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for root in roots:
        try:
            resolved.relative_to(root.resolve())
            return True
        except (ValueError, OSError):
            continue
    return False


class AppState:
    """In-memory scan + schedule + player. Injectable clock / probe / player / rng."""

    def __init__(
        self,
        config: AppConfig,
        *,
        now_fn: Callable[[], datetime] | None = None,
        probe_runner: Callable[..., Any] | None = None,
        player: MpvController | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self.config = config
        self.now_fn = now_fn or _now_local
        self.probe_runner = probe_runner
        self.rng = rng
        self.player = player or MpvController(
            config.socket_path,
            extra_args=list(config.playback.mpv_args),
        )
        self.channels = []
        self.schedule: GuideSchedule | None = None
        self.programs_by_id: dict[str, ScheduledProgram] = {}
        self._lock = threading.RLock()

    def ensure_writable_config_dir(self) -> None:
        try:
            self.config.config_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            log.warning("cannot create config dir %s: %s", self.config.config_dir, exc)

    def refresh(self, force: bool = False) -> GuideSchedule:
        with self._lock:
            now = self.now_fn()
            if (
                not force
                and self.schedule is not None
                and self.schedule.window_start <= now < self.schedule.window_end
            ):
                self.schedule.now = now
                return self.schedule
            channels = []
            for root in self.config.media_roots:
                channels.extend(
                    scan_media_root(
                        root,
                        default_mode=self.config.schedule.default_mode,
                        probe_runner=self.probe_runner,
                        cache_dir=self.config.cache_dir,
                    )
                )
            self.channels = channels
            self.schedule = generate_schedule(
                channels,
                now=now,
                window_hours_before=self.config.schedule.window_hours_before,
                window_hours_after=self.config.schedule.window_hours_after,
                rng=self.rng,
            )
            self.programs_by_id = {
                program.id: program
                for channel in self.schedule.channels
                for program in channel.programs
            }
            log.info(
                "schedule ready: %s channels, %s airings, window %s → %s",
                len(self.schedule.channels),
                sum(len(ch.programs) for ch in self.schedule.channels),
                self.schedule.window_start.isoformat(),
                self.schedule.window_end.isoformat(),
            )
            return self.schedule

    def play(self, program_id: str | None = None, path: str | None = None) -> PlayResult:
        target: Path | None = None
        with self._lock:
            if program_id:
                if self.schedule is None:
                    self.refresh()
                program = self.programs_by_id.get(program_id)
                if program is None:
                    raise KeyError(program_id)
                target = program.file_path
            elif path:
                candidate = Path(path).expanduser()
                if not _is_under(candidate, self.config.media_roots):
                    raise PermissionError(path)
                target = candidate
            else:
                raise ValueError("program_id or path is required")
        assert target is not None
        return self.player.play_file(target)


def _index_html() -> str:
    index = STATIC_DIR / "index.html"
    return index.read_text(encoding="utf-8")


def create_app(
    config: AppConfig | None = None,
    *,
    state: AppState | None = None,
) -> FastAPI:
    if state is None:
        if config is None:
            raise TypeError("create_app requires config= or state=")
        state = AppState(config)
    bundle = state

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        bundle.ensure_writable_config_dir()
        bundle.refresh(force=True)
        yield

    app = FastAPI(title="LocalCable", version=__version__, docs_url="/docs", lifespan=lifespan)
    app.state.bundle = bundle

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(_index_html(), headers={"Cache-Control": "no-store"})

    @app.get("/logo")
    def logo() -> Response:
        path = bundle.config.logo_path
        if path.is_file():
            mime = LOGO_MIME.get(path.suffix.lower(), "application/octet-stream")
            return FileResponse(path, media_type=mime, headers={"Cache-Control": "no-cache"})
        if DEFAULT_LOGO.is_file():
            return FileResponse(
                DEFAULT_LOGO,
                media_type="image/svg+xml",
                headers={"Cache-Control": "no-cache"},
            )
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="280" height="48">'
            '<text x="8" y="34" fill="white" font-size="28" font-family="serif" '
            'font-style="italic">LocalCable</text></svg>'
        )
        return Response(content=svg, media_type="image/svg+xml")

    @app.get("/api/schedule")
    def api_schedule(refresh: bool = False) -> JSONResponse:
        schedule = bundle.refresh(force=refresh)
        return JSONResponse(schedule.to_dict(), headers={"Cache-Control": "no-store"})

    @app.get("/api/channels")
    def api_channels() -> JSONResponse:
        schedule = bundle.refresh()
        body = [
            {"number": ch.number, "name": ch.name, "folder_path": str(ch.folder_path)}
            for ch in schedule.channels
        ]
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    @app.post("/api/play")
    def api_play(body: PlayRequest) -> JSONResponse:
        try:
            result = bundle.play(program_id=body.program_id, path=body.path)
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown program_id") from None
        except PermissionError:
            raise HTTPException(status_code=403, detail="path is not under a media root") from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except MpvNotFoundError as exc:
            return JSONResponse(
                {
                    "ok": False,
                    "error": "mpv not found",
                    "path": exc.path,
                    "argv": exc.argv,
                    "ipc_commands": ipc_commands_for_play(exc.path),
                },
                status_code=503,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("play failed")
            raise HTTPException(status_code=500, detail=str(exc)) from None
        return JSONResponse({"ok": True, **result.to_dict()})

    return app
