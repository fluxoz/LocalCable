"""CLI entry: ``localcable`` / ``python -m localcable``."""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

from localcable import __version__
from localcable.app import AppState, create_app
from localcable.config import DEFAULT_BIND_HOST, DEFAULT_BIND_PORT, load_config
from localcable.util import lan_ipv4_addresses

log = logging.getLogger("localcable")

DESCRIPTION = """\
LocalCable turns a media library into a cable-style guide. Channel folders,
Jellyfin Shows/Movies trees, and an in-page dash.js player (plus optional mpv).
"""

EPILOG = """\
examples:
  localcable --media-root ~/Videos/LocalCableMedia
  localcable --headless --bind 0.0.0.0 --media-root ~/Videos/LocalCableMedia
  localcable --tv-root ~/Videos/Shows --movies-root ~/Videos/Movies
  localcable --headless --config ~/.config/localcable/settings.yaml
  python -m localcable --headed --port 8787 --media-root /media/tv
  localcable transcode --rungs 1080,720
  localcable transcode --fetch-ffmpeg --hw auto --dry-run
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="localcable",
        description=DESCRIPTION,
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", "-c", help="Path to settings.yaml or a config directory")
    parser.add_argument(
        "--media-root",
        action="append",
        default=[],
        metavar="PATH",
        help="Library root (repeatable). Channel folders, or a parent with Movies/ and Shows/.",
    )
    parser.add_argument(
        "--tv-root",
        action="append",
        default=[],
        metavar="PATH",
        help="Jellyfin TV/Shows library root (repeatable).",
    )
    parser.add_argument(
        "--movies-root",
        action="append",
        default=[],
        metavar="PATH",
        help="Jellyfin Movies library root (repeatable).",
    )
    parser.add_argument(
        "--player",
        choices=["browser", "mpv", "both"],
        default=None,
        help="Where Watch plays: in-page DASH, local mpv, or both (default browser).",
    )
    parser.add_argument(
        "--organize",
        action="store_true",
        help="Auto-organize loose/inbox files into the Jellyfin folder layout.",
    )
    parser.add_argument(
        "--inbox",
        default=None,
        metavar="PATH",
        help="Folder of loose downloads to organize (implies --organize).",
    )
    parser.add_argument("--bind", default=None, help=f"Bind host (default {DEFAULT_BIND_HOST})")
    parser.add_argument(
        "--port",
        "-p",
        type=int,
        default=None,
        help=f"Bind port (default {DEFAULT_BIND_PORT})",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--headed", action="store_true", help="Auto-open a browser (default)")
    mode.add_argument(
        "--headless",
        action="store_true",
        help="Serve the same UI without opening a browser",
    )
    parser.add_argument("--no-browser", action="store_true", help="Do not auto-open a browser")
    parser.add_argument(
        "--mode",
        choices=["sequential", "random"],
        default=None,
        help="Schedule mode (overrides settings.yaml)",
    )
    parser.add_argument("--version", action="version", version=f"LocalCable {__version__}")
    return parser


def build_transcode_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="localcable transcode",
        description=(
            "One-time in-place rewrite of the library to browser-native H.264 + AAC MP4. "
            "Assumes originals are backed up elsewhere. Uses a vendored/static ffmpeg when "
            "present, with GPU encode (nvenc/qsv/amf/vaapi/videotoolbox) if it works."
        ),
    )
    parser.add_argument("--config", "-c", help="Path to settings.yaml or a config directory")
    parser.add_argument(
        "--media-root",
        action="append",
        default=[],
        metavar="PATH",
        help="Library root (repeatable).",
    )
    parser.add_argument("--tv-root", action="append", default=[], metavar="PATH")
    parser.add_argument("--movies-root", action="append", default=[], metavar="PATH")
    parser.add_argument(
        "--rungs",
        default=None,
        help="Comma-separated heights: native,2160,1440,1080,720,480 (never upscales).",
    )
    parser.add_argument(
        "--codec",
        choices=["h264", "hevc"],
        default=None,
        help="h264 (default, Chrome/Firefox native) or hevc (Safari/mpv, smaller).",
    )
    parser.add_argument(
        "--hw",
        default=None,
        help="auto, cpu, nvenc, qsv, amf, vaapi, videotoolbox",
    )
    parser.add_argument(
        "--keep-original",
        action="store_true",
        help="Leave source files in place (default is replace after success).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan only; do not write files")
    parser.add_argument(
        "--fetch-ffmpeg",
        action="store_true",
        help="Download a portable static ffmpeg into the vendor dir first.",
    )
    parser.add_argument("--ffmpeg", default=None, help="Explicit ffmpeg binary")
    return parser


def transcode_main(argv: list[str]) -> int:
    from localcable.transcode import parse_rungs, transcode_library

    parser = build_transcode_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(args.config, args=args)
    roots = list(config.media_roots)
    if not roots:
        parser.error("no media library configured")
    xc = config.library.transcode
    rungs = parse_rungs(args.rungs if args.rungs is not None else xc.rungs)
    codec = args.codec or xc.codec
    hw = args.hw or xc.hw
    keep = True if args.keep_original else xc.keep_original
    print(f"LocalCable v{__version__}  transcode-in-place")
    print(f"Media:  {', '.join(str(p) for p in roots)}")
    print(f"Rungs:  {', '.join(rungs)}")
    print(f"Codec:  {codec}  hw={hw}  keep_original={keep}")
    if args.dry_run:
        print("Mode:   dry-run")
    try:
        result = transcode_library(
            roots,
            rungs=rungs,
            codec=codec,
            hw=hw,
            keep_original=keep,
            dry_run=args.dry_run,
            fetch=args.fetch_ffmpeg,
            ffmpeg=args.ffmpeg,
        )
    except FileNotFoundError as exc:
        print(exc)
        return 2
    print(
        f"Done: planned={result.planned} encoded={result.encoded} "
        f"skipped={result.skipped} failed={result.failed} removed={result.removed}"
    )
    for err in result.errors:
        print(f"  error: {err}")
    return 1 if result.failed else 0


def public_url(host: str, port: int) -> str:
    shown = "127.0.0.1" if host in {"0.0.0.0", "::", "[::]"} else host
    return f"http://{shown}:{port}/"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "transcode":
        return transcode_main(argv[1:])
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(args.config, args=args)
    if not config.media_roots and not config.libraries:
        parser.error(
            "no media library configured. Pass --media-root / --tv-root / --movies-root "
            "or set media_roots / libraries in settings.yaml"
        )
    missing = [p for p in config.media_roots if not Path(p).is_dir()]
    if missing:
        log.warning("media root does not exist yet: %s", ", ".join(str(p) for p in missing))

    state = AppState(config)
    app = create_app(state=state)
    host = config.ui.bind_host
    port = int(config.ui.bind_port)
    url = public_url(host, port)
    lan = lan_ipv4_addresses() if host in {"0.0.0.0", "::", "[::]"} else []

    print(f"LocalCable v{__version__}")
    print(f"Guide:  {url}")
    if lan:
        for ip in lan:
            print(f"LAN:    http://{ip}:{port}/")
    elif host in {"127.0.0.1", "localhost", "::1"}:
        print("LAN:    (not reachable — bind 127.0.0.1). Use --bind 0.0.0.0 to share on the LAN")
    print(f"Player: {config.playback.player}")
    print(f"Media:  {', '.join(str(p) for p in config.media_roots)}")
    print(f"Config: {config.config_dir}")
    print(f"Mode:   {config.schedule.default_mode}  ({'headed' if config.ui.auto_open_browser else 'headless'})")

    if config.ui.auto_open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()

    try:
        uvicorn.run(app, host=host, port=port, log_level="info")
    except KeyboardInterrupt:
        print("\nLocalCable stopped.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
