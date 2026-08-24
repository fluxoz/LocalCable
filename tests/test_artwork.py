"""User-supplied sidecars win; keyless online fetch is optional and mocked."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from localcable.artwork import find_folder_poster, find_sidecar, resolve_artwork
from localcable.app import AppState, create_app
from tests.test_api import _config, _fake_player

# 1x1 PNG
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082"
)


def test_sidecar_next_to_video(tmp_path: Path):
    video = tmp_path / "evening_news.mp4"
    video.write_bytes(b"x")
    art = tmp_path / "evening_news.jpg"
    art.write_bytes(PNG)
    found = find_sidecar(video)
    assert found == art


def test_poster_suffix_and_folder_cover(tmp_path: Path):
    folder = tmp_path / "101_CNN"
    folder.mkdir()
    video = folder / "late_edition.mp4"
    video.write_bytes(b"x")
    poster = folder / "late_edition-poster.png"
    poster.write_bytes(PNG)
    assert find_sidecar(video) == poster
    cover = folder / "cover.jpg"
    cover.write_bytes(PNG)
    assert find_folder_poster(folder) == cover


def test_sidecar_beats_online_fetch(tmp_path: Path):
    video = tmp_path / "show.mp4"
    video.write_bytes(b"x")
    sidecar = tmp_path / "show.jpg"
    sidecar.write_bytes(PNG)

    def boom(*_a, **_k):
        raise AssertionError("must not hit the network when a sidecar exists")

    path = resolve_artwork(
        video_path=video,
        title="Show",
        cache_dir=tmp_path / "cache",
        fetch=True,
        opener=boom,
    )
    assert path == sidecar


def test_tvmaze_fetch_cached(tmp_path: Path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    cache = tmp_path / "cache"
    seen: list[str] = []

    class Resp:
        def __init__(self, body: bytes):
            self._body = body

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    def opener(req, timeout=4):
        url = getattr(req, "full_url", str(req))
        seen.append(url)
        if "api.tvmaze.com" in url:
            return Resp(json.dumps({"image": {"original": "http://example.test/p.png"}}).encode())
        return Resp(PNG)

    def no_ffmpeg(*_a, **_k):
        class Proc:
            returncode = 1

        return Proc()

    path = resolve_artwork(
        video_path=video,
        title="Nature",
        cache_dir=cache,
        fetch=True,
        opener=opener,
        runner=no_ffmpeg,
    )
    assert path is not None and path.is_file()
    assert path.read_bytes() == PNG
    assert any("tvmaze.com" in u for u in seen)
    seen.clear()
    again = resolve_artwork(
        video_path=video,
        title="Nature",
        cache_dir=cache,
        fetch=True,
        opener=opener,
        runner=no_ffmpeg,
    )
    assert again == path
    assert seen == []


def test_art_api_serves_sidecar(tmp_path: Path, media_root: Path, frozen_now):
    config = _config(tmp_path, media_root)
    player, _ = _fake_player(tmp_path)
    state = AppState(config, now_fn=lambda: frozen_now, player=player)
    app = create_app(state=state)
    with TestClient(app) as client:
        body = client.get("/api/schedule").json()
        program = None
        for channel in body["channels"]:
            for item in channel["programs"]:
                program = item
                break
            if program:
                break
        assert program
        video = Path(program["file_path"])
        sidecar = video.with_suffix(".jpg")
        sidecar.write_bytes(PNG)
        assert program["art"] == f"/art/{program['id']}"
        response = client.get(program["art"])
        assert response.status_code == 200, response.text
        assert response.content == PNG
        missing = client.get("/art/does-not-exist")
        assert missing.status_code == 404


def test_channel_poster_api(tmp_path: Path, media_root: Path, frozen_now):
    config = _config(tmp_path, media_root)
    player, _ = _fake_player(tmp_path)
    state = AppState(config, now_fn=lambda: frozen_now, player=player)
    poster = media_root / "101_CNN" / "poster.jpg"
    poster.write_bytes(PNG)
    app = create_app(state=state)
    with TestClient(app) as client:
        response = client.get("/art/channel/101")
        assert response.status_code == 200
        assert response.content == PNG
