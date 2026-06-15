from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Callable
from pathlib import Path
from threading import Event
from urllib.parse import urlparse

from yt_dlp import YoutubeDL
from yt_dlp.utils import DownloadError

logger = logging.getLogger(__name__)


class MediaDownloadError(RuntimeError):
    pass


class DownloadCancelled(MediaDownloadError):
    pass


SUPPORTED_HOSTS = {
    "facebook.com": "Facebook",
    "fb.watch": "Facebook",
    "instagram.com": "Instagram",
    "music.youtube.com": "YouTube Music",
    "soundcloud.com": "SoundCloud",
    "tiktok.com": "TikTok",
    "twitter.com": "X",
    "x.com": "X",
    "youtube.com": "YouTube",
    "youtu.be": "YouTube",
}


def format_for_quality(quality: str, *, audio: bool = False) -> str:
    if audio:
        return "bestaudio[ext=m4a]/bestaudio/best"
    heights = {"360": 360, "720": 720, "1080": 1080}
    height = heights.get(quality, 720)
    return (
        f"bestvideo[height<={height}][ext=mp4]+bestaudio[ext=m4a]/"
        f"bestvideo[height<={height}]+bestaudio/"
        f"best[height<={height}][ext=mp4]/best[height<={height}]"
    )


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
    raise MediaDownloadError("Bu platforma hozir qo'llab-quvvatlanmaydi")


def search_query(text: str) -> str:
    query = " ".join(text.strip().split())
    if len(query) < 2:
        raise MediaDownloadError("Qo'shiq nomi yoki ijrochi nomini yozing")
    return f"ytsearch1:{query}"


def search_queries(text: str) -> tuple[str, str]:
    youtube_query = search_query(text)
    normalized = youtube_query.split(":", maxsplit=1)[1]
    return youtube_query, f"scsearch1:{normalized}"


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

    async def download(
        self,
        url: str,
        directory: Path,
        *,
        audio: bool = False,
        quality: str = "720",
        progress: Callable[[float, str], None] | None = None,
        cancel_event: Event | asyncio.Event | None = None,
    ) -> Path:
        if not url.startswith(("ytsearch", "scsearch")):
            platform_for_url(url)
        return await asyncio.to_thread(
            self._download_sync,
            url,
            directory,
            audio,
            quality,
            progress,
            cancel_event,
        )

    async def search(
        self,
        query: str,
        directory: Path,
        *,
        progress: Callable[[float, str], None] | None = None,
        cancel_event: Event | asyncio.Event | None = None,
    ) -> Path:
        last_error: MediaDownloadError | None = None
        for candidate in search_queries(query):
            try:
                return await self.download(
                    candidate,
                    directory,
                    audio=True,
                    quality="audio",
                    progress=progress,
                    cancel_event=cancel_event,
                )
            except DownloadCancelled:
                raise
            except MediaDownloadError as exc:
                last_error = exc
                logger.warning("Music search failed for %s: %s", candidate, exc)
                for path in directory.iterdir():
                    if path.is_file():
                        path.unlink(missing_ok=True)
                    elif path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)
        raise MediaDownloadError(
            "Qo'shiq YouTube va SoundCloud orqali topilmadi yoki platformalar "
            "server so'rovini vaqtincha chekladi."
        ) from last_error

    def _download_sync(
        self,
        url: str,
        directory: Path,
        audio: bool,
        quality: str,
        progress: Callable[[float, str], None] | None,
        cancel_event: Event | asyncio.Event | None,
    ) -> Path:
        directory.mkdir(parents=True, exist_ok=True)

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
                progress(percent, "download")
            elif status == "finished":
                progress(100, "processing")

        options: dict[str, object] = {
            "outtmpl": str(directory / "source.%(ext)s"),
            "format": format_for_quality(quality, audio=audio),
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
            "progress_hooks": [progress_hook],
            "merge_output_format": "mp4",
            "js_runtimes": {"deno": {}},
            "remote_components": {"ejs:npm"},
        }
        if self.cookies_file:
            if self.cookies_file.is_file():
                options["cookiefile"] = str(self.cookies_file)
            else:
                logger.warning("yt-dlp cookies file not found: %s", self.cookies_file)

        try:
            with YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
        except DownloadCancelled:
            raise
        except DownloadError as exc:
            if cancel_event and cancel_event.is_set():
                raise DownloadCancelled("Yuklash bekor qilindi") from exc
            logger.warning("yt-dlp download error for %s: %s", url, exc)
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
