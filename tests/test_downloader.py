import pytest

from app.services.downloader import (
    MediaDownloadError,
    format_for_quality,
    platform_for_url,
    search_query,
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
    with pytest.raises(MediaDownloadError):
        search_query("x")
