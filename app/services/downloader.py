from __future__ import annotations

import asyncio
from pathlib import Path
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError


class MediaDownloadError(RuntimeError):
    pass


SUPPORTED_HOSTS = {
    "instagram.com": "Instagram",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
}


def platform_for_url(url: str) -> str:
    try:
        parsed = urlparse(url.strip())
    except ValueError as exc:
        raise MediaDownloadError("Havola noto'g'ri") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise MediaDownloadError("Faqat http/https havola yuboring")
    if parsed.username or parsed.password:
        raise MediaDownloadError("Login ma'lumoti yozilgan havola qabul qilinmaydi")

    hostname = parsed.hostname.lower().rstrip(".")
    for allowed_host, platform in SUPPORTED_HOSTS.items():
        if hostname == allowed_host or hostname.endswith(f".{allowed_host}"):
            return platform
    raise MediaDownloadError("Faqat YouTube yoki Instagram havolasi qo'llanadi")


class DownloadService:
    def __init__(
        self,
        *,
        max_bytes: int,
        max_duration_seconds: int,
        cookies_file: Path | None = None,
    ) -> None:
        self.max_bytes = max_bytes
        self.max_duration_seconds = max_duration_seconds
        self.cookies_file = cookies_file

    async def download(self, url: str, directory: Path, *, audio: bool = False) -> Path:
        platform_for_url(url)
        return await asyncio.to_thread(self._download_sync, url, directory, audio)

    def _download_sync(self, url: str, directory: Path, audio: bool) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        options: dict[str, object] = {
            "outtmpl": str(directory / "source.%(ext)s"),
            "format": (
                "bestaudio[ext=m4a]/bestaudio/best"
                if audio
                else "best[ext=mp4][height<=720]/best[height<=720]/best"
            ),
            "noplaylist": True,
            "quiet": True,
            "noprogress": True,
            "no_warnings": True,
            "cachedir": False,
            "max_filesize": self.max_bytes,
            "socket_timeout": 15,
            "retries": 1,
            "fragment_retries": 1,
            "concurrent_fragment_downloads": 4,
            "restrictfilenames": True,
        }
        if self.cookies_file:
            options["cookiefile"] = str(self.cookies_file)

        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        except DownloadError as exc:
            raise MediaDownloadError(
                "Media yuklanmadi. Havola yopiq, o'chirilgan yoki platforma cheklov qo'ygan."
            ) from exc

        duration = info.get("duration") if isinstance(info, dict) else None
        if duration and float(duration) > self.max_duration_seconds:
            max_hours = self.max_duration_seconds / 3600
            raise MediaDownloadError(
                f"Media {max_hours:g} soatlik limitdan uzun"
            )

        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix not in {".part", ".ytdl"}
        ]
        if not candidates:
            raise MediaDownloadError("Yuklangan media fayli topilmadi")
        result = max(candidates, key=lambda path: path.stat().st_size)
        if result.stat().st_size > self.max_bytes:
            raise MediaDownloadError("Media fayli ruxsat etilgan hajmdan katta")
        return result
