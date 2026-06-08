from __future__ import annotations

import asyncio
import tempfile
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot
from aiogram.types import FSInputFile
from sqlalchemy import select, update

from bot.config import settings
from bot.database.models import Download, MediaCache, utcnow
from bot.database.session import create_sessionmaker, session_scope
from bot.keyboards import audio_tools_keyboard
from bot.services.cache import CacheIdentity, save_cached_media
from bot.services.downloader import DownloadErrorHuman, YtDlpDownloader
from bot.services.ffmpeg import extract_mp3
from bot.services.platforms import detect_platform
from bot.services.progress import ThrottledProgress, progress_text
from bot.services.proxies import ProxyProvider
from bot.tasks.celery_app import celery_app


@dataclass(frozen=True, slots=True)
class DownloadPayload:
    download_id: int
    user_id: int
    chat_id: int
    status_message_id: int
    normalized_url: str
    media_type: str
    quality: str


class TelegramProgressReporter:
    def __init__(self, bot: Bot, payload: DownloadPayload) -> None:
        self.bot = bot
        self.payload = payload
        self.throttle = ThrottledProgress(settings.progress_interval_seconds)

    def __call__(self, percent: float, stage: str) -> None:
        if not self.throttle.should_send(percent):
            return
        asyncio.run(self._send(percent, stage))

    async def _send(self, percent: float, stage: str) -> None:
        try:
            await self.bot.edit_message_text(
                progress_text(percent, stage),
                chat_id=self.payload.chat_id,
                message_id=self.payload.status_message_id,
            )
        except Exception:
            return


@celery_app.task(name="media.download", bind=True)
def download_media_task(self, payload: dict) -> None:
    self.update_state(state="STARTED")
    asyncio.run(_download_media(DownloadPayload(**payload)))


async def _download_media(payload: DownloadPayload) -> None:
    sessionmaker = create_sessionmaker(settings.database_url)
    bot = Bot(settings.bot_token)
    proxy_provider = ProxyProvider(
        settings.rotating_proxies,
        proxy_file=settings.proxy_file,
    )
    downloader = YtDlpDownloader(
        max_bytes=settings.max_download_bytes,
        max_duration_seconds=settings.max_duration_seconds,
        proxy_provider=proxy_provider,
        cookies_file=settings.yt_dlp_cookies,
    )
    try:
        async with session_scope(sessionmaker) as session:
            await session.execute(
                update(Download)
                .where(Download.id == payload.download_id)
                .values(status="running", progress_percent=1)
            )

        with tempfile.TemporaryDirectory(
            prefix=f"download-{payload.download_id}-",
            dir=settings.storage_dir,
        ) as raw_temp:
            temp_dir = Path(raw_temp)
            reporter = TelegramProgressReporter(bot, payload)
            source = await downloader.download(
                payload.normalized_url,
                temp_dir,
                media_type=payload.media_type,
                quality=payload.quality,
                progress=reporter,
            )
            upload_path = source
            if payload.media_type == "audio":
                upload_path = await extract_mp3(source, temp_dir / "audio.mp3")

            file_id = await _send_result(bot, payload, upload_path)
            identity = CacheIdentity(
                payload.normalized_url,
                payload.media_type,
                payload.quality,
            )
            async with session_scope(sessionmaker) as session:
                existing = await session.scalar(
                    select(MediaCache).where(MediaCache.cache_key == identity.key)
                )
                if not existing:
                    await save_cached_media(
                        session,
                        identity=identity,
                        platform=detect_platform(payload.normalized_url),
                        telegram_file_id=file_id,
                    )
                await session.execute(
                    update(Download)
                    .where(Download.id == payload.download_id)
                    .values(
                        status="completed",
                        progress_percent=100,
                        telegram_file_id=file_id,
                        completed_at=utcnow(),
                    )
                )
            await bot.edit_message_text(
                "✅ Tayyor. Fayl yuborildi.",
                chat_id=payload.chat_id,
                message_id=payload.status_message_id,
            )
    except DownloadErrorHuman as exc:
        await _mark_failed(sessionmaker, payload, str(exc))
        await bot.edit_message_text(
            f"❌ {exc}",
            chat_id=payload.chat_id,
            message_id=payload.status_message_id,
        )
    except Exception as exc:
        await _mark_failed(sessionmaker, payload, "Kutilmagan xato yuz berdi")
        await bot.edit_message_text(
            "❌ Kutilmagan xato yuz berdi. Keyinroq qayta urinib ko'ring.",
            chat_id=payload.chat_id,
            message_id=payload.status_message_id,
        )
        raise exc
    finally:
        await bot.session.close()


async def _send_result(bot: Bot, payload: DownloadPayload, path: Path) -> str:
    if payload.media_type == "audio":
        message = await bot.send_audio(
            payload.chat_id,
            FSInputFile(path),
            reply_markup=audio_tools_keyboard(),
        )
        if not message.audio:
            raise RuntimeError("Telegram audio file_id qaytarmadi")
        return message.audio.file_id
    if payload.media_type == "subtitles":
        message = await bot.send_document(payload.chat_id, FSInputFile(path))
        if not message.document:
            raise RuntimeError("Telegram document file_id qaytarmadi")
        return message.document.file_id
    message = await bot.send_video(
        payload.chat_id,
        FSInputFile(path),
        supports_streaming=True,
    )
    if not message.video:
        raise RuntimeError("Telegram video file_id qaytarmadi")
    return message.video.file_id


async def _mark_failed(sessionmaker, payload: DownloadPayload, message: str) -> None:
    async with session_scope(sessionmaker) as session:
        await session.execute(
            update(Download)
            .where(Download.id == payload.download_id)
            .values(
                status="failed",
                error_message=message[:1000],
                updated_at=utcnow(),
            )
        )
