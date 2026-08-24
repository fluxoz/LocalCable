# LocalCable

LocalCable turns a folder of videos into a living cable-TV guide.

Point it at a media library. Classic **channel folders** still work; a Jellyfin parent with **Movies/** and **Shows/** is detected automatically and mixed onto genre cable channels with configurable names. Files become programs on a rolling timeline. Click a block, then **Watch** — playback **joins at the guide’s current time** (a show that started at 4:00 starts 20 minutes in at 4:20). **Start over** on the HUD plays from 0:00. Video plays in the page (H.264 MP4 is served directly; anything else is packaged as MPEG-DASH). Optional **mpv** on the server.

Everything runs **offline** on Linux except optional keyless artwork/metadata lookups. One FastAPI process serves the guide UI, MPEG-DASH streams, and the schedule/play API. Headed mode can open a browser; headless mode serves the same page — including to other computers on your LAN.

## Requirements

- Python 3.11+ (3.14 is fine) and [uv](https://docs.astral.sh/uv/) (or pip)
- `ffmpeg` / `ffprobe` (durations, tags, and MPEG-DASH packaging for the in-page player)
- `mpv` (optional local playback via IPC; the in-page player does not need it)
- Optional: [ntsc-rs](https://ntsc.rs/) CRT/VHS look on mpv. The **ntscrs frei0r plugin is vendored** (Linux x86_64, macOS arm64, Windows x86_64). Other platforms fall back to a 480p scanline/noise stand-in.

## Install

```bash
cd LocalCable
uv sync --extra dev
```

Or:

```bash
pip install -e ".[dev]"
```

## Update

From the clone (stop LocalCable first if it is running):

```bash
cd LocalCable
git pull
uv sync --extra dev
```

Or with pip:

```bash
git pull
pip install -e ".[dev]"
```

Then start LocalCable again as usual. After an update:

- **Quit any leftover mpv window** so it respawns with the new lua script, key bindings, and CRT filter.
- **Hard-refresh the guide** in the browser (or close the tab and reopen http://127.0.0.1:8787/) so CSS/JS is not served from cache.
- **New `settings.yaml` keys are optional** — missing fields keep their defaults. Compare with `example/settings.yaml` if you want the new options (`lineup` names, `playback.start_from`, `playback.player`, libraries, auto-organize).

IR grab support is extra: `uv sync --extra remote` (or `pip install -e ".[dev,remote]"`).

## Media folder layout

LocalCable understands classic channel folders and Jellyfin Movies/Shows trees. You can mix them with `libraries:` in `settings.yaml`. Point `--media-root` at a **parent folder** that contains `Movies/` and `Shows/` (or `TV Shows/`) and LocalCable finds both, then **auto-builds cable channels by genre** — mixing movies and TV episodes on the same channel, with invented network names.

### Channel folders (original)

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

- One channel per **immediate subfolder** of the media root.
- Optional leading `NNN_` is the channel number and sort key (`101_CNN` → channel 101, name `CNN`).
- Folders without a number are sorted by name and given unused numbers starting at 1.
- Empty folders still appear as channels (the row shows “No programming” until you add videos).
- Common video files in each folder become programs (non-recursive).
- `playlist.m3u` / `playlist.txt` (if present) sets sequential order; otherwise files are sorted by name. Sequential mode **loops** to fill the window.

### Jellyfin libraries (recommended)

Same folder rules [Jellyfin documents](https://jellyfin.org/docs/general/server/media/movies/) for Movies and [Shows](https://jellyfin.org/docs/general/server/media/shows/):

```
~/Videos/Shows/                              ← --tv-root
└── The Office (2005)/
    ├── poster.jpg
    └── Season 01/
        ├── The Office (2005) - S01E01 - Pilot.mkv
        └── The Office (2005) - S01E02 - Diversity Day.mkv

~/Videos/Movies/                             ← --movies-root
└── Heat (1995)/
    ├── Heat (1995).mkv
    └── poster.jpg
```

- Drop the parent on LocalCable and it finds `Movies/` + `Shows/` (also `TV Shows/`, `Film/`, `Series/`, …):

```bash
uv run localcable --media-root ~/Videos
```

```
~/Videos/                                 ← --media-root  (auto-detected)
├── Movies/
│   └── Heat (1995)/Heat (1995).mkv
└── Shows/
    └── The Office (2005)/Season 01/…
```

- **Genre lineup (default).** Movies and TV episodes are mixed onto cable channels. Defaults: Horror → **Nightfall**, action → **Thunderbolt**, comedy (including sitcoms) → **Chuckle**, sci-fi → **Starline**, kids/animation → **Toonbox**, drama → **Prime**, unlabeled → **Local 8**. Names are **configurable** in `settings.yaml` (see below). Empty genres are omitted. Genre comes from `.nfo` / embedded tags, then optional TVMaze (TV) and iTunes (movies) when `library.fetch_metadata` is on.
- Episodes of a show stay in `SxxExx` order and are woven with movies on that channel.
- `kind: tv` still means **one channel per series**. `kind: movies` is still one **Movies** channel. Use those when you do not want the mix.
- `featurettes`, `extras`, `trailers`, and similar sidecar folders are skipped.

```yaml
libraries:
  - path: ~/Videos          # Movies/ + Shows/ → Chuckle, Thunderbolt, …
    kind: auto
  - path: ~/Videos/Shows
    kind: tv                # one channel per series
  - path: ~/Videos/Movies
    kind: movies            # single Movies channel
```

### Auto-organize

Opt-in. Parses loose filenames (`Show.Name.S01E02.720p.mkv`, `Movie.Name.1999.BluRay.mkv`), looks up type/title/year/episode on **TVMaze** and the **iTunes Search API** (no API keys), and **moves** files into the Jellyfin layout. Existing files are never overwritten.

```yaml
library:
  auto_channels: true        # genre mix + invented names (default)
  min_channels: 24           # repeat channels so a small library still fills the grid
  auto_organize: true
  inbox: ~/Downloads
  fetch_metadata: true       # TVMaze / iTunes genres when tags/NFO are missing
```

Rename the auto channels (or replace the whole map):

```yaml
lineup:
  Chuckle: Comedy Central
  Thunderbolt: TNT
  Nightfall: Chiller
  Local 8: WXYZ 8
  # or:
  # channels:
  #   - { number: 6, name: Comedy Central, genres: [comedy, sitcom] }
```

Or: `localcable --organize --inbox ~/Downloads --tv-root ~/Videos/Shows --movies-root ~/Videos/Movies`

### Titles, art, duration

- **Title** comes from embedded tags when present, otherwise a cleaned filename (`evening_news.mkv` → `Evening News`). **Duration** comes from ffprobe. Missing description/rating never crashes the scan.
- **Cover art** (guide poster slot) is local first: `evening_news.jpg` next to the file, or `poster.jpg` / `cover.jpg` / `folder.jpg` in the channel folder. Embedded posters inside the video are extracted when present. If nothing local is found and `artwork.fetch` is on (default), LocalCable asks TVMaze then the iTunes Search API — **no API key** — and caches the image. Set `artwork.fetch: false` to stay fully offline.

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
└── cache/                         ← ffprobe cache, DASH packages, downloaded cover art
```

Drop a PNG, SVG, or JPEG named `provider_logo.png` (or the filename in `logo:`) into that directory. If the file is missing, LocalCable serves a built-in LocalCable wordmark.

The top-right header label defaults to **TV Listings**. Set `ui.banner` in `settings.yaml` to any string (for example `guide`, like DirecTV).

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

`--headed` / `--headless` override `ui.auto_open_browser`. `--bind` and `--port` override the YAML. `--player browser|mpv|both` overrides `playback.player`.

Jellyfin-style libraries from the CLI:

```bash
uv run localcable --tv-root ~/Videos/Shows --movies-root ~/Videos/Movies
```

## Watch from another computer on the LAN

The guide embeds **dash.js** (vendored, no CDN). A laptop, phone, or living-room Pi on the same network can open the guide and watch — the server does not need to play audio through its own speakers.

1. Bind every interface, not just loopback:

```bash
uv run localcable --bind 0.0.0.0 --port 8787 --headless --media-root ~/Videos/LocalCableMedia
```

Or in `settings.yaml`:

```yaml
playback:
  player: browser          # in-page DASH (default). mpv | both
ui:
  bind_host: 0.0.0.0
  bind_port: 8787
  auto_open_browser: false
```

2. On the **server**, LocalCable prints a LAN URL, for example `http://192.168.1.40:8787/`. If you need the address yourself:

```bash
hostname -I
# or
ip -4 addr show
```

3. On the **other computer**, open that URL in a browser. Same LAN/Wi-Fi; no extra app.

4. Allow TCP **8787** from your LAN if a firewall is on, e.g. `sudo ufw allow from 192.168.0.0/16 to any port 8787 proto tcp`.

`127.0.0.1` is only the machine running LocalCable. Other devices cannot connect unless you bind `0.0.0.0` (or a specific LAN IP such as `192.168.1.40`).

`playback.player: mpv` still plays on the **server** only — a browser on another computer will not hear it. Use `browser` (default) for LAN watching. `both` starts DASH and mpv together and will double the audio on the server.

## Using the guide

- Horizontal/vertical scroll (mouse or trackpad) moves the timeline; the channel column stays put. **Arrow keys follow the highlight** — the grid scrolls left/right (and the channel row up/down) so the selected program stays on screen.
- **Click** a program block to select it (detail panel: full title, time range, rating, description). The top-right inset loads a **muted video preview** of the highlighted program.
- The header clock and the red **now** line use **this machine’s local time**.
- **Watch** or **double-click** joins the airing **where the timeline says you are** (`playback.start_from: live`, the default). A 4:00 show watched at 4:20 starts 20 minutes in. **Start over** on the HUD (or `start_from: beginning`) plays from 0:00.
- Playback is in-page: browser-friendly **H.264 MP4** is streamed directly (HTTP Range from the original file — this is the fast NFS path). H.264+AAC in other containers (typical Jellyfin `.mkv`) is **stream-copied** into MPEG-DASH without a CPU transcode, including live join-in-progress. HEVC, MPEG-4, AC-3, etc. still transcode (capped at 720p, starting at the join-in point). Repeat airings reuse the cache.
- A cable-style **HUD** (channel, title, seek, volume, CH+/−, Start over, Guide) sits on the video; it auto-hides and is meant to be driven by a remote. Press **i** to pin/unpin it. Set `playback.player: mpv` to use a local mpv window instead.
- **Esc** / **Guide** stay in this tab: they leave fullscreen video and show the grid. The clip keeps playing muted in the inset. They do not open a new tab, quit mpv, or resize the player window.

### CRT / VHS (ntsc-rs)

Analog TV look on playback, modeled after [ntsc.rs](https://ntsc.rs/):

```yaml
playback:
  filter: vhs    # off | ntsc | vhs
  # filter_preset: ~/presets/my-tape.json
```

- **ntsc** — composite broadcast (dot crawl, chroma smear, light snow)
- **vhs** — tape (more noise, scanlines, tracking, chroma loss)

LocalCable ships the [ntscrs frei0r plugin](https://github.com/rectalogic/ntsc) (the [ntsc-rs](https://ntsc.rs/) engine) under `src/localcable/vendor/ntscrs/`. **mpv** and the **in-page player** both use it at 480p with a shipped preset — no extra install on Linux x86_64, macOS Apple Silicon, or Windows x86_64.

- Config: `playback.filter: off | ntsc | vhs` is the default look. HUD **CRT** checkbox toggles it.
- **In-page CRT is CSS by default** (`playback.inpage_filter: css`) so Watch can keep HTTP Range reads from NFS/disk. Authentic ntsc-rs through ffmpeg (`inpage_filter: ntscrs`) is optional and **CPU-heavy** — it is not limited by NFS speed.
- Highlight preview never starts ffmpeg: H.264 MP4 plays in the inset; other files show cover art.

### Slow playback / NFS

If the library lives on NFS, the disk is almost never the bottleneck. Sequential Range reads of an H.264 MP4 are cheap; **CPU transcode** (and a too-short wait that used to fall back from stream-copy to libx264) is what feels like “NFS is slow.”

- Keep files as **H.264 + AAC in `.mp4` / `.m4v`** when you can — the browser reads them with HTTP Range and never waits on ffmpeg.
- MKV is fine when the **video** is H.264: LocalCable remuxes the video into DASH (copy). AAC audio is copied too; AC-3/DTS is re-encoded to AAC (cheap compared with a video transcode). It no longer re-encodes video just because you joined 20 minutes in.
- Leave `playback.inpage_filter: css` (the default). `ntscrs` encodes every frame through frei0r and will crawl on any storage.
- Codec info is stored from the library scan so the guide does not ffprobe the NFS file on every highlight.
- A first start after this update may re-read headers for files whose probe cache has no codec fields; after that, `~/.config/localcable/cache/probe.json` keeps them.
- mpv still uses the vendored ntscrs plugin when `filter` is ntsc/vhs.
- Set `FREI0R_PATH` if you want a different plugin build. Hardware decode is turned off for mpv while the filter is on. Quit any leftover mpv window after changing the YAML default.

## Remote control

LocalCable is meant to be driven from an IR remote. A remote that Linux already exposes as a keyboard (the usual `ir-keytable` / `rc-core` setup) works with no extra daemon — those keys hit the on-screen HUD while watching:

| Button | Guide | While watching (in-page HUD / mpv) |
| --- | --- | --- |
| Arrows | Move the highlight (grid follows) | Left/right seek, up/down volume |
| OK / Enter / Space | Watch the highlighted program | Play / pause |
| Esc / Back / Exit / Guide | Stay on / return to the guide | Return to the guide (video keeps going) |
| CH+ / CH− / PageUp / PageDown | Jump to the next/previous channel | Surf and play that channel |
| 0–9 | Type a channel number (cable-style timeout) | Same, then play |
| i / Info | Show the video info overlay | Pin / unpin the HUD (mpv: toggle OSD) |

To grab a dedicated IR event node instead of using keyboard emulation, install `evdev` and set `remote.device` in `settings.yaml`.

## Tests

```bash
uv run pytest
```
