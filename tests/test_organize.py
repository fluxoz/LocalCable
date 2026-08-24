from __future__ import annotations

import json
from pathlib import Path

from localcable.config import AppConfig, LibraryConfig, LibraryRoot
from localcable.jellyfin import parse_loose_filename
from localcable.organize import (
    fetch_movie_metadata,
    fetch_tv_metadata,
    organize_library,
    planned_destination,
)


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def read(self):
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def test_planned_destination_tv_and_movie(tmp_path: Path):
    parsed = parse_loose_filename("The.Office.S01E02.mkv")
    dest = planned_destination(
        parsed,
        tv_root=tmp_path / "Shows",
        movies_root=tmp_path / "Movies",
        source=tmp_path / "The.Office.S01E02.mkv",
        meta={"show": "The Office", "year": "2005", "episode_title": "Diversity Day"},
    )
    assert dest is not None
    assert dest.parent.name == "Season 01"
    assert "S01E02" in dest.name
    movie = parse_loose_filename("Heat.1995.mkv")
    mdest = planned_destination(
        movie,
        tv_root=tmp_path / "Shows",
        movies_root=tmp_path / "Movies",
        source=tmp_path / "Heat.1995.mkv",
        meta={"title": "Heat", "year": "1995"},
    )
    assert mdest is not None
    assert mdest.parent.name == "Heat (1995)"


def test_fetch_tv_and_movie_metadata_mocked():
    calls: list[str] = []

    def opener(req, timeout=0):
        url = getattr(req, "full_url", str(req))
        calls.append(url)
        if "tvmaze.com/singlesearch" in url:
            return FakeResp(
                {
                    "id": 66,
                    "name": "The Office",
                    "premiered": "2005-03-24",
                    "summary": "<p>A mockumentary.</p>",
                    "image": {"original": "http://example/office.jpg"},
                }
            )
        if "episodebynumber" in url:
            return FakeResp({"name": "Diversity Day", "summary": "<p>Seminar.</p>"})
        if "itunes.apple.com" in url:
            return FakeResp(
                {
                    "results": [
                        {
                            "trackName": "Heat",
                            "releaseDate": "1995-12-15T08:00:00Z",
                            "longDescription": "Cops and robbers.",
                            "artworkUrl100": "http://example/100x100bb.jpg",
                        }
                    ]
                }
            )
        raise AssertionError(url)

    tv = fetch_tv_metadata("The Office", 1, 2, opener=opener)
    assert tv["show"] == "The Office"
    assert tv["year"] == "2005"
    assert tv["episode_title"] == "Diversity Day"
    movie = fetch_movie_metadata("Heat", "1995", opener=opener)
    assert movie["title"] == "Heat"
    assert movie["year"] == "1995"
    assert "600x600bb" in (movie.get("art_url") or "")
    assert calls


def test_organize_moves_inbox_without_overwrite(tmp_path: Path):
    inbox = tmp_path / "inbox"
    shows = tmp_path / "Shows"
    movies = tmp_path / "Movies"
    inbox.mkdir()
    shows.mkdir()
    movies.mkdir()
    src = inbox / "The.Office.S01E01.720p.mkv"
    src.write_bytes(b"episode")
    already = movies / "Heat (1995)" / "Heat (1995).mkv"
    already.parent.mkdir(parents=True)
    already.write_bytes(b"existing")
    (inbox / "Heat.1995.1080p.mkv").write_bytes(b"new-heat")

    config = AppConfig(
        libraries=[
            LibraryRoot(path=shows, kind="tv"),
            LibraryRoot(path=movies, kind="movies"),
        ],
        library=LibraryConfig(auto_organize=True, inbox=inbox, fetch_metadata=False),
    )
    result = organize_library(config, dry_run=False)
    moved_names = {row.source.name: row.dest for row in result.moved}
    assert "The.Office.S01E01.720p.mkv" in moved_names
    dest = moved_names["The.Office.S01E01.720p.mkv"]
    assert dest.is_file()
    assert not src.exists()
    assert dest.parent.name == "Season 01"
    skipped_reasons = {path.name: reason for path, reason in result.skipped}
    assert skipped_reasons.get("Heat.1995.1080p.mkv") == "destination exists"
    assert already.read_bytes() == b"existing"


def test_organize_off_is_noop(tmp_path: Path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "Show.S01E01.mkv").write_bytes(b"x")
    config = AppConfig(
        libraries=[LibraryRoot(path=tmp_path / "Shows", kind="tv")],
        library=LibraryConfig(auto_organize=False, inbox=inbox),
    )
    result = organize_library(config)
    assert result.moved == []
    assert (inbox / "Show.S01E01.mkv").exists()
