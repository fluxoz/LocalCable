from __future__ import annotations

from pathlib import Path

from datetime import datetime, timezone

from localcable.config import LibraryRoot, LineupConfig
from localcable.jellyfin import scan_libraries
from localcable.lineup import (
    FALLBACK_SLOT,
    configured_lineup,
    detect_library_kind,
    find_movie_dir,
    find_tv_dir,
    mix_playlist,
    pick_slot,
)
from localcable.util import live_offset_seconds
from localcable.models import MediaFile


def _probe(path, **_kwargs):
    return MediaFile(path=Path(path).resolve(), title=Path(path).stem, duration_seconds=60.0)


def _touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not-a-real-video")
    return path


def test_pick_slot_maps_genres_to_invented_channels():
    assert pick_slot("Horror").name == "Nightfall"
    assert pick_slot("Action, Crime").name == "Thunderbolt"
    assert pick_slot("Comedy").name == "Chuckle"
    assert pick_slot("Science-Fiction").name == "Starline"
    assert pick_slot("Kids / Animation").name == "Toonbox"
    assert pick_slot("Drama").name == "Prime"
    assert pick_slot(None) is FALLBACK_SLOT
    assert pick_slot("").name == "Local 8"


def test_configured_lineup_renames_slots():
    cfg = LineupConfig(names={"Chuckle": "Comedy Central", "Thunderbolt": "TNT"}, fallback="WXYZ 8")
    slots, fallback = configured_lineup(cfg)
    by_keyword = {slot.keywords[0]: slot.name for slot in slots if slot.keywords}
    assert by_keyword["comedy"] == "Comedy Central"
    assert by_keyword["action"] == "TNT"
    assert fallback.name == "WXYZ 8"
    chuck = pick_slot("Comedy", slots=slots, fallback=fallback)
    assert chuck.name == "Comedy Central"


def test_live_offset_joins_in_progress():
    start = datetime(2026, 8, 23, 16, 0, tzinfo=timezone.utc)
    now = datetime(2026, 8, 23, 16, 20, tzinfo=timezone.utc)
    assert live_offset_seconds(start, now, 3600) == 20 * 60
    assert live_offset_seconds(start, start, 3600) == 0
    assert live_offset_seconds(start, now, 60) == 0


def test_detect_top_level_movies_and_tv_shows(tmp_path: Path):
    (tmp_path / "Movies").mkdir()
    (tmp_path / "TV Shows").mkdir()
    (tmp_path / "extras").mkdir()
    assert detect_library_kind(tmp_path) == "auto"
    assert find_movie_dir(tmp_path).name == "Movies"
    assert find_tv_dir(tmp_path).name == "TV Shows"


def test_detect_classic_channel_folders(tmp_path: Path):
    (tmp_path / "101_CNN").mkdir()
    (tmp_path / "HBO").mkdir()
    assert detect_library_kind(tmp_path) == "channels"


def test_mix_playlist_keeps_episode_order():
    show = Path("/shows/Office/Season 01")
    items = [
        MediaFile(path=show / "S01E01.mkv", title="E1", duration_seconds=1),
        MediaFile(path=show / "S01E02.mkv", title="E2", duration_seconds=1),
        MediaFile(path=Path("/movies/Heat/Heat.mkv"), title="Heat", duration_seconds=1),
    ]
    mixed = [p.name for p in mix_playlist(items)]
    assert mixed.index("S01E01.mkv") < mixed.index("S01E02.mkv")
    assert "Heat.mkv" in mixed


def test_auto_lineup_mixes_tv_and_movies_by_genre(tmp_path: Path):
    movies = tmp_path / "Movies"
    shows = tmp_path / "Shows"
    heat = _touch(movies / "Heat (1995)" / "Heat (1995).mkv")
    (heat.parent / "movie.nfo").write_text("<movie><genre>Action</genre></movie>\n", encoding="utf-8")
    office = _touch(
        shows / "The Office (2005)" / "Season 01" / "The Office (2005) - S01E01 - Pilot.mkv"
    )
    (office.parent.parent / "tvshow.nfo").write_text(
        "<tvshow><genre>Comedy</genre></tvshow>\n",
        encoding="utf-8",
    )
    _touch(shows / "The Office (2005)" / "Season 01" / "The Office (2005) - S01E02.mkv")
    channels = scan_libraries(
        [LibraryRoot(path=tmp_path, kind="channels")],
        probe_fn=_probe,
        fetch_metadata=False,
    )
    by_name = {ch.name: ch for ch in channels}
    assert "Thunderbolt" in by_name
    assert "Chuckle" in by_name
    assert by_name["Thunderbolt"].number == 13
    assert any("Heat" in m.title for m in by_name["Thunderbolt"].media)
    chuckle_titles = " ".join(m.title for m in by_name["Chuckle"].media)
    assert "Office" in chuckle_titles
    assert by_name["Chuckle"].playlist


def test_kind_auto_on_movies_only(tmp_path: Path):
    movies = tmp_path / "Movies"
    _touch(movies / "Up (2009)" / "Up (2009).mkv")
    (movies / "Up (2009)" / "movie.nfo").write_text(
        "<movie><genre>Animation</genre><genre>Family</genre></movie>\n",
        encoding="utf-8",
    )
    channels = scan_libraries(
        [LibraryRoot(path=tmp_path, kind="auto")],
        probe_fn=_probe,
        fetch_metadata=False,
    )
    names = {ch.name for ch in channels}
    assert names == {"Toonbox"}
