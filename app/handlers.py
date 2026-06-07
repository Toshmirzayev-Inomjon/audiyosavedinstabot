from __future__ import annotations

import asyncio
import logging
import tempfile
from dataclasses import dataclass
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.enums import ChatAction
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from app.config import Settings
from app.database import Database
from app.keyboards import (
    BALANCE_BUTTON,
    BUY_BUTTON,
    CANCEL_BUTTON,
    CIRCLE_BUTTON,
    MP3_BUTTON,
    RECTANGLE_BUTTON,
    VIDEO_BUTTON,
    cancel_keyboard,
    main_keyboard,
    star_packages_keyboard,
)
from app.services.downloader import (
    DownloadService,
    MediaDownloadError,
    platform_for_url,
)
from app.services.media import MediaConversionError, MediaService
from app.services.telegram_downloader import (
    TelegramDownloadError,
    TelegramDownloadService,
    is_telegram_url,
    parse_telegram_url,
)

logger = logging.getLogger(__name__)


class MediaStates(StatesGroup):
    video_download = State()
    mp3_download = State()
    circle = State()
    rectangle = State()
    custom_stars = State()


@dataclass(slots=True)
class Services:
    settings: Settings
    database: Database
    downloader: DownloadService
    media: MediaService
    telegram: TelegramDownloadService


def format_money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so'm"


def custom_credits(stars: int, settings: Settings) -> int:
    return stars * settings.star_credit_rate


def parse_payment_payload(
    payload: str,
    *,
    currency: str,
    total_amount: int,
    settings: Settings,
) -> tuple[bool, int, int]:
    if currency != "XTR":
        return False, 0, 0
    parts = payload.split(":")
    if len(parts) != 3:
        return False, 0, 0
    kind, stars_raw, credits_raw = parts
    try:
        stars = int(stars_raw)
        credits = int(credits_raw)
    except ValueError:
        return False, 0, 0
    if stars <= 0 or credits <= 0 or total_amount != stars:
        return False, 0, 0
    if kind == "stars":
        return (stars, credits) in settings.star_packages, stars, credits
    if kind == "stars_custom":
        is_valid = (
            stars >= settings.custom_star_min
            and credits == custom_credits(stars, settings)
        )
        return is_valid, stars, credits
    return False, 0, 0


async def ensure_user(message: Message, database: Database) -> None:
    if not message.from_user:
        return
    await database.ensure_user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.full_name,
    )


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
        raise MediaDownloadError("Video, audio yoki qo'llab-quvvatlangan havola yuboring")
    if media.file_size and media.file_size > max_bytes:
        raise MediaDownloadError("Fayl ruxsat etilgan hajmdan katta")
    safe_name = Path(filename).name
    destination = directory / safe_name
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
) -> Path:
    if message.text and message.text != CANCEL_BUTTON:
        url = _validate_text_url(message.text)
        if is_telegram_url(url):
            return await services.telegram.download(url, directory)
        return await services.downloader.download(url, directory, audio=prefer_audio)
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
        raise MediaConversionError(
            f"Media {max_hours:g} soatlik limitdan uzun"
        )


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
        (MediaDownloadError, MediaConversionError, TelegramDownloadError),
    ):
        text = str(exc)
    elif isinstance(exc, TelegramAPIError):
        logger.exception("Telegram API error", exc_info=exc)
        text = f"Telegramga yuborishda xato: {exc}"
    else:
        logger.exception("Unexpected media processing error", exc_info=exc)
        text = "Kutilmagan xato yuz berdi. Birozdan keyin qayta urinib ko'ring."
    await message.answer(f"Xato: {text}\n\nQayta yuboring yoki /cancel ni bosing.")


async def _show_payment_processing(message: Message) -> Message:
    status = await message.answer("⏳ To'lov tekshirilmoqda...\n▱▱▱▱▱")
    steps = ["▰▱▱▱▱", "▰▰▱▱▱", "▰▰▰▱▱", "▰▰▰▰▱", "▰▰▰▰▰"]
    for step in steps:
        await asyncio.sleep(1)
        await _update_status(status, f"⏳ To'lov amalga oshirilmoqda...\n{step}")
    return status


def build_router(services: Services) -> Router:
    router = Router()
    settings = services.settings
    database = services.database

    @router.message(CommandStart())
    async def start_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await ensure_user(message, database)
        await message.answer(
            "<b>Assalomu alaykum!</b>\n\n"
            "Bu bot quyidagilarni bajaradi:\n"
            "📥 YouTube va Instagram havolasidan video yuklaydi\n"
            "🎵 Havola yoki videoni MP3 qiladi\n"
            "⭕ Oddiy videoni Telegram aylana videosiga aylantiradi\n"
            "🖼 Aylana videoni 16:9 oddiy videoga aylantiradi\n"
            "💰 Balans va Telegram Stars orqali to'lovni boshqaradi\n\n"
            f"⭕ Aylana video narxi: <b>{format_money(settings.circle_price)}</b>\n\n"
            f"⏱ Maksimal davomiylik: <b>{settings.max_duration_minutes // 60} soat</b>\n"
            f"📦 Tayyor fayl hajmi: <b>{settings.max_download_mb} MB gacha</b>\n\n"
            "<b>Qanday ishlatiladi?</b>\n"
            "1. Pastdagi kerakli tugmani bosing.\n"
            "2. Havola yoki media faylni yuboring.\n"
            "3. Bot tayyor faylni qaytaradi.\n\n"
            "Telegram videosini botga yuborish yoki forward qilish mumkin.",
            reply_markup=main_keyboard(),
        )

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await ensure_user(message, database)
        await message.answer(
            "<b>Botdan foydalanish:</b>\n\n"
            "📥 <b>Video yuklab olish</b> - YouTube yoki Instagram havolasini yuboring.\n"
            "🎵 <b>MP3 yuklab olish</b> - havola, video yoki audio yuboring.\n"
            "⭕ <b>Videoni aylana qilish</b> - video yuboring; xizmat pullik.\n"
            "🖼 <b>Aylanani oddiy video qilish</b> - video note yuboring.\n"
            "💰 <b>Balansim</b> - hisob va oxirgi amallar.\n"
            "⭐ <b>Hisob to'ldirish</b> - Telegram Stars orqali to'lov.\n\n"
            "/cancel - boshlangan amalni bekor qilish",
            reply_markup=main_keyboard(),
        )

    @router.message(Command("cancel"))
    @router.message(F.text.in_({CANCEL_BUTTON, "Bekor qilish"}))
    async def cancel_handler(message: Message, state: FSMContext) -> None:
        await state.clear()
        await message.answer("Amal bekor qilindi.", reply_markup=main_keyboard())

    @router.message(Command("balance"))
    @router.message(F.text.in_({BALANCE_BUTTON, "Hisobim"}))
    async def balance_handler(message: Message) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        balance = await database.get_balance(message.from_user.id)
        transactions = await database.recent_transactions(message.from_user.id)
        history = "\n".join(
            f"{'+' if amount > 0 else ''}{format_money(amount)} - {description}"
            for amount, _kind, description, _created_at in transactions
        )
        suffix = f"\n\nSo'nggi amallar:\n{history}" if history else ""
        await message.answer(
            f"Hisobingiz: {format_money(balance)}{suffix}",
            reply_markup=main_keyboard(),
        )

    @router.message(Command("buy"))
    @router.message(F.text.in_({BUY_BUTTON, "Hisob to'ldirish"}))
    async def buy_handler(message: Message) -> None:
        await ensure_user(message, database)
        if not settings.star_packages:
            await message.answer("Onlayn to'lov hozircha o'chirilgan.")
            return
        await message.answer(
            "Telegram Stars orqali paket tanlang yoki o'zingiz miqdor kiriting.\n"
            f"Minimal custom to'lov: {settings.custom_star_min} Stars.",
            reply_markup=star_packages_keyboard(settings.star_packages),
        )

    @router.callback_query(F.data == "stars_custom")
    async def custom_stars_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.from_user:
            return
        await database.ensure_user(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.full_name,
        )
        await state.set_state(MediaStates.custom_stars)
        await callback.message.answer(
            "Nechta Stars bilan hisob to'ldirmoqchisiz?\n"
            f"Minimal: {settings.custom_star_min} Stars.\n\n"
            "Masalan: 5",
            reply_markup=cancel_keyboard(),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("stars:"))
    async def stars_callback(callback: CallbackQuery, bot: Bot) -> None:
        if not callback.from_user or not callback.data:
            return
        try:
            _, stars_raw, credits_raw = callback.data.split(":", maxsplit=2)
            package = (int(stars_raw), int(credits_raw))
        except (ValueError, TypeError):
            await callback.answer("Paket noto'g'ri", show_alert=True)
            return
        if package not in settings.star_packages:
            await callback.answer("Bu paket mavjud emas", show_alert=True)
            return
        stars, credits = package
        await database.ensure_user(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.full_name,
        )
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title="Bot balansi",
            description=f"Hisobga {format_money(credits)} qo'shiladi",
            payload=f"stars:{stars}:{credits}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{format_money(credits)} balans", amount=stars)],
        )
        await callback.answer()

    @router.message(MediaStates.custom_stars)
    async def custom_stars_handler(
        message: Message,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        value = (message.text or "").strip().replace(" ", "")
        try:
            stars = int(value)
        except ValueError:
            await message.answer(
                "Faqat butun son kiriting.\n"
                f"Minimal: {settings.custom_star_min} Stars.",
                reply_markup=cancel_keyboard(),
            )
            return
        if stars < settings.custom_star_min:
            await message.answer(
                f"Minimal to'lov {settings.custom_star_min} Stars. "
                "Undan kam miqdor qabul qilinmaydi.",
                reply_markup=cancel_keyboard(),
            )
            return
        credits = custom_credits(stars, settings)
        await bot.send_invoice(
            chat_id=message.from_user.id,
            title="Bot balansi",
            description=f"Hisobga {format_money(credits)} qo'shiladi",
            payload=f"stars_custom:{stars}:{credits}",
            provider_token="",
            currency="XTR",
            prices=[LabeledPrice(label=f"{format_money(credits)} balans", amount=stars)],
        )
        await state.clear()
        await message.answer(
            "Invoice yuborildi. To'lovni tasdiqlang.",
            reply_markup=main_keyboard(),
        )

    @router.pre_checkout_query()
    async def pre_checkout_handler(query: PreCheckoutQuery) -> None:
        valid = False
        if query.invoice_payload:
            valid, _stars, _credits = parse_payment_payload(
                query.invoice_payload,
                currency=query.currency,
                total_amount=query.total_amount,
                settings=settings,
            )
        await query.answer(
            ok=valid,
            error_message=None if valid else "To'lov paketi eskirgan yoki noto'g'ri.",
        )

    @router.message(F.successful_payment)
    async def successful_payment_handler(message: Message) -> None:
        payment = message.successful_payment
        if not payment or not message.from_user:
            return
        valid, stars, credits = parse_payment_payload(
            payment.invoice_payload,
            currency=payment.currency,
            total_amount=payment.total_amount,
            settings=settings,
        )
        if not valid:
            logger.error("Invalid successful payment payload: %s", payment.invoice_payload)
            return
        payment_id = payment.telegram_payment_charge_id
        created = await database.create_pending_star_payment(
            message.from_user.id,
            stars=stars,
            credits=credits,
            external_id=payment_id,
        )
        if not created:
            balance = await database.get_balance(message.from_user.id)
            await message.answer(
                f"Bu to'lov oldin qayta ishlangan. Balans: {format_money(balance)}",
                reply_markup=main_keyboard(),
            )
            return
        status = await _show_payment_processing(message)
        confirmed, balance = await database.confirm_star_payment(
            payment_id,
            f"{stars} Telegram Stars orqali to'lov",
        )
        if confirmed:
            await _update_status(
                status,
                "✅ To'lov tekshirildi va ichki hisobga tushdi.\n"
                f"Yangi balans: {format_money(balance)}",
            )
        else:
            await _update_status(status, "To'lov allaqachon qayta ishlangan.")
        await message.answer("Menyu:", reply_markup=main_keyboard())

    @router.message(Command("addbalance"))
    async def add_balance_handler(message: Message) -> None:
        if not message.from_user or message.from_user.id not in settings.admin_ids:
            await message.answer("Bu komanda faqat admin uchun.")
            return
        parts = (message.text or "").split()
        if len(parts) != 3:
            await message.answer("Format: /addbalance USER_ID SUMMA")
            return
        try:
            user_id = int(parts[1])
            amount = int(parts[2])
            if amount <= 0:
                raise ValueError
        except ValueError:
            await message.answer("USER_ID va SUMMA musbat butun son bo'lishi kerak.")
            return
        _, balance = await database.add_balance(
            user_id,
            amount,
            f"Admin {message.from_user.id} hisobni to'ldirdi",
            kind="admin_credit",
        )
        await message.answer(
            f"{user_id} hisobiga {format_money(amount)} qo'shildi. "
            f"Yangi balans: {format_money(balance)}"
        )

    @router.message(F.text.in_({VIDEO_BUTTON, "Video yuklash"}))
    async def choose_video(message: Message, state: FSMContext) -> None:
        await ensure_user(message, database)
        await state.set_state(MediaStates.video_download)
        await message.answer(
            "📥 <b>Video yuklash</b>\n\n"
            "YouTube yoki Instagram havolasini yuboring.\n"
            "Telegram videosini fayl sifatida yuborish yoki forward qilish ham mumkin.",
            reply_markup=cancel_keyboard(),
        )

    @router.message(F.text.in_({MP3_BUTTON, "MP3 yuklash"}))
    async def choose_mp3(message: Message, state: FSMContext) -> None:
        await ensure_user(message, database)
        await state.set_state(MediaStates.mp3_download)
        await message.answer(
            "🎵 <b>MP3 tayyorlash</b>\n\n"
            "YouTube/Instagram havolasini, video yoki audio faylni yuboring.",
            reply_markup=cancel_keyboard(),
        )

    @router.message(F.text.in_({CIRCLE_BUTTON, "Aylana video qilish"}))
    async def choose_circle(message: Message, state: FSMContext) -> None:
        await ensure_user(message, database)
        await state.set_state(MediaStates.circle)
        await message.answer(
            "⭕ <b>Aylana video tayyorlash</b>\n\n"
            f"Narxi: <b>{format_money(settings.circle_price)}</b>\n"
            "Video yoki havolani yuboring. Natija ko'pi bilan 60 soniya bo'ladi.",
            reply_markup=cancel_keyboard(),
        )

    @router.message(F.text.in_({RECTANGLE_BUTTON, "Aylanani to'rtburchak qilish"}))
    async def choose_rectangle(message: Message, state: FSMContext) -> None:
        await ensure_user(message, database)
        await state.set_state(MediaStates.rectangle)
        await message.answer(
            "🖼 <b>Aylanani oddiy video qilish</b>\n\n"
            "Telegram aylana videosini (video note) yuboring. "
            "Natija 16:9 oddiy video bo'ladi.",
            reply_markup=cancel_keyboard(),
        )

    @router.message(MediaStates.video_download)
    async def download_video_handler(
        message: Message,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        status = await message.answer("⏳ Video yuklanmoqda...")
        try:
            with tempfile.TemporaryDirectory(
                prefix="video-",
                dir=settings.temp_dir,
            ) as temp:
                source = await _resolve_source(message, bot, services, Path(temp))
                await _check_output(source, settings)
                await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO)
                await message.answer_video(
                    FSInputFile(source),
                    caption="✅ Video tayyor.",
                    supports_streaming=True,
                    reply_markup=main_keyboard(),
                )
            await state.clear()
        except Exception as exc:
            await _show_error(message, exc)
        finally:
            await _delete_status(status)

    @router.message(MediaStates.mp3_download)
    async def download_mp3_handler(
        message: Message,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        status = await message.answer("⏳ 1/2: Audio yuklanmoqda...")
        try:
            with tempfile.TemporaryDirectory(
                prefix="mp3-",
                dir=settings.temp_dir,
            ) as temp:
                temp_dir = Path(temp)
                source = await _resolve_source(
                    message,
                    bot,
                    services,
                    temp_dir,
                    prefer_audio=True,
                )
                await _update_status(status, "⚙️ 2/2: MP3 tayyorlanmoqda...")
                await _check_duration(source, services)
                output = await services.media.to_mp3(source, temp_dir / "converted.mp3")
                await _check_output(output, settings)
                await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VOICE)
                await message.answer_audio(
                    FSInputFile(output),
                    title="Yuklangan audio",
                    caption="✅ MP3 tayyor.",
                    reply_markup=main_keyboard(),
                )
            await state.clear()
        except Exception as exc:
            await _show_error(message, exc)
        finally:
            await _delete_status(status)

    @router.message(MediaStates.circle)
    async def circle_handler(
        message: Message,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        charged = await database.charge(
            message.from_user.id,
            settings.circle_price,
            "Aylana video",
        )
        if not charged.success:
            await message.answer(
                f"Mablag' yetarli emas.\n"
                f"Balans: {format_money(charged.balance)}\n"
                f"Kerak: {format_money(settings.circle_price)}",
                reply_markup=main_keyboard(),
            )
            await state.clear()
            return

        status = None
        completed = False
        try:
            status = await message.answer("Aylana video tayyorlanmoqda...")
            with tempfile.TemporaryDirectory(
                prefix="circle-",
                dir=settings.temp_dir,
            ) as temp:
                temp_dir = Path(temp)
                source = await _resolve_source(
                    message,
                    bot,
                    services,
                    temp_dir,
                    allow_audio_upload=False,
                )
                output = await services.media.to_circle(
                    source,
                    temp_dir / "circle-output.mp4",
                )
                await _check_output(output, settings)
                info = await services.media.probe(output)
                await bot.send_chat_action(message.chat.id, ChatAction.UPLOAD_VIDEO_NOTE)
                await message.answer_video_note(
                    FSInputFile(output),
                    duration=min(60, max(1, int(info.duration))),
                    length=640,
                )
            completed = True
            await state.clear()
            await message.answer(
                f"Tayyor. Qolgan balans: {format_money(charged.balance)}",
                reply_markup=main_keyboard(),
            )
        except Exception as exc:
            await _show_error(message, exc)
        finally:
            if not completed and settings.circle_price:
                await database.add_balance(
                    message.from_user.id,
                    settings.circle_price,
                    "Aylana video xatosi uchun refund",
                    kind="refund",
                )
            await _delete_status(status)

    @router.message(MediaStates.rectangle)
    async def rectangle_handler(
        message: Message,
        state: FSMContext,
        bot: Bot,
    ) -> None:
        status = await message.answer("To'rtburchak video tayyorlanmoqda...")
        try:
            with tempfile.TemporaryDirectory(
                prefix="rectangle-",
                dir=settings.temp_dir,
            ) as temp:
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
        await message.answer(
            "Quyidagi tugmalardan kerakli xizmatni tanlang. "
            "Bot nima qilishini ko'rish uchun /help ni bosing.",
            reply_markup=main_keyboard(),
        )

    return router
