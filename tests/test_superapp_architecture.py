import pytest

from bot.services.cache import CacheIdentity, normalize_url
from bot.services.downloader import format_for_quality
from bot.services.platforms import UnsupportedPlatformError, detect_platform
from bot.services.progress import progress_text, render_progress_bar
from bot.services.proxies import ProxyProvider


def test_normalize_url_removes_tracking_params() -> None:
    url = "https://WWW.YouTube.com/watch?v=abc&utm_source=tg&si=share&list=playlist"

    assert normalize_url(url) == "https://www.youtube.com/watch?v=abc&list=playlist"


def test_cache_key_depends_on_media_type_and_quality() -> None:
    video = CacheIdentity("https://youtu.be/a", "video", "720")
    audio = CacheIdentity("https://youtu.be/a", "audio", "audio")

    assert video.key == CacheIdentity("https://youtu.be/a", "video", "720").key
    assert video.key != audio.key


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://youtu.be/abc", "YouTube"),
        ("https://music.youtube.com/watch?v=abc", "YouTube Music"),
        ("https://www.instagram.com/reel/abc/", "Instagram"),
        ("https://vm.tiktok.com/abc/", "TikTok"),
        ("https://x.com/user/status/1", "X"),
        ("https://soundcloud.com/artist/song", "SoundCloud"),
    ],
)
def test_detect_platform(url: str, platform: str) -> None:
    assert detect_platform(url) == platform


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "https://youtube.com.evil.example/watch?v=x",
        "https://user:pass@youtube.com/watch?v=x",
        "not-a-url",
    ],
)
def test_detect_platform_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(UnsupportedPlatformError):
        detect_platform(url)


def test_progress_bar_text() -> None:
    assert render_progress_bar(50, width=10) == "█████░░░░░"
    assert progress_text(65).startswith("📥 Yuklanmoqda: [")
    assert progress_text(150).endswith("100%")


def test_proxy_provider_rotates_unique_proxies(tmp_path) -> None:
    proxy_file = tmp_path / "proxies.txt"
    proxy_file.write_text("http://proxy-2\n# ignored\nhttp://proxy-1\n")
    provider = ProxyProvider(("http://proxy-1",), proxy_file=proxy_file)

    assert provider.enabled is True
    assert provider.next_proxy() == "http://proxy-1"
    assert provider.next_proxy() == "http://proxy-2"
    assert provider.next_proxy() == "http://proxy-1"


def test_format_for_quality() -> None:
    assert "height<=360" in format_for_quality("360")
    assert "height<=720" in format_for_quality("720")
    assert format_for_quality("audio", audio=True).startswith("bestaudio")
    assert format_for_quality("auto", subtitles=True).startswith("best")
