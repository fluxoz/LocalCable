# LocalCable — Project Plan

**Working Title:** LocalCable  
**Alternatives:** GuideBox, CableFolder, MediaCable  
**Status:** Final v1.1 (groomed from initial concept + full team review)  
**Date:** 2026-08-23  
**Target Platform:** Linux (headed and/or headless), offline-first  

**Visual Target:** The two user-supplied screenshots (classic DirecTV guide and Xfinity TV Listings) define the desired look and feel for the electronic program guide.

---

## 1. Vision & Goals

### Vision Statement

LocalCable turns your local media folders into a living, nostalgic cable television experience.  

You point the app at a directory of folders. Each folder becomes a channel. The media files inside become the programming. LocalCable generates a classic electronic program guide (EPG) that looks and feels like the old DirecTV and Xfinity guides — vertical channel list, horizontal scrolling timeline, program blocks, descriptions, ratings, and a customizable provider logo. Click any program block and it plays instantly.

Everything runs fully offline on Linux. No accounts, no cloud, no required network. Headed mode opens a beautiful guide in the browser (or kiosk). Headless mode runs as a local service that can optionally be reached on the LAN later.

The core emotional goal is **channel surfing nostalgia** with your own content.

### Design Principles

1. **Folder simplicity first** — Channels are just folders. No complex library management required.
2. **Visual fidelity** — The guide should feel immediately familiar to anyone who used cable/satellite guides in the 2000s–2010s.
3. **Offline-first** — Must work with zero network. Network is a pure enhancement.
4. **One codebase for headed + headless** — Web UI served locally solves both modes cleanly.
5. **Real durations, living timeline** — The guide advances with wall-clock time. Programs have authentic start/end times based on actual file lengths.
6. **Graceful degradation** — Missing metadata, short libraries, or odd file formats should never break the experience.

### Differentiation from Existing Projects

| Project          | Focus                                      | How LocalCable Differs                                      |
|------------------|--------------------------------------------|-------------------------------------------------------------|
| ErsatzTV         | Live IPTV channels + HDHomeRun + XMLTV for Plex/Jellyfin | Interactive classic EPG UI is the product, not a backend for other apps. Dead-simple folder model. |
| FieldStation42   | Highly authentic retro TV simulator (RPi/CRT friendly) | Stronger emphasis on the interactive scrolling guide UI matching modern cable screenshots + easier folder-driven setup. |
| leetv            | 24/7 unattended station with schedule files | Interactive click-to-play guide is primary; simpler mental model. |

LocalCable sits in the sweet spot of “beautiful interactive guide + instant play from folders.”

---

## 2. Core Requirements (from original notes)

- Standalone application for headed **and/or** headless Linux.
- UI that scrolls horizontally with channels and content, matching the supplied DirecTV / Xfinity screenshots.
- Channels derived from user-supplied folder names; content inside the folders becomes the programming on that channel.
- Time table / schedule can be generated randomly **or** from a playlist / ordered list.
- Selecting / clicking a program in the guide plays the content.
- Pulls show/movie information (title, description, etc.) from the content to display in the guide style of the screenshots.
- Customizable cable provider logo stored in a user folder.
- Must run fully locally (no network required). Network support is a nice-to-have.

---

## 3. User Stories

**Primary**

- As a user with a media collection organized in folders, I want each folder to appear as a channel so I can browse my library like cable TV.
- As a user, I want a scrolling program guide that looks like classic cable EPGs so the experience feels nostalgic and familiar.
- As a user, I want to click any program block and have it start playing immediately.
- As a user, I want the guide to advance in real time so it feels “live.”
- As a user, I want to drop my own logo into a folder and have it appear as the cable provider branding.
- As a user on a headless Linux box (or HTPC), I want the same experience available via a local web browser.

**Secondary**

- As a user, I want to choose sequential (playlist-style) or random scheduling per channel.
- As a user, I want basic metadata (title + duration at minimum) to appear without any online services.
- As a power user, I want optional `.nfo` sidecars or playlist files for richer control.

---

## 4. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        LocalCable                           │
├──────────────────────┬──────────────────────────────────────┤
│   FastAPI Backend    │           Web Frontend               │
│                      │                                      │
│  • Config & logo     │  • Classic EPG grid (channels × time)│
│  • Folder scanner    │  • Horizontal scroll + “now” line    │
│  • Metadata pipeline │  • Program detail panel              │
│  • Schedule engine   │  • Provider logo header              │
│  • mpv controller    │  • Click → play command              │
│  • REST / WebSocket  │                                      │
└──────────┬───────────┴──────────────────┬───────────────────┘
           │                              │
           ▼                              ▼
    ┌─────────────┐               ┌─────────────────┐
    │  mpv (IPC)  │               │  User Media     │
    │  Playback   │               │  Folders        │
    └─────────────┘               └─────────────────┘
```

**Why this stack?**

- **Python + FastAPI**: Excellent Linux media tooling, typed models, easy headless operation, rapid development.
- **Web frontend (Svelte + Tailwind recommended)**: Perfect recreation of the screenshot look, responsive, one UI for both headed and headless, trivial future LAN exposure.
- **mpv**: Best-in-class Linux player, hardware acceleration, controllable via socket/IPC, works headless or with video window.
- **ffprobe**: Reliable duration + basic tag extraction without external services.

---

## 5. Data Model & Folder Convention

### Recommended Folder Layout

```
~/Videos/LocalCableMedia/          ← user points the app at any media root path(s)
├── 101_CNN/
│   ├── evening_news.mkv
│   ├── documentary.mp4
│   └── playlist.m3u               ← optional ordered list (supported in MVP)
├── 205_HBO/
│   ├── movie1.mkv
│   └── movie2.mp4
├── 287_MILT/
│   └── ...
└── ...

~/.config/localcable/              ← config & branding (or user-specified)
├── settings.yaml
├── provider_logo.png              ← custom cable logo (top-left of guide)
└── cache/                         ← optional metadata / schedule cache
```

**Rules**

- Each **immediate subfolder** of the media root = one channel. The media root itself can be any path the user chooses (multiple roots supported later).
- Folder name becomes the channel name.
- Optional leading number + underscore (e.g. `101_CNN`, `287_MILT`) is parsed for channel number and sort order.
- If no number is present, sequential numbers are auto-assigned after sorting.
- All common video files that mpv can play (mkv, mp4, avi, etc.) inside a channel folder are treated as programs (recursive scan optional later).
- Optional `playlist.m3u` or `playlist.txt` inside a channel folder defines ordered sequential mode and is part of MVP.
- Config directory is separate so media folders stay pure.

### Core Data Objects

```python
Channel:
  id / number: int
  name: str
  folder_path: Path
  logo: optional Path
  programs: list[Program]
  schedule_mode: "sequential" | "random"

Program:
  id: str
  title: str
  description: str | None
  rating: str | None          # e.g. "TV-G", "PG-13"
  genre: str | None
  duration_seconds: float
  file_path: Path
  start_time: datetime        # virtual
  end_time: datetime          # virtual
  thumbnail: optional Path

Schedule:
  window_start: datetime
  window_end: datetime
  channels: list[ChannelSchedule]   # each with ordered Program instances placed in time
```

---

## 6. Scheduling Engine

### Modes

1. **Sequential / Playlist** (MVP)  
   - Follow `playlist.m3u` / `playlist.txt` if present inside the channel folder.  
   - Otherwise sort by filename (or optional natural sort).  
   - Loop the list continuously to fill the schedule window.

2. **Random** (MVP)  
   - Shuffle the available programs.  
   - Pack them end-to-end by real duration.  
   - Re-shuffle when the list is exhausted.

### Generation Rules (MVP)

- Generate a rolling window (default: current time − 6 h to + 18 h, configurable).
- Use **real durations** from ffprobe → variable-width program blocks (more natural for personal libraries of mixed lengths).
- No artificial commercial gaps in v1 (future: optional bumper / interstitial support).
- “Now” line moves with wall-clock time.
- When a channel runs out of unique content it simply loops.
- Schedule is regenerated on startup, on media change detection, or on demand.

### Future Enhancements

- Snap-to-30-min visual grid option for pure cable nostalgia.
- Weighted random, day-parting, marathons, seasonal rules.
- User-supplied bumper / station-ID videos between programs.

---

## 7. Metadata Pipeline

**Priority order (fully offline):**

1. Filename heuristics (strip extensions, common separators, year, episode patterns).
2. Embedded tags via ffprobe / mediainfo.
3. Optional `.nfo` (Kodi-style) or `.json` sidecar next to the media file.
4. Fallback: cleaned filename as title, empty description, “No rating”.

**Extracted fields for guide display**

- Title (required)
- Duration (required)
- Description (optional — shown in detail panel)
- Rating / content advisory (optional)
- Genre / category (optional)
- Year (optional)

Online enrichment (TMDB / TVDB / OMDb) is explicitly **out of scope for core offline path** and may be added later as an optional “enrich when network available” feature with user-supplied API keys.

---

## 8. UI / UX Specification

### Visual Target

The two user-supplied screenshots (classic DirecTV guide and Xfinity TV Listings) are the **explicit visual target** for layout, colors, logo placement, program blocks, and the detail/info panel.

- **DirecTV-style**: Blue header bar with provider logo + “guide”, program detail strip with title, time, rating, short description, and a small poster/thumbnail area.
- **Xfinity-style**: Provider logo, time of day, “TV Listings”, horizontal time slots, colored program blocks, channel numbers + short names on the left.

**Key visual elements to recreate**

- Top-left: customizable provider logo.
- Horizontal time axis that scrolls.
- Vertical channel column (number + short name) that stays fixed while the timeline scrolls.
- Colored rectangular program blocks with truncated title (variable width based on real duration).
- “Now” vertical line that advances in real time.
- Detail / info panel (top or side) showing full title, time range, rating, description, and space for a thumbnail/poster (use generic icon or leave blank in v1; full support later).
- Guide Options / “Channels I Get” style footer or side controls (phase 2).

### Interaction

- Mouse / trackpad: scroll horizontally and vertically, click to select / play.
- Keyboard: arrow keys to move selection, Enter to play, Escape to stop, etc.
- Optional: future remote-control friendly (large hit targets, number entry for channels).

### Responsive / Headed vs Headless

- Primary experience is a full-screen or large browser window.
- Headed mode can auto-launch the system browser or a simple kiosk wrapper.
- Headless mode simply serves the same UI on `localhost` (or configurable bind address).

---

## 9. Playback Integration

- Primary player: **mpv** controlled via IPC socket.
- On program select:
  - Default (MVP): start the selected file from the beginning.
  - Future option: “true live” mode that seeks into the virtual current offset of the program (authentic channel-surfing feel).
- Backend can report now-playing status back to the UI.
- Support for external player fallback (VLC, system default) via config.
- Hardware acceleration preferred; graceful software fallback.

---

## 10. Configuration & Customization

**settings.yaml** (example)

```yaml
media_roots:
  - /home/user/Videos/LocalCableMedia

config_dir: ~/.config/localcable   # or absolute path

schedule:
  window_hours_before: 6
  window_hours_after: 18
  default_mode: sequential        # or random

playback:
  player: mpv
  mpv_args: ["--fullscreen", "--hwdec=auto"]
  start_from: beginning           # or live_offset (future)

ui:
  theme: directv                  # or xfinity, custom
  auto_open_browser: true
  bind_host: 127.0.0.1
  bind_port: 8787

logo: provider_logo.png
```

Provider logo is simply a PNG/SVG placed in the config directory and referenced in the header exactly like the screenshots.

---

## 11. MVP Scope (v0.1) vs Future

### Must-Have for First Usable Release

- [ ] Config directory + custom provider logo support
- [ ] Media root → channel folder scanning (with optional numeric prefixes)
- [ ] Basic metadata extraction (title + duration) via filename + ffprobe
- [ ] Schedule generation (sequential + random modes) using real durations
- [ ] Basic playlist.m3u / playlist.txt support per channel for ordered sequential mode
- [ ] Classic EPG-style web UI matching the visual language of the provided screenshots
- [ ] “Now” indicator that advances with wall-clock time
- [ ] Click program → play via mpv (from beginning)
- [ ] Fully offline operation on Linux
- [ ] Headed (browser) and headless (server-only) modes from the same binary/process

### Nice-to-Have / Phase 2+

- Richer metadata (descriptions, ratings, genres via .nfo)
- “True live” seek into current virtual program position
- Advanced playlist / schedule file features and interstitials
- Channel logos, favorites, “Channels I Get” filter
- Search / jump-to-channel
- Network binding + simple auth for LAN access
- Multiple media roots / library management
- Themes that more precisely mimic different providers
- Bumper / interstitial / station-ID support
- Recording / DVR simulation feel
- Optional online metadata enrichment
- Desktop wrapper (Tauri / Electron) for a more native window
- CEC / remote control support
- Series detection and smarter episode ordering
- Full poster/thumbnail support in the detail panel (v1 reserves space or uses a generic icon)

---

## 12. Implementation Phases / Roadmap

**Phase 0 – Foundations (1–2 days)**  
- Project scaffolding (Python package, FastAPI skeleton, config loading)  
- mpv IPC helper  
- Basic ffprobe wrapper  
- Folder scanner + Channel / Program models

**Phase 1 – Schedule & Core Logic (2–3 days)**  
- Duration extraction  
- Sequential + random packers  
- Rolling schedule window with real start/end times  
- Simple in-memory cache / invalidation on media change

**Phase 2 – Guide UI (3–5 days)**  
- Static HTML/CSS recreation of the screenshot look  
- Svelte (or chosen framework) components for channel column, time header, program blocks, detail panel  
- Horizontal/vertical scrolling + “now” line  
- Click → backend play command  
- Logo injection

**Phase 3 – Polish & Integration (2–3 days)**  
- Auto-open browser / kiosk helpers  
- Keyboard navigation  
- Error handling & graceful fallbacks  
- Basic settings UI or documented YAML  
- README + example media layout

**Phase 4 – Hardening & Packaging**  
- systemd service example for headless  
- AppImage / deb / simple install script  
- Performance (virtualized grid for large channel counts)  
- Logging & diagnostics

**Later Phases**  
- Playlist files, richer metadata, live-offset play, network features, themes, etc.

---

## 13. Technical Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Variable media durations make a clean grid hard | Medium | Use real durations + variable-width blocks; offer optional snap-to-grid later |
| Extreme durations (3+ hour movies or very short clips) produce awkward block widths | Medium | Enforce reasonable min/max visual widths for blocks + rely on horizontal scroll; never clip content |
| Large libraries / many channels → slow grid | Medium | Virtualize the visible window; generate schedule only for the current time window |
| Metadata quality is low for pure filename libraries | Low–Medium | Clear fallbacks + strong .nfo support; never block on missing description |
| mpv IPC reliability across distros | Low | Well-tested library or simple socket protocol; fallback to subprocess launch |
| Headless users expect pure TUI | Low | Web UI on localhost is still usable via SSH tunnel or local browser; optional future TUI / CLI wrapper |
| Scope creep toward full ErsatzTV / FieldStation42 feature set | High | Strict MVP focus on the interactive guide + folder model; document future ideas clearly |

---

## 14. Open Questions / Decisions (Resolved for v1)

| Question | Decision for MVP |
|----------|------------------|
| Click behavior | Play selected program **from the beginning**. “Live offset” is a documented future enhancement. |
| Time slot style | Variable-width blocks based on real durations. Optional 30-min snap later. |
| Channel numbers | Optional leading numeric prefix in folder name; otherwise auto-assign after sort. |
| Frontend | Svelte + Tailwind preferred for lightness; React acceptable. Vanilla + Tailwind also viable. |
| Metadata ambition | Title + duration required; description/rating if easily available offline. |
| Network | Bind to 127.0.0.1 by default; 0.0.0.0 is a one-line config change later. |

---

## 15. Success Criteria for v0.1

A user can:

1. Create a media root with a few numbered or named folders containing video files.
2. Drop a logo into the config directory.
3. Start LocalCable.
4. See a familiar-looking cable guide with their channels and a living timeline.
5. Click a program and watch it play in mpv.
6. Do all of the above with no network connection and on both a desktop (headed) and a headless Linux machine (via browser).

If those six things work reliably and the guide looks recognizably like the supplied screenshots, the first version is a success.

---

## 16. Next Steps

1. Review and lock this PLAN.md with any final wording tweaks.
2. Create the repository skeleton and basic FastAPI + mpv + scanner proof-of-concept.
3. Build a static HTML/CSS mock of the guide UI that matches the screenshots as closely as possible (logo, colors, layout, detail panel).
4. Iterate on schedule generation and play control.
5. Package and document.

---

*This plan synthesizes the original concept notes, the two reference screenshots, and collaborative input from the team (Grok, Benjamin, Lucas, Trader Grok). It prioritizes a coherent, shippable core that delivers the nostalgic cable-guide experience with minimal friction.*
