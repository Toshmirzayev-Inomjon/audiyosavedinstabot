from pathlib import Path

import pytest

from app.services.downloader import (
    DownloadService,
    MediaDownloadError,
    format_for_quality,
    platform_for_url,
    search_queries,
    search_query,
    song_query_from_info,
)


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://youtu.be/abc123", "YouTube"),
        ("https://www.youtube.com/watch?v=abc123", "YouTube"),
        ("https://music.youtube.com/watch?v=abc123", "YouTube Music"),
        ("https://instagram.com/reel/abc123/", "Instagram"),
        ("https://www.instagram.com/p/abc123/", "Instagram"),
        ("https://www.tiktok.com/@user/video/123", "TikTok"),
        ("https://soundcloud.com/artist/song", "SoundCloud"),
        ("https://x.com/user/status/123", "X"),
    ],
)
def test_supported_urls(url: str, platform: str) -> None:
    assert platform_for_url(url) == platform


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://example.com/video",
        "https://youtube.com.evil.example/watch?v=x",
        "https://user:password@youtube.com/watch?v=x",
        "not-a-url",
    ],
)
def test_rejects_unsupported_or_unsafe_urls(url: str) -> None:
    with pytest.raises(MediaDownloadError):
        platform_for_url(url)


def test_quality_format_limits_height() -> None:
    assert "height<=360" in format_for_quality("360")
    assert "height<=720" in format_for_quality("720")
    assert "height<=1080" in format_for_quality("1080")
    assert format_for_quality("audio", audio=True).startswith("bestaudio")


def test_song_search_query_uses_yt_dlp_search() -> None:
    assert search_query("  artist   song name ") == "ytsearch1:artist song name"
    assert search_queries("artist song") == (
        "ytsearch1:artist song",
        "scsearch1:artist song",
    )
    with pytest.raises(MediaDownloadError):
        search_query("x")


def test_song_query_from_social_metadata_prefers_artist_and_track() -> None:
    info = {
        "title": "Instagram video by user",
        "music_info": {
            "artist": "Saman",
            "track": "BURGUT 2",
        },
    }

    assert song_query_from_info(info) == "Saman BURGUT 2"


def test_song_query_from_social_metadata_rejects_generic_audio() -> None:
    info = {"audio_title": "Original audio", "title": "Instagram reel"}

    assert song_query_from_info(info) is None


@pytest.mark.asyncio
async def test_song_search_falls_back_to_soundcloud(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = DownloadService(max_bytes=1_000_000, max_duration_seconds=600)
    calls: list[str] = []

    async def fake_download(url: str, directory: Path, **_kwargs) -> Path:
        calls.append(url)
        if url.startswith("ytsearch"):
            raise MediaDownloadError("YouTube blocked")
        output = directory / "source.mp3"
        output.write_bytes(b"audio")
        return output

    monkeypatch.setattr(service, "download", fake_download)

    result = await service.search("Oq libos", tmp_path)

    assert result.name == "source.mp3"
    assert calls == ["ytsearch1:Oq libos", "scsearch1:Oq libos"]


@pytest.mark.asyncio
async def test_social_audio_uses_detected_full_song_query(
    monkeypatch,
    tmp_path: Path,
) -> None:
    service = DownloadService(max_bytes=1_000_000, max_duration_seconds=600)
    calls: list[str] = []

    async def fake_extract_info(url: str) -> dict:
        assert url == "https://www.instagram.com/reel/abc/"
        return {"music": {"artist": "Artist", "title": "Song"}}

    async def fake_search(query: str, directory: Path, **_kwargs) -> Path:
        calls.append(query)
        output = directory / "full-song.mp3"
        output.write_bytes(b"audio")
        return output

    async def fake_download(*_args, **_kwargs) -> Path:
        raise AssertionError("short reel audio should not be downloaded")

    monkeypatch.setattr(service, "extract_info", fake_extract_info)
    monkeypatch.setattr(service, "search", fake_search)
    monkeypatch.setattr(service, "download", fake_download)

    result = await service.download_audio_or_song(
        "https://www.instagram.com/reel/abc/",
        tmp_path,
    )

    assert result.name == "full-song.mp3"
    assert calls == ["Artist Song"]
