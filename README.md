# LocalCable

LocalCable turns a folder of videos into a living cable-TV guide.

Point it at a media root. **Each immediate subfolder becomes a channel.** Files inside those folders become programs on a rolling timeline. Click a block to select it, then **Watch** (or double-click) to play the file from the beginning in **mpv**.

Everything runs **offline** on Linux. One FastAPI process serves the guide UI and the schedule/play API. Headed mode can open a browser; headless mode serves the same page on localhost.

## Requirements

- Python 3.11+ (3.14 is fine) and [uv](https://docs.astral.sh/uv/) (or pip)
- `ffmpeg` / `ffprobe` (durations and tags)
- `mpv` (playback via IPC; the guide still works without it)

## Install

```bash
cd LocalCable
uv sync --extra dev
```

Or:

```bash
pip install -e ".[dev]"
```

## Media folder layout

```
~/Videos/LocalCableMedia/          ← --media-root
├── 101_CNN/
│   ├── evening_news.mkv
│   ├── documentary.mp4
│   └── playlist.m3u               ← optional ordered list
├── 205_HBO/
│   ├── movie1.mkv
│   └── movie2.mp4
└── Discovery/                     ← unnumbered; auto-numbered after sort
    └── nature.mp4
```

Rules:

- One channel per **immediate subfolder** of the media root.
- Optional leading `NNN_` is the channel number and sort key (`101_CNN` → channel 101, name `CNN`).
- Folders without a number are sorted by name and given unused numbers starting at 1.
- Common video files in each folder become programs (non-recursive).
- **Title** comes from embedded tags when present, otherwise a cleaned filename (`evening_news.mkv` → `Evening News`). **Duration** comes from ffprobe. Missing description/rating never crashes the scan.
- `playlist.m3u` / `playlist.txt` (if present) sets sequential order; otherwise files are sorted by name. Sequential mode **loops** to fill the window.

## Sequential vs random

Set `schedule.default_mode` in `settings.yaml` or pass `--mode sequential|random`.

| Mode | Behavior |
|------|----------|
| **sequential** | Follow `playlist.m3u` / `playlist.txt` when present, else filename order. Loop until the window is full. |
| **random** | Shuffle the library, pack end-to-end by real duration, re-shuffle when exhausted. |

The default window is **now − 6 hours** through **now + 18 hours**. Adjacent blocks abut; there are no commercial gaps. Every airing has a real `start_time` / `end_time` from the file’s duration.

## Config directory and logo

Config lives **outside** the media tree, default `~/.config/localcable/`:

```
~/.config/localcable/
├── settings.yaml
├── provider_logo.png              ← custom cable logo (top-left of the guide)
└── cache/                         ← ffprobe cache
```

Drop a PNG, SVG, or JPEG named `provider_logo.png` (or the filename in `logo:`) into that directory. If the file is missing, LocalCable serves a built-in LocalCable wordmark.

See `example/settings.yaml` for a full template.

## Start commands

Headed (serves the UI and opens a browser):

```bash
uv run localcable --media-root ~/Videos/LocalCableMedia
```

Same thing via the module:

```bash
uv run python -m localcable --media-root ~/Videos/LocalCableMedia
```

Headless (same UI, no browser — use this on a box without a display):

```bash
uv run localcable --headless --media-root ~/Videos/LocalCableMedia
```

With a config file (bind defaults to `127.0.0.1:8787`):

```bash
uv run localcable --config ~/.config/localcable/settings.yaml
uv run localcable --headless --config ~/.config/localcable/settings.yaml --port 8787
```

Then open http://127.0.0.1:8787/ in any local browser.

`--headed` / `--headless` override `ui.auto_open_browser`. `--bind` and `--port` override the YAML. The process never needs a network path beyond loopback.

## Using the guide

- Horizontal/vertical scroll (mouse or trackpad) moves the timeline; the channel column stays put.
- The red **now** line tracks wall-clock time.
- **Click** a program block to select it (detail panel: full title, time range, rating, description; thumbnail space is reserved).
- **Watch** or **double-click** plays that file from the beginning in mpv.

## Tests

```bash
uv run pytest
```
