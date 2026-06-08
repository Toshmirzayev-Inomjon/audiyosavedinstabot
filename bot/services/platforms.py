from __future__ import annotations

from urllib.parse import urlparse

SUPPORTED_HOSTS = (
    ("music.youtube.com", "YouTube Music"),
    ("facebook.com", "Facebook"),
    ("fb.watch", "Facebook"),
    ("instagram.com", "Instagram"),
    ("pinterest.com", "Pinterest"),
    ("pin.it", "Pinterest"),
    ("soundcloud.com", "SoundCloud"),
    ("tiktok.com", "TikTok"),
    ("twitter.com", "X"),
    ("x.com", "X"),
    ("youtu.be", "YouTube"),
    ("youtube.com", "YouTube"),
)


class UnsupportedPlatformError(ValueError):
    pass


def detect_platform(url: str) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise UnsupportedPlatformError("Faqat http/https havola yuboring")
    if parsed.username or parsed.password:
        raise UnsupportedPlatformError("Login yozilgan havola xavfsiz emas")
    host = parsed.hostname.lower().rstrip(".")
    for supported, platform in SUPPORTED_HOSTS:
        if host == supported or host.endswith(f".{supported}"):
            return platform
    raise UnsupportedPlatformError("Bu platforma hozir qo'llab-quvvatlanmaydi")
