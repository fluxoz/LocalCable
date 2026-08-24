"""FastAPI application: schedule JSON, play API, and the EPG UI."""

from __future__ import annotations

import html as html_lib
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
from localcable.artwork import resolve_artwork
from localcable.config import DEFAULT_BANNER, AppConfig, normalize_inpage_filter, normalize_start_from
from localcable.crt import normalize_filter
from localcable.dash import DashPackager, can_direct_play, codecs_allow_copy, mime_for
from localcable.guide_focus import GUIDE_WINDOW_TITLE, focus_guide_window
from localcable.jellyfin import scan_libraries
from localcable.scan import pad_channels
from localcable.models import GuideSchedule, ScheduledProgram
from localcable.organize import organize_library
from localcable.osd import osd_payload_from_path, osd_payload_from_program, write_osd_state
from localcable.player import MpvController, MpvNotFoundError, PlayResult, ipc_commands_for_play
from localcable.remote import (
    match_channel_number,
    max_channel_digits,
    normalize_action,
    program_airing_on,
    start_evdev_listener,
    step_channel,
)
from localcable.schedule import generate_schedule
from localcable.util import live_offset_seconds

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


class MediaFileResponse(FileResponse):
    """Larger chunks than Starlette's 64 KiB default — fewer RPCs on NFS."""

    chunk_size = 1024 * 1024


class PlayRequest(BaseModel):
    program_id: str | None = None
    path: str | None = Field(default=None, description="Absolute media path under a media root")
    start_seconds: float | None = None
    from_start: bool = False
    filter: str | None = None


class RemoteRequest(BaseModel):
    action: str | None = None
    key: str | None = None
    digit: str | None = None
    channel: int | None = None
    program_id: str | None = None


class SelectRequest(BaseModel):
    program_id: str | None = None
    channel: int | None = None


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
        focus_guide: Callable[..., Any] | None = None,
        artwork_opener: Callable[..., Any] | None = None,
        packager: DashPackager | None = None,
        organize_opener: Callable[..., Any] | None = None,
    ) -> None:
        self.config = config
        self.now_fn = now_fn or _now_local
        self.probe_runner = probe_runner
        self.rng = rng
        self.player = player or MpvController(
            config.socket_path,
            extra_args=list(config.playback.mpv_args),
            extra_env={"LOCALCABLE_OSD_PATH": str(config.osd_path)},
            guide_url=config.public_base_url,
            osd_path=config.osd_path,
            filter_mode=config.playback.filter,
            filter_preset=config.playback.filter_preset,
        )
        self._focus_guide = focus_guide or focus_guide_window
        self._artwork_opener = artwork_opener
        self._organize_opener = organize_opener
        self._mse_by_path: dict[str, bool] = {}
        self._plan_by_path: dict[str, str] = {}
        self.packager = packager or DashPackager(
            config.cache_dir,
            copy_ok=self._path_copy_ok,
            copy_plan_fn=self._path_copy_plan,
            runner=self.probe_runner,
        )
        if hasattr(self.packager, "filter_mode"):
            self.packager.filter_mode = config.playback.filter
            self.packager.filter_preset = config.playback.filter_preset
        self.channels = []
        self.schedule: GuideSchedule | None = None
        self.programs_by_id: dict[str, ScheduledProgram] = {}
        self.now_playing: ScheduledProgram | None = None
        self.selected_program_id: str | None = None
        self.selected_channel: int | None = None
        self._digit_buf = ""
        self._digit_timer: threading.Timer | None = None
        self._remote_stop: threading.Event | None = None
        self._lock = threading.RLock()

    def _path_key(self, path: Path | str) -> str:
        src = Path(path)
        try:
            return str(src.resolve())
        except OSError:
            return str(src)

    def _path_copy_ok(self, path: Path | str) -> bool:
        known = self._mse_by_path.get(self._path_key(path))
        if known is not None:
            return known
        return codecs_allow_copy(path, runner=self.probe_runner)

    def _path_copy_plan(self, path: Path | str) -> str | None:
        return self._plan_by_path.get(self._path_key(path))

    def _remember_codecs(self, channels: list[Any]) -> None:
        mse: dict[str, bool] = {}
        plans: dict[str, str] = {}
        for channel in channels:
            for item in getattr(channel, "media", []) or []:
                key = self._path_key(item.path)
                video = str(getattr(item, "video_codec", None) or "").lower()
                flag = getattr(item, "mse_copy", None)
                if flag:
                    plans[key] = "copy"
                    mse[key] = True
                elif video in {"h264", "avc1"}:
                    plans[key] = "audio"
                    mse[key] = False
                elif getattr(item, "video_codec", None):
                    plans[key] = "xcode"
                    mse[key] = False
                elif flag is False:
                    mse[key] = False
        self._mse_by_path = mse
        self._plan_by_path = plans

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
            if self.config.library.auto_organize:
                try:
                    organize_library(self.config, opener=self._organize_opener)
                except Exception as exc:  # noqa: BLE001
                    log.warning("auto-organize failed: %s", exc)
            channels = scan_libraries(
                self.config.library_roots(),
                default_mode=self.config.schedule.default_mode,
                probe_runner=self.probe_runner,
                cache_dir=self.config.cache_dir,
                fetch_metadata=self.config.library.fetch_metadata,
                opener=self._organize_opener or self._artwork_opener,
                auto_channels=self.config.library.auto_channels,
                lineup_config=self.config.lineup,
            )
            channels = pad_channels(channels, self.config.library.min_channels)
            self.channels = channels
            self._remember_codecs(channels)
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

    def _play_offset(
        self,
        program: ScheduledProgram | None,
        *,
        from_start: bool = False,
        start_seconds: float | None = None,
    ) -> float:
        if from_start:
            return 0.0
        if start_seconds is not None:
            return max(0.0, float(start_seconds))
        if program is None:
            return 0.0
        if normalize_start_from(self.config.playback.start_from) != "live":
            return 0.0
        return live_offset_seconds(
            program.start_time,
            self.now_fn(),
            program.duration_seconds,
            end=program.end_time,
        )

    def play(
        self,
        program_id: str | None = None,
        path: str | None = None,
        *,
        from_start: bool = False,
        start_seconds: float | None = None,
    ) -> PlayResult:
        target: Path | None = None
        payload: dict[str, Any] | None = None
        program: ScheduledProgram | None = None
        with self._lock:
            if program_id:
                if self.schedule is None:
                    self.refresh()
                program = self.programs_by_id.get(program_id)
                if program is None:
                    raise KeyError(program_id)
                target = program.file_path
                payload = osd_payload_from_program(program)
            elif path:
                candidate = Path(path).expanduser()
                if not _is_under(candidate, self.config.media_roots):
                    raise PermissionError(path)
                target = candidate
                payload = osd_payload_from_path(target)
            else:
                raise ValueError("program_id or path is required")
        assert target is not None
        offset = self._play_offset(program, from_start=from_start, start_seconds=start_seconds)
        if payload is not None:
            try:
                write_osd_state(self.config.osd_path, payload)
            except OSError as exc:
                log.warning("could not write OSD state: %s", exc)
        result = self.player.play_file(target, start_seconds=offset)
        with self._lock:
            if program_id:
                self.now_playing = self.programs_by_id.get(program_id)
                if self.now_playing is not None:
                    self.selected_program_id = self.now_playing.id
                    self.selected_channel = self.now_playing.channel_number
        return result

    def stream(
        self,
        program_id: str,
        *,
        from_start: bool = False,
        start_seconds: float | None = None,
        filter: str | None = None,
    ) -> dict[str, Any]:
        """Return an in-page play URL (original file or MPEG-DASH) and join offset."""
        with self._lock:
            if self.schedule is None:
                self.refresh()
            program = self.programs_by_id.get(program_id)
            if program is None:
                raise KeyError(program_id)
            target = program.file_path
            payload = osd_payload_from_program(program)
        if payload is not None:
            try:
                write_osd_state(self.config.osd_path, payload)
            except OSError as exc:
                log.warning("could not write OSD state: %s", exc)
        offset = self._play_offset(program, from_start=from_start, start_seconds=start_seconds)
        with self._lock:
            self.now_playing = self.programs_by_id.get(program_id)
            if self.now_playing is not None:
                self.selected_program_id = self.now_playing.id
                self.selected_channel = self.now_playing.channel_number
        body: dict[str, Any] = {
            "ok": True,
            "program_id": program.id,
            "path": str(target),
            "title": program.title,
            "duration_seconds": program.duration_seconds,
            "channel": program.channel_number,
            "channel_name": program.channel_name,
            "player": self.config.playback.player,
            "offset_seconds": offset,
            "start_from": "beginning" if offset <= 0.05 else "live",
        }
        mode = normalize_filter(
            filter if filter is not None else self.config.playback.filter
        )
        body["filter"] = mode
        if mode == "off" and can_direct_play(
            target,
            mse_copy=getattr(program, "mse_copy", None),
            copy_ok=getattr(self.packager, "_copy_ok", None),
        ):
            body.update(
                {
                    "protocol": "file",
                    "url": f"/media/{program.id}",
                    "manifest": None,
                    "packaged_from_offset": False,
                }
            )
            return body
        pack_offset = offset if offset >= 3 else 0.0
        mpd = self.packager.ensure(
            program.id,
            target,
            wait=20.0,
            start_seconds=pack_offset,
            filter_mode=mode,
            filter_preset=self.config.playback.filter_preset,
        )
        pack_id = mpd.parent.name
        body.update(
            {
                "protocol": "dash",
                "url": self.packager.manifest_url(pack_id),
                "manifest": self.packager.manifest_url(pack_id),
                "mpd": str(mpd),
                "packaged_from_offset": pack_offset >= 3,
            }
        )
        return body

    def preview(self, program_id: str) -> dict[str, Any]:
        """Cheap highlight preview: original file if the browser can play it, else artwork.

        Never starts ffmpeg. NFS Range reads on H.264 MP4 are enough.
        """
        with self._lock:
            if self.schedule is None:
                self.refresh()
            program = self.programs_by_id.get(program_id)
            if program is None:
                raise KeyError(program_id)
            target = program.file_path
        art = f"/art/{program.id}"
        if can_direct_play(
            target,
            mse_copy=getattr(program, "mse_copy", None),
            copy_ok=getattr(self.packager, "_copy_ok", None),
        ):
            return {
                "ok": True,
                "protocol": "file",
                "url": f"/media/{program.id}",
                "art": art,
                "program_id": program.id,
                "title": program.title,
                "duration_seconds": program.duration_seconds,
                "offset_seconds": 0.0,
                "filter": "off",
            }
        return {
            "ok": True,
            "protocol": "art",
            "url": art,
            "art": art,
            "program_id": program.id,
            "title": program.title,
            "duration_seconds": program.duration_seconds,
            "offset_seconds": 0.0,
            "filter": "off",
        }

    def artwork_for_program(self, program_id: str) -> Path | None:
        if self.schedule is None:
            self.refresh()
        program = self.programs_by_id.get(program_id)
        if program is None:
            return None
        path = resolve_artwork(
            video_path=program.file_path,
            title=program.title,
            folder=program.file_path.parent,
            cache_dir=self.config.cache_dir,
            fetch=self.config.artwork.fetch,
            opener=self._artwork_opener,
        )
        if path is None:
            return None
        allowed = list(self.config.media_roots) + [self.config.cache_dir]
        if not _is_under(path, allowed):
            return None
        return path

    def artwork_for_channel(self, number: int) -> Path | None:
        if self.schedule is None:
            self.refresh()
        channel = self._channel_by_number(int(number))
        if channel is None:
            return None
        path = resolve_artwork(
            video_path=None,
            title=channel.name,
            folder=channel.folder_path,
            cache_dir=self.config.cache_dir,
            fetch=self.config.artwork.fetch,
            opener=self._artwork_opener,
        )
        if path is None:
            return None
        allowed = list(self.config.media_roots) + [self.config.cache_dir]
        if not _is_under(path, allowed):
            return None
        return path

    def show_guide(self) -> dict[str, Any]:
        """Raise the guide. Must not send any commands to the player window."""
        return self._focus_guide(title=GUIDE_WINDOW_TITLE, url=self.config.public_base_url + "/")

    def select(self, program_id: str | None = None, channel: int | None = None) -> dict[str, Any]:
        with self._lock:
            if program_id:
                program = self.programs_by_id.get(program_id)
                if program is None:
                    raise KeyError(program_id)
                self.selected_program_id = program.id
                self.selected_channel = program.channel_number
                return {
                    "ok": True,
                    "program_id": program.id,
                    "channel": program.channel_number,
                }
            if channel is not None:
                self.selected_channel = int(channel)
                self.selected_program_id = None
                return {"ok": True, "channel": int(channel)}
            raise ValueError("program_id or channel is required")

    def _channel_numbers(self) -> list[int]:
        if self.schedule is None:
            return []
        return [ch.number for ch in self.schedule.channels]

    def _channel_by_number(self, number: int) -> Any:
        if self.schedule is None:
            return None
        for channel in self.schedule.channels:
            if channel.number == number:
                return channel
        return None

    def play_channel(self, number: int) -> dict[str, Any]:
        schedule = self.refresh()
        channel = self._channel_by_number(int(number))
        if channel is None:
            raise KeyError(number)
        program = program_airing_on(channel, self.now_fn())
        self.selected_channel = channel.number
        if program is None:
            return {
                "ok": True,
                "played": False,
                "channel": channel.number,
                "channel_name": channel.name,
            }
        result = self.play(program_id=program.id)
        return {
            "ok": True,
            "played": True,
            "channel": channel.number,
            "channel_name": channel.name,
            "program_id": program.id,
            "title": program.title,
            **result.to_dict(),
        }

    def _cancel_digit_timer(self) -> None:
        timer = self._digit_timer
        self._digit_timer = None
        if timer is not None:
            timer.cancel()

    def commit_remote_digits(self) -> dict[str, Any]:
        with self._lock:
            buf = self._digit_buf
            self._digit_buf = ""
            self._cancel_digit_timer()
            numbers = self._channel_numbers()
        if not buf:
            return {"ok": True, "played": False, "buffer": ""}
        matched = match_channel_number(numbers, buf)
        if matched is None:
            return {"ok": False, "error": "no channels", "buffer": buf}
        return {"buffer": buf, **self.play_channel(matched)}

    def add_remote_digit(self, digit: str) -> dict[str, Any]:
        if not str(digit).isdigit():
            raise ValueError("digit must be 0-9")
        if self.schedule is None:
            self.refresh()
        with self._lock:
            self._digit_buf += str(digit)[-1]
            buf = self._digit_buf
            width = max_channel_digits(self._channel_numbers())
            self._cancel_digit_timer()
            if len(buf) >= width:
                commit_now = True
            else:
                commit_now = False
                timeout = max(self.config.remote.digit_timeout_ms, 200) / 1000.0
                timer = threading.Timer(timeout, self.commit_remote_digits)
                timer.daemon = True
                self._digit_timer = timer
                timer.start()
        if commit_now:
            return self.commit_remote_digits()
        return {"ok": True, "pending": True, "buffer": buf}

    def handle_remote(
        self,
        action: str | None = None,
        *,
        key: str | None = None,
        digit: str | None = None,
        channel: int | None = None,
        program_id: str | None = None,
    ) -> dict[str, Any]:
        name, parsed_digit = normalize_action(action, key=key, digit=digit)
        if name in {"guide", "back", "exit"}:
            result = self.show_guide()
            return {"ok": True, "action": "guide", **result}
        if name == "digit":
            return {"action": "digit", **self.add_remote_digit(parsed_digit or "0")}
        if name == "tune":
            if channel is None:
                raise ValueError("channel is required")
            return {"action": "tune", **self.play_channel(int(channel))}
        if name in {"channel-up", "channel-down"}:
            self.refresh()
            delta = 1 if name == "channel-up" else -1
            nxt = step_channel(self._channel_numbers(), self.selected_channel, delta)
            if nxt is None:
                return {"ok": False, "action": name, "error": "no channels"}
            return {"action": name, **self.play_channel(nxt)}
        if name in {"ok", "play"}:
            pid = program_id or self.selected_program_id
            if pid:
                result = self.play(program_id=pid)
                return {"ok": True, "action": name, "played": True, **result.to_dict()}
            if self.selected_channel is not None:
                return {"action": name, **self.play_channel(self.selected_channel)}
            return {"ok": False, "action": name, "error": "nothing selected"}
        if name == "info":
            self.player.send_command(["script-message-to", "localcable", "info"])
            return {"ok": True, "action": "info"}
        if name == "select":
            return {"action": "select", **self.select(program_id=program_id, channel=channel)}
        return {"ok": False, "error": name}

    def start_remote_listener(self) -> None:
        device = self.config.remote.device
        if not device:
            return
        self._remote_stop = start_evdev_listener(device, self.handle_remote)

    def stop_remote_listener(self) -> None:
        self._cancel_digit_timer()
        if self._remote_stop is not None:
            self._remote_stop.set()
            self._remote_stop = None


def _index_html(banner: str | None = None) -> str:
    index = STATIC_DIR / "index.html"
    raw = index.read_text(encoding="utf-8")
    text = (banner or "").strip() or DEFAULT_BANNER
    safe = html_lib.escape(text)
    icon = ' class="with-mail"' if text == DEFAULT_BANNER else ""
    return raw.replace(
        '<span id="header-label" class="with-mail">TV Listings</span>',
        f'<span id="header-label"{icon}>{safe}</span>',
        1,
    )


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
        bundle.start_remote_listener()
        try:
            yield
        finally:
            bundle.stop_remote_listener()

    app = FastAPI(title="LocalCable", version=__version__, docs_url="/docs", lifespan=lifespan)
    app.state.bundle = bundle

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "version": __version__}

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse(
            _index_html(bundle.config.ui.banner),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/ui")
    def api_ui() -> JSONResponse:
        return JSONResponse(
            {
                "banner": bundle.config.ui.banner,
                "theme": bundle.config.ui.theme,
                "player": bundle.config.playback.player,
                "start_from": bundle.config.playback.start_from,
                "filter": bundle.config.playback.filter,
                "inpage_filter": bundle.config.playback.inpage_filter,
            },
            headers={"Cache-Control": "no-store"},
        )

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

    @app.get("/art/channel/{number}")
    def art_channel(number: int) -> Response:
        path = bundle.artwork_for_channel(number)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="no artwork")
        mime = LOGO_MIME.get(path.suffix.lower(), "image/jpeg")
        return FileResponse(path, media_type=mime, headers={"Cache-Control": "no-cache"})

    @app.get("/art/{program_id}")
    def art_program(program_id: str) -> Response:
        path = bundle.artwork_for_program(program_id)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="no artwork")
        mime = LOGO_MIME.get(path.suffix.lower(), "image/jpeg")
        return FileResponse(path, media_type=mime, headers={"Cache-Control": "no-cache"})

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
            result = bundle.play(
                program_id=body.program_id,
                path=body.path,
                from_start=body.from_start,
                start_seconds=body.start_seconds,
            )
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

    @app.post("/api/stream")
    def api_stream(body: PlayRequest) -> JSONResponse:
        if not body.program_id:
            raise HTTPException(status_code=400, detail="program_id is required")
        try:
            result = bundle.stream(
                body.program_id,
                from_start=body.from_start,
                start_seconds=body.start_seconds,
                filter=body.filter,
            )
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown program_id") from None
        except FileNotFoundError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from None
        except TimeoutError as exc:
            raise HTTPException(status_code=504, detail=str(exc)) from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except Exception as exc:  # noqa: BLE001
            log.exception("DASH package failed")
            raise HTTPException(status_code=500, detail=str(exc)) from None
        return JSONResponse(result)

    @app.get("/api/preview/{program_id}")
    def api_preview(program_id: str) -> JSONResponse:
        try:
            result = bundle.preview(program_id)
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown program_id") from None
        return JSONResponse(result, headers={"Cache-Control": "no-store"})

    @app.get("/media/{program_id}")
    def media_file(program_id: str) -> Response:
        if bundle.schedule is None:
            bundle.refresh()
        program = bundle.programs_by_id.get(program_id)
        if program is None:
            raise HTTPException(status_code=404, detail="unknown program_id")
        path = program.file_path
        if not path.is_file() or not _is_under(path, list(bundle.config.media_roots)):
            raise HTTPException(status_code=404, detail="media missing")
        mime = LOGO_MIME.get(path.suffix.lower()) or {
            ".mp4": "video/mp4",
            ".m4v": "video/mp4",
            ".mov": "video/quicktime",
            ".webm": "video/webm",
            ".mkv": "video/x-matroska",
        }.get(path.suffix.lower(), "application/octet-stream")
        return MediaFileResponse(
            path,
            media_type=mime,
            headers={"Cache-Control": "private, max-age=3600", "Accept-Ranges": "bytes"},
        )

    @app.api_route("/dash/{program_id}/{name}", methods=["GET", "HEAD"])
    def dash_file(program_id: str, name: str) -> Response:
        path = bundle.packager.resolve_file(program_id, name)
        if path is None or not path.is_file():
            raise HTTPException(status_code=404, detail="unknown dash object")
        cache = "no-cache" if path.suffix.lower() == ".mpd" else "public, max-age=3600"
        return MediaFileResponse(
            path,
            media_type=mime_for(name),
            headers={"Cache-Control": cache, "Accept-Ranges": "bytes"},
        )

    @app.post("/api/show-guide")
    def api_show_guide() -> JSONResponse:
        result = bundle.show_guide()
        return JSONResponse({"ok": True, "url": bundle.config.public_base_url + "/", **result})

    @app.post("/api/select")
    def api_select(body: SelectRequest) -> JSONResponse:
        try:
            result = bundle.select(program_id=body.program_id, channel=body.channel)
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown program_id") from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        return JSONResponse(result)

    @app.post("/api/remote")
    def api_remote(body: RemoteRequest) -> JSONResponse:
        try:
            result = bundle.handle_remote(
                body.action,
                key=body.key,
                digit=body.digit,
                channel=body.channel,
                program_id=body.program_id,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"unknown channel {exc}") from None
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from None
        except MpvNotFoundError as exc:
            return JSONResponse(
                {"ok": False, "error": "mpv not found", "path": exc.path, "argv": exc.argv},
                status_code=503,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("remote action failed")
            raise HTTPException(status_code=500, detail=str(exc)) from None
        return JSONResponse(result)

    return app
