from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from threading import Event

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

from bot.services.platforms import detect_platform
from bot.services.proxies import ProxyProvider


class DownloadErrorHuman(RuntimeError):
    pass


class DownloadCancelled(DownloadErrorHuman):
    pass


def format_for_quality(quality: str, *, audio: bool = False, subtitles: bool = False) -> str:
    if subtitles:
        return "best[ext=mp4]/best"
    if audio:
        return "bestaudio[ext=m4a]/bestaudio/best"
    heights = {"360": 360, "480": 480, "720": 720, "1080": 1080}
    height = heights.get(quality, 720)
    return (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={height}]+bestaudio/"
        f"best[height<={height}][ext=mp4]/best[height<={height}]"
    )


class YtDlpDownloader:
    def __init__(
        self,
        *,
        max_bytes: int,
        max_duration_seconds: int,
        proxy_provider: ProxyProvider | None = None,
        cookies_file: Path | None = None,
    ) -> None:
        self.max_bytes = max_bytes
        self.max_duration_seconds = max_duration_seconds
        self.proxy_provider = proxy_provider or ProxyProvider()
        self.cookies_file = cookies_file

    async def download(
        self,
        url: str,
        directory: Path,
        *,
        media_type: str,
        quality: str,
        progress: Callable[[float, str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> Path:
        return await asyncio.to_thread(
            self.download_sync,
            url,
            directory,
            media_type,
            quality,
            progress,
            cancel_event,
        )

    def download_sync(
        self,
        url: str,
        directory: Path,
        media_type: str,
        quality: str,
        progress: Callable[[float, str], None] | None = None,
        cancel_event: Event | None = None,
    ) -> Path:
        detect_platform(url)
        directory.mkdir(parents=True, exist_ok=True)
        audio = media_type == "audio"
        subtitles = media_type == "subtitles"

        def progress_hook(data: dict) -> None:
            if cancel_event and cancel_event.is_set():
                raise DownloadCancelled("Yuklash bekor qilindi")
            if not progress:
                return
            status = str(data.get("status", ""))
            if status == "downloading":
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
                downloaded = data.get("downloaded_bytes") or 0
                percent = (float(downloaded) / float(total) * 100) if total else 0
                progress(percent, "Yuklanmoqda")
            elif status == "finished":
                progress(100, "Qayta ishlanmoqda")

        options: dict[str, object] = {
            "outtmpl": str(directory / "source.%(ext)s"),
            "format": format_for_quality(quality, audio=audio, subtitles=subtitles),
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "cachedir": False,
            "max_filesize": self.max_bytes,
            "socket_timeout": 20,
            "retries": 3,
            "fragment_retries": 3,
            "concurrent_fragment_downloads": 4,
            "restrictfilenames": True,
            "progress_hooks": [progress_hook],
            "merge_output_format": "mp4",
            "writesubtitles": subtitles,
            "writeautomaticsub": subtitles,
            "subtitleslangs": ["uz", "en", "ru"],
        }
        proxy = self.proxy_provider.next_proxy()
        if proxy:
            options["proxy"] = proxy
        if self.cookies_file:
            options["cookiefile"] = str(self.cookies_file)

        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        except DownloadCancelled:
            raise
        except DownloadError as exc:
            raise DownloadErrorHuman(
                "Media yuklanmadi. Havola yopiq, o'chirilgan yoki platforma cheklagan."
            ) from exc

        duration = info.get("duration") if isinstance(info, dict) else None
        if duration and float(duration) > self.max_duration_seconds:
            max_hours = self.max_duration_seconds / 3600
            raise DownloadErrorHuman(f"Media {max_hours:g} soatlik limitdan uzun")

        candidates = [
            path
            for path in directory.iterdir()
            if path.is_file() and path.suffix not in {".part", ".ytdl"}
        ]
        if not candidates:
            raise DownloadErrorHuman("Yuklangan fayl topilmadi")
        result = max(candidates, key=lambda item: item.stat().st_size)
        if result.stat().st_size > self.max_bytes:
            raise DownloadErrorHuman("Media fayli ruxsat etilgan hajmdan katta")
        return result
