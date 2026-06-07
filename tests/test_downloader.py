import pytest

from app.services.downloader import MediaDownloadError, platform_for_url


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://youtu.be/abc123", "YouTube"),
        ("https://www.youtube.com/watch?v=abc123", "YouTube"),
        ("https://instagram.com/reel/abc123/", "Instagram"),
        ("https://www.instagram.com/p/abc123/", "Instagram"),
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

