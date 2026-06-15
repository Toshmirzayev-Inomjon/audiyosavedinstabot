from __future__ import annotations

import asyncio
import logging
import mimetypes
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, FSInputFile, Message

from app.config import Settings
from app.database import Database
from app.i18n import text as i18n_text
from app.jobs import JobCancelled, JobContext, JobManager
from app.keyboards import (
    CANCEL_BUTTON,
    MENU_LABELS,
    cancel_keyboard,
    history_keyboard,
    language_keyboard,
    main_keyboard,
    quality_keyboard,
)
from app.services.downloader import (
    DownloadCancelled,
    DownloadService,
    MediaDownloadError,
    platform_for_url,
    search_query,
)
from app.services.media import MediaConversionError, MediaService
from app.services.telegram_downloader import (
    TelegramDownloadError,
    TelegramDownloadService,
    is_telegram_url,
    parse_telegram_url,
)

logger = logging.getLogger(__name__)

VIDEO_LABELS = {labels["video"] for labels in MENU_LABELS.values()}
MP3_LABELS = {labels["mp3"] for labels in MENU_LABELS.values()}
MUSIC_SEARCH_LABELS = {labels["music_search"] for labels in MENU_LABELS.values()}
AI_MUSIC_LABELS = {labels["ai_music"] for labels in MENU_LABELS.values()}
CIRCLE_LABELS = {labels["circle"] for labels in MENU_LABELS.values()}
RECTANGLE_LABELS = {labels["rectangle"] for labels in MENU_LABELS.values()}
HISTORY_LABELS = {labels["history"] for labels in MENU_LABELS.values()}
LANGUAGE_LABELS = {labels["language"] for labels in MENU_LABELS.values()}


class MediaStates(StatesGroup):
    video_quality = State()
    video_download = State()
    mp3_download = State()
    circle = State()
    rectangle = State()


@dataclass(slots=True)
class Services:
    settings: Settings
    database: Database
    downloader: DownloadService
    media: MediaService
    telegram: TelegramDownloadService
    jobs: JobManager
    public_base_url: str | None = None


async def ensure_user(message: Message, database: Database) -> None:
    if not message.from_user:
        return
    await database.ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )


def _looks_like_url(text: str) -> bool:
    return text.strip().startswith(("http://", "https://"))


def _input_file(message: Message, *, allow_audio: bool = True):
    if message.video_note:
        return message.video_note, "video_note.mp4"
    if message.video:
        return message.video, message.video.file_name or "video.mp4"
    if allow_audio and message.audio:
        return message.audio, message.audio.file_name or "audio.mp3"
    if message.document:
        mime = message.document.mime_type or ""
        allowed_prefixes = ("video/", "audio/") if allow_audio else ("video/",)
        if mime.startswith(allowed_prefixes):
            return message.document, message.document.file_name or "media.bin"
    return None, None


async def _download_message_media(
    message: Message,
    bot: Bot,
    directory: Path,
    max_bytes: int,
    *,
    allow_audio: bool = True,
) -> Path:
    media, filename = _input_file(message, allow_audio=allow_audio)
    if not media or not filename:
        raise MediaDownloadError("Video, audio, havola yoki qo'shiq nomi yuboring")
    if media.file_size and media.file_size > max_bytes:
        raise MediaDownloadError("Fayl ruxsat etilgan hajmdan katta")
    destination = directory / Path(filename).name
    await bot.download(media.file_id, destination=destination)
    if not destination.exists():
        raise MediaDownloadError("Telegram fayli yuklanmadi")
    return destination


def _validate_text_url(text: str) -> str:
    url = text.strip()
    if is_telegram_url(url):
        parse_telegram_url(url)
        return url
    platform_for_url(url)
    return url


async def _resolve_source(
    message: Message,
    bot: Bot,
    services: Services,
    directory: Path,
    *,
    prefer_audio: bool = False,
    allow_audio_upload: bool = True,
    quality: str = "720",
    progress=None,
    cancel_event: asyncio.Event | None = None,
) -> Path:
    if message.text and message.text != CANCEL_BUTTON:
        raw = message.text.strip()
        if prefer_audio and not _looks_like_url(raw):
            return await services.downloader.download(
                search_query(raw),
                directory,
                audio=True,
                quality="audio",
                progress=progress,
                cancel_event=cancel_event,
            )
        url = _validate_text_url(raw)
        if is_telegram_url(url):
            return await services.telegram.download(url, directory)
        return await services.downloader.download(
            url,
            directory,
            audio=prefer_audio,
            quality=quality,
            progress=progress,
            cancel_event=cancel_event,
        )
    return await _download_message_media(
        message,
        bot,
        directory,
        services.settings.max_download_bytes,
        allow_audio=allow_audio_upload,
    )


async def _check_output(path: Path, settings: Settings) -> None:
    if not path.exists() or path.stat().st_size == 0:
        raise MediaConversionError("Tayyor media fayli yaratilmadi")
    if path.stat().st_size > settings.max_download_bytes:
        raise MediaConversionError(
            f"Tayyor fayl {settings.max_download_mb} MB limitdan oshib ketdi"
        )


async def _check_duration(source: Path, services: Services) -> None:
    info = await services.media.probe(source)
    if info.duration > services.settings.max_duration_seconds:
        max_hours = services.settings.max_duration_seconds / 3600
        raise MediaConversionError(f"Media {max_hours:g} soatlik limitdan uzun")


async def _temporary_download_link(
    path: Path,
    *,
    user_id: int,
    services: Services,
) -> str:
    if not services.public_base_url:
        raise MediaConversionError("Katta fayl uchun public HTTPS manzil topilmadi")
    public_dir = services.settings.temp_dir / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    destination = public_dir / f"{user_id}-{secrets.token_hex(8)}{path.suffix}"
    await asyncio.to_thread(shutil.move, path, destination)
    mime_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    token = await services.database.create_public_file(
        user_id,
        path=str(destination),
        filename=path.name,
        mime_type=mime_type,
        ttl_seconds=services.settings.public_file_ttl_seconds,
    )
    return f"{services.public_base_url}/files/{token}"


async def _delete_status(status: Message | None) -> None:
    if not status:
        return
    try:
        await status.delete()
    except Exception:
        logger.debug("Status message could not be deleted", exc_info=True)


async def _update_status(status: Message, text: str) -> None:
    try:
        await status.edit_text(text)
    except Exception:
        logger.debug("Status message could not be updated", exc_info=True)


async def _show_error(message: Message, exc: Exception) -> None:
    if isinstance(
        exc,
        (
            MediaDownloadError,
            MediaConversionError,
            TelegramDownloadError,
            JobCancelled,
        ),
    ):
        text = str(exc)
    elif isinstance(exc, TelegramAPIError):
        logger.exception("Telegram API error", exc_info=exc)
        text = f"Telegramga yuborishda xato: {exc}"
    else:
        logger.exception("Unexpected media processing error", exc_info=exc)
        text = "Kutilmagan xato yuz berdi. Birozdan keyin qayta urinib ko'ring."
    await message.answer(f"Xato: {text}\n\nQayta yuboring yoki /cancel ni bosing.")


async def _send_video_note_or_fallback(
    message: Message,
    output: Path,
    *,
    duration: int,
) -> bool:
    try:
        await message.answer_video_note(
            FSInputFile(output),
            duration=duration,
            length=640,
        )
        return True
    except TelegramBadRequest as exc:
        if "VOICE_MESSAGES_FORBIDDEN" not in str(exc).upper():
            raise
        await message.answer_video(
            FSInputFile(output),
            caption=(
                "Telegram maxfiylik sozlamangiz aylana/ovozli xabarni qabul "
                "qilmadi. Shu sababli video oddiy formatda yuborildi."
            ),
            supports_streaming=True,
            reply_markup=main_keyboard(),
        )
        return False


class _ProgressUpdater:
    def __init__(self, status: Message) -> None:
        self.status = status
        self.loop = asyncio.get_running_loop()
        self.last_percent = -10

    def __call__(self, percent: float, stage: str) -> None:
        rounded = min(100, max(0, int(percent // 5 * 5)))
        if rounded < 100 and rounded - self.last_percent < 5:
            return
        self.last_percent = rounded
        blocks = min(10, rounded // 10)
        bar = "▰" * blocks + "▱" * (10 - blocks)
        label = "Fayl birlashtirilmoqda" if stage == "processing" else "Yuklanmoqda"
        text = f"⏳ {label}: {rounded}%\n{bar}\n/cancel - bekor qilish"
        self.loop.call_soon_threadsafe(
            lambda: asyncio.create_task(_update_status(self.status, text))
        )


def build_router(services: Services) -> Router:
    router = Router()
    settings = services.settings
    database = services.database

    @router.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await ensure_user(message, database)
        language = (
            await database.get_language(message.from_user.id)
            if message.from_user
            else "uz"
        )
        await message.answer(
            i18n_text(language, "welcome")
            + "\n\n"
            f"⏱ Maksimal davomiylik: <b>{settings.max_duration_minutes // 60} soat</b>\n"
            f"📦 Media limiti: <b>{settings.max_download_mb} MB gacha</b>\n"
            "💡 MP3 uchun qo'shiq nomi yoki ijrochi nomini yozishingiz mumkin.",
            reply_markup=main_keyboard(language),
        )

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await ensure_user(message, database)
        language = (
            await database.get_language(message.from_user.id)
            if message.from_user
            else "uz"
        )
        await message.answer(i18n_text(language, "help"), reply_markup=main_keyboard(language))

    @router.message(Command("ai", "tarif"))
    @router.message(F.text.in_(AI_MUSIC_LABELS))
    async def ai_handler(message: Message) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        if not settings.huggingface_api_token:
            await message.answer(
                "🎼 AI musiqa serveri hali ulanmagan.\n\n"
                "Admin Railway Variables ichiga HUGGINGFACE_API_TOKEN yozishi kerak.",
                reply_markup=main_keyboard(),
            )
            return
        until = await database.ai_subscription_until(message.from_user.id)
        if until:
            await message.answer(
                "🎼 <b>AI qo'shiq obunangiz faol</b>\n\n"
                "Tarif: 30 kunlik AI obuna\n"
                f"AI modeli ulangan: <code>{settings.huggingface_music_model}</code>\n"
                "Holat: matndan qo'shiq yaratish generatori tayyorlanmoqda.",
                reply_markup=main_keyboard(),
            )
            return
        await message.answer(
            "🎼 <b>AI qo'shiq tarifi</b>\n\n"
            "Muddat: 30 kun\n"
            "Narx: admin bilan kelishiladi\n"
            f"AI server: ulangan ({settings.huggingface_music_model})\n\n"
            "Avtomatik to'lov yo'q. Obuna olish uchun adminga yozing, "
            "admin to'lovni tekshirgandan keyin WebApp admin panelidan sizga "
            "AI obuna ochib beradi.",
            reply_markup=main_keyboard(),
        )

    @router.message(Command("cancel"))
    @router.message(F.text.in_({CANCEL_BUTTON, "Bekor qilish"}))
    async def cancel_handler(message: Message, state: FSMContext) -> None:
        cancelled = False
        if message.from_user:
            cancelled = await services.jobs.cancel(message.from_user.id)
        await state.clear()
        await message.answer(
            "Aktiv yuklash bekor qilinmoqda." if cancelled else "Amal bekor qilindi.",
            reply_markup=main_keyboard(),
        )

    @router.message(F.text.in_(LANGUAGE_LABELS | {"Til / Language"}))
    @router.message(Command("language"))
    async def language_handler(message: Message) -> None:
        await ensure_user(message, database)
        await message.answer(
            "Tilni tanlang / Выберите язык / Choose language:",
            reply_markup=language_keyboard(),
        )

    @router.callback_query(F.data.startswith("lang:"))
    async def language_callback(callback: CallbackQuery) -> None:
        if not callback.data:
            return
        language = callback.data.split(":", maxsplit=1)[1]
        if language not in {"uz", "ru", "en"}:
            await callback.answer("Language error", show_alert=True)
            return
        await database.set_language(callback.from_user.id, language)
        texts = {
            "uz": "Til o'zbekchaga o'zgartirildi.",
            "ru": "Язык изменён на русский.",
            "en": "Language changed to English.",
        }
        await callback.message.answer(texts[language], reply_markup=main_keyboard(language))
        await callback.answer()

    @router.message(F.text.in_(VIDEO_LABELS | {"Video yuklash"}))
    async def choose_video(message: Message, state: FSMContext) -> None:
        await ensure_user(message, database)
        await state.set_state(MediaStates.video_quality)
        await message.answer(
            "📥 <b>Video sifatini tanlang</b>\n\n"
            "Keyin video havolasi yoki video fayl yuboring.",
            reply_markup=quality_keyboard(),
        )

    @router.callback_query(MediaStates.video_quality, F.data.startswith("quality:"))
    async def quality_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.data:
            return
        quality = callback.data.split(":", maxsplit=1)[1]
        if quality not in {"360", "720", "1080", "audio"}:
            await callback.answer("Sifat noto'g'ri", show_alert=True)
            return
        await state.update_data(quality=quality)
        await state.set_state(
            MediaStates.mp3_download if quality == "audio" else MediaStates.video_download
        )
        text = (
            "🎵 Havola, qo'shiq nomi, ijrochi nomi, video yoki audio yuboring."
            if quality == "audio"
            else f"📥 {quality}p tanlandi. Havola yoki video yuboring."
        )
        await callback.message.answer(text, reply_markup=cancel_keyboard())
        await callback.answer()

    @router.message(F.text.in_(MP3_LABELS | MUSIC_SEARCH_LABELS | {"MP3 yuklash"}))
    async def choose_mp3(message: Message, state: FSMContext) -> None:
        await ensure_user(message, database)
        await state.set_state(MediaStates.mp3_download)
        await message.answer(
            "🎵 <b>MP3 tayyorlash</b>\n\n"
            "YouTube/Instagram/TikTok/SoundCloud havolasini yuboring yoki "
            "qo'shiq nomi/ijrochi nomini yozing.",
            reply_markup=cancel_keyboard(),
        )

    @router.message(F.text.in_(HISTORY_LABELS | {"Yuklash tarixi"}))
    @router.message(Command("history"))
    async def history_handler(message: Message) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        items = await database.recent_downloads(message.from_user.id, 10)
        available = [
            (item.id, item.title or f"{item.media_type} {item.quality}".strip())
            for item in items
            if item.status == "completed" and item.telegram_file_id
        ]
        if not available:
            await message.answer("Yuklash tarixi hozircha bo'sh.")
            return
        await message.answer(
            "🕘 Qayta yuborish uchun faylni tanlang:",
            reply_markup=history_keyboard(available),
        )

    @router.callback_query(F.data.startswith("history:"))
    async def history_callback(callback: CallbackQuery) -> None:
        try:
            download_id = int((callback.data or "").split(":", maxsplit=1)[1])
        except (IndexError, ValueError):
            await callback.answer("Tarix yozuvi noto'g'ri", show_alert=True)
            return
        item = await database.get_download(callback.from_user.id, download_id)
        if not item or not item.telegram_file_id:
            await callback.answer("Fayl topilmadi", show_alert=True)
            return
        if item.media_type == "audio":
            await callback.message.answer_audio(
                item.telegram_file_id,
                caption="↻ Tarixdan qayta yuborildi.",
            )
        else:
            await callback.message.answer_video(
                item.telegram_file_id,
                caption="↻ Tarixdan qayta yuborildi.",
                supports_streaming=True,
            )
        await callback.answer()

    @router.message(F.text.in_(CIRCLE_LABELS | {"Aylana video qilish"}))
    async def choose_circle(message: Message, state: FSMContext) -> None:
        await ensure_user(message, database)
        await state.set_state(MediaStates.circle)
        await message.answer(
            "⭕ <b>Aylana video tayyorlash</b>\n\n"
            "Video yoki havolani yuboring. Natija ko'pi bilan 60 soniya bo'ladi.",
            reply_markup=cancel_keyboard(),
        )

    @router.message(F.text.in_(RECTANGLE_LABELS | {"Aylanani to'rtburchak qilish"}))
    async def choose_rectangle(message: Message, state: FSMContext) -> None:
        await ensure_user(message, database)
        await state.set_state(MediaStates.rectangle)
        await message.answer(
            "🖼 <b>Aylanani oddiy video qilish</b>\n\n"
            "Telegram video note yuboring. Natija ortiqcha effektlarsiz oddiy video bo'ladi.",
            reply_markup=cancel_keyboard(),
        )

    @router.message(MediaStates.video_download)
    async def download_video_handler(
        message: Message,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        state_data = await state.get_data()
        quality = str(state_data.get("quality", "720"))
        source_url = message.text.strip() if message.text else None
        download_id = await database.create_download(
            message.from_user.id,
            source_url=source_url,
            media_type="video",
            quality=quality,
        )
        status = await message.answer("⏳ Navbatga qo'shildi...")
        try:
            async def work(context: JobContext) -> tuple[Message, str]:
                progress = _ProgressUpdater(status)
                with tempfile.TemporaryDirectory(prefix="video-", dir=settings.temp_dir) as temp:
                    source = await _resolve_source(
                        message,
                        bot,
                        services,
                        Path(temp),
                        quality=quality,
                        progress=progress,
                        cancel_event=context.cancel_event,
                    )
                    context.check_cancelled()
                    await _check_output(source, settings)
                    if source.stat().st_size > settings.telegram_upload_bytes:
                        link = await _temporary_download_link(
                            source,
                            user_id=message.from_user.id,
                            services=services,
                        )
                        sent = await message.answer(
                            "✅ Video tayyor, lekin Telegram limitidan katta.\n\n"
                            f"Yuklab olish: {link}\n"
                            f"Havola {settings.public_file_ttl_seconds // 60} daqiqa ishlaydi.",
                            reply_markup=main_keyboard(),
                        )
                    else:
                        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
                        sent = await message.answer_video(
                            FSInputFile(source),
                            caption="✅ Video tayyor.",
                            supports_streaming=True,
                            reply_markup=main_keyboard(),
                        )
                    return sent, source.stem

            sent, title = await services.jobs.run(
                message.from_user.id,
                work,
                queued=lambda position: _update_status(
                    status,
                    f"⏳ Navbatdagi o'rningiz: {position}\n/cancel - bekor qilish",
                ),
            )
            file_id = sent.video.file_id if sent.video else None
            await database.finish_download(
                download_id,
                status="completed",
                telegram_file_id=file_id,
                title=title,
            )
            await state.clear()
        except (DownloadCancelled, JobCancelled) as exc:
            await database.finish_download(download_id, status="cancelled", error_message=str(exc))
            await state.clear()
            await message.answer("Yuklash bekor qilindi.", reply_markup=main_keyboard())
        except Exception as exc:
            await database.finish_download(download_id, status="failed", error_message=str(exc))
            await database.log_error("video_download", str(exc), message.from_user.id)
            await _show_error(message, exc)
        finally:
            await _delete_status(status)

    @router.message(MediaStates.mp3_download)
    async def download_mp3_handler(
        message: Message,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        source_url = message.text.strip() if message.text else None
        download_id = await database.create_download(
            message.from_user.id,
            source_url=source_url,
            media_type="audio",
            quality="mp3",
        )
        status = await message.answer("⏳ Qidirilmoqda va yuklanmoqda...")
        try:
            async def work(context: JobContext) -> tuple[Message, str]:
                progress = _ProgressUpdater(status)
                with tempfile.TemporaryDirectory(prefix="mp3-", dir=settings.temp_dir) as temp:
                    temp_dir = Path(temp)
                    source = await _resolve_source(
                        message,
                        bot,
                        services,
                        temp_dir,
                        prefer_audio=True,
                        quality="audio",
                        progress=progress,
                        cancel_event=context.cancel_event,
                    )
                    context.check_cancelled()
                    await _update_status(status, "⚙️ MP3 tayyorlanmoqda...")
                    await _check_duration(source, services)
                    output = await services.media.to_mp3(
                        source,
                        temp_dir / "converted.mp3",
                        cancel_event=context.cancel_event,
                    )
                    context.check_cancelled()
                    await _check_output(output, settings)
                    if output.stat().st_size > settings.telegram_upload_bytes:
                        link = await _temporary_download_link(
                            output,
                            user_id=message.from_user.id,
                            services=services,
                        )
                        sent = await message.answer(
                            "✅ MP3 tayyor, lekin Telegram limitidan katta.\n\n"
                            f"Yuklab olish: {link}\n"
                            f"Havola {settings.public_file_ttl_seconds // 60} daqiqa ishlaydi.",
                            reply_markup=main_keyboard(),
                        )
                    else:
                        await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VOICE)
                        sent = await message.answer_audio(
                            FSInputFile(output),
                            title=source_url or "Yuklangan audio",
                            caption="✅ MP3 tayyor.",
                            reply_markup=main_keyboard(),
                        )
                    return sent, output.stem

            sent, title = await services.jobs.run(
                message.from_user.id,
                work,
                queued=lambda position: _update_status(
                    status,
                    f"⏳ Navbatdagi o'rningiz: {position}\n/cancel - bekor qilish",
                ),
            )
            file_id = sent.audio.file_id if sent.audio else None
            await database.finish_download(
                download_id,
                status="completed",
                telegram_file_id=file_id,
                title=title,
            )
            await state.clear()
        except (DownloadCancelled, JobCancelled) as exc:
            await database.finish_download(download_id, status="cancelled", error_message=str(exc))
            await state.clear()
            await message.answer("Yuklash bekor qilindi.", reply_markup=main_keyboard())
        except Exception as exc:
            await database.finish_download(download_id, status="failed", error_message=str(exc))
            await database.log_error("mp3_download", str(exc), message.from_user.id)
            await _show_error(message, exc)
        finally:
            await _delete_status(status)

    @router.message(MediaStates.circle)
    async def circle_handler(message: Message, state: FSMContext, bot: Bot) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        status = await message.answer("Aylana video tayyorlanmoqda...")
        try:
            with tempfile.TemporaryDirectory(prefix="circle-", dir=settings.temp_dir) as temp:
                temp_dir = Path(temp)
                source = await _resolve_source(
                    message,
                    bot,
                    services,
                    temp_dir,
                    allow_audio_upload=False,
                )
                output = await services.media.to_circle(source, temp_dir / "circle-output.mp4")
                await _check_output(output, settings)
                info = await services.media.probe(output)
                await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO_NOTE)
                sent_as_note = await _send_video_note_or_fallback(
                    message,
                    output,
                    duration=min(60, max(1, int(info.duration))),
                )
            await state.clear()
            if sent_as_note:
                await message.answer(
                    "✅ Aylana video tayyor.",
                    reply_markup=main_keyboard(),
                )
        except Exception as exc:
            await _show_error(message, exc)
        finally:
            await _delete_status(status)

    @router.message(MediaStates.rectangle)
    async def rectangle_handler(message: Message, state: FSMContext, bot: Bot) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        status = await message.answer("Oddiy video tayyorlanmoqda...")
        try:
            with tempfile.TemporaryDirectory(prefix="rectangle-", dir=settings.temp_dir) as temp:
                temp_dir = Path(temp)
                source = await _resolve_source(
                    message,
                    bot,
                    services,
                    temp_dir,
                    allow_audio_upload=False,
                )
                await _check_duration(source, services)
                output = await services.media.to_rectangle(
                    source,
                    temp_dir / "rectangle-output.mp4",
                    from_video_note=bool(message.video_note),
                )
                await _check_output(output, settings)
                if output.stat().st_size > settings.telegram_upload_bytes:
                    link = await _temporary_download_link(
                        output,
                        user_id=message.from_user.id,
                        services=services,
                    )
                    await message.answer(
                        "✅ Oddiy video tayyor.\n\n"
                        f"Katta faylni yuklab olish: {link}",
                        reply_markup=main_keyboard(),
                    )
                else:
                    await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
                    await message.answer_video(
                        FSInputFile(output),
                        caption="✅ Oddiy video tayyor.",
                        supports_streaming=True,
                        reply_markup=main_keyboard(),
                    )
            await state.clear()
        except Exception as exc:
            await _show_error(message, exc)
        finally:
            await _delete_status(status)

    @router.message()
    async def fallback_handler(message: Message) -> None:
        await ensure_user(message, database)
        if message.text and _looks_like_url(message.text):
            await message.answer(
                "Havola qabul qilindi. Video yuklash yoki MP3 tugmasini tanlang.",
                reply_markup=main_keyboard(),
            )
            return
        await message.answer(
            "Kerakli xizmatni tanlang. MP3 uchun qo'shiq nomini qidirish mumkin.",
            reply_markup=main_keyboard(),
        )

    return router
