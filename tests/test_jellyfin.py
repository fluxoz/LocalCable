from __future__ import annotations

from pathlib import Path

from localcable.jellyfin import (
    jellyfin_movie_path,
    jellyfin_tv_path,
    parse_episode_tag,
    parse_loose_filename,
    scan_libraries,
    scan_movies_root,
    scan_tv_root,
)
from localcable.config import LibraryRoot
from localcable.models import MediaFile
from localcable.scan import merge_channels
from localcable.models import Channel


def _probe(path, **_kwargs):
    return MediaFile(path=Path(path).resolve(), title=Path(path).stem, duration_seconds=60.0)


def _touch_video(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"not-a-real-video")
    return path


def test_parse_episode_and_loose_names():
    assert parse_episode_tag("Show - S01E02 - Pilot.mkv") == (1, 2)
    tv = parse_loose_filename("The.Office.S02E03.720p.WEBRip.x264.mkv")
    assert tv is not None
    assert tv["kind"] == "tv"
    assert tv["show"] == "The Office"
    assert tv["season"] == 2
    assert tv["episode"] == 3
    x_tag = parse_loose_filename("Show Name - 1x04 - Title.mkv")
    assert x_tag is not None
    assert x_tag["kind"] == "tv"
    assert x_tag["season"] == 1
    assert x_tag["episode"] == 4
    movie = parse_loose_filename("Some.Movie.1999.1080p.BluRay.mkv")
    assert movie is not None
    assert movie["kind"] == "movie"
    assert movie["title"] == "Some Movie"
    assert movie["year"] == "1999"


def test_jellyfin_paths():
    tv = jellyfin_tv_path("/media/Shows", "The Office", "2005", 1, 2, ".mkv", "The Dundies")
    assert tv.parent.name == "Season 01"
    assert tv.parent.parent.name == "The Office (2005)"
    assert "S01E02" in tv.name
    assert "The Dundies" in tv.name
    movie = jellyfin_movie_path("/media/Movies", "Heat", "1995", ".mkv")
    assert movie.parent.name == "Heat (1995)"
    assert movie.name == "Heat (1995).mkv"


def test_scan_tv_root_series_are_channels(tmp_path: Path):
    shows = tmp_path / "Shows"
    _touch_video(shows / "The Office (2005)" / "Season 01" / "The Office (2005) - S01E01 - Pilot.mkv")
    _touch_video(shows / "The Office (2005)" / "Season 01" / "The Office (2005) - S01E02 - Diversity Day.mkv")
    _touch_video(shows / "The Office (2005)" / "featurettes" / "behind.mkv")
    _touch_video(shows / "Lost (2004)" / "Season 01" / "Lost (2004) - S01E01.mkv")
    channels = scan_tv_root(shows, probe_fn=_probe)
    by_name = {ch.name: ch for ch in channels}
    assert "The Office (2005)" in by_name
    assert "Lost (2004)" in by_name
    office = by_name["The Office (2005)"]
    assert len(office.media) == 2
    assert "S01E01" in office.media[0].title
    extras = [m for m in office.media if "behind" in m.path.name]
    assert extras == []


def test_scan_movies_root_one_channel(tmp_path: Path):
    movies = tmp_path / "900_Movies"
    _touch_video(movies / "Heat (1995)" / "Heat (1995).mkv")
    _touch_video(movies / "Up (2009)" / "Up (2009).mkv")
    channels = scan_movies_root(movies, probe_fn=_probe)
    assert len(channels) == 1
    assert channels[0].number == 900
    assert channels[0].name == "Movies"
    titles = {m.title for m in channels[0].media}
    assert "Heat (1995)" in titles
    assert "Up (2009)" in titles


def test_scan_libraries_merges_kinds(tmp_path: Path):
    tv = tmp_path / "Shows"
    movies = tmp_path / "Movies"
    channels_root = tmp_path / "Channels"
    _touch_video(tv / "Lost (2004)" / "Season 01" / "Lost (2004) - S01E01.mkv")
    _touch_video(movies / "Heat (1995)" / "Heat (1995).mkv")
    (channels_root / "101_CNN").mkdir(parents=True)
    libs = [
        LibraryRoot(path=channels_root, kind="channels"),
        LibraryRoot(path=tv, kind="tv"),
        LibraryRoot(path=movies, kind="movies"),
    ]
    channels = scan_libraries(libs, probe_fn=_probe)
    names = {ch.name for ch in channels}
    assert "CNN" in names
    assert "Lost (2004)" in names
    assert "Movies" in names
    numbers = [ch.number for ch in channels]
    assert numbers == sorted(numbers)
    assert len(set(numbers)) == len(numbers)


def test_merge_channels_rewrites_collisions():
    a = Channel(number=1, name="A", folder_path=Path("/a"))
    b = Channel(number=1, name="B", folder_path=Path("/b"))
    c = Channel(number=5, name="C", folder_path=Path("/c"))
    merged = merge_channels([a, c], [b])
    numbers = [ch.number for ch in merged]
    assert 1 in numbers and 5 in numbers
    assert len(set(numbers)) == 3
