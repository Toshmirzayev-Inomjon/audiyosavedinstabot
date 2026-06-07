from __future__ import annotations

import asyncio
import logging
import mimetypes
import secrets
import shutil
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
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
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardRemove,
)

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
    star_packages_keyboard,
    tariff_confirm_keyboard,
    tariff_keyboard,
)
from app.services.downloader import (
    DownloadCancelled,
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

VIDEO_LABELS = {labels["video"] for labels in MENU_LABELS.values()}
MP3_LABELS = {labels["mp3"] for labels in MENU_LABELS.values()}
CIRCLE_LABELS = {labels["circle"] for labels in MENU_LABELS.values()}
RECTANGLE_LABELS = {labels["rectangle"] for labels in MENU_LABELS.values()}
BALANCE_LABELS = {labels["balance"] for labels in MENU_LABELS.values()}
BUY_LABELS = {labels["buy"] for labels in MENU_LABELS.values()}
HISTORY_LABELS = {labels["history"] for labels in MENU_LABELS.values()}
PREMIUM_LABELS = {labels["premium"] for labels in MENU_LABELS.values()}
TARIFF_LABELS = {labels["tariff"] for labels in MENU_LABELS.values()}
LANGUAGE_LABELS = {labels["language"] for labels in MENU_LABELS.values()}


class MediaStates(StatesGroup):
    video_quality = State()
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
    jobs: JobManager
    public_base_url: str | None = None


def format_money(amount: int) -> str:
    return f"{amount:,}".replace(",", " ") + " so'm"


def custom_credits(stars: int, settings: Settings) -> int:
    return stars * settings.star_credit_rate


def _tariff_period_seconds(settings: Settings) -> int:
    return settings.tariff_period_days * 24 * 60 * 60


def _tariff_name(plan_code: str) -> str:
    return {
        "free": "Bepul",
        "standard": "Standard",
        "premium": "Premium",
    }.get(plan_code, plan_code.title())


def _tariff_price(plan_code: str, settings: Settings) -> int:
    return {
        "standard": settings.tariff_standard_price,
        "premium": settings.tariff_premium_price,
    }[plan_code]


def _tariff_stars(plan_code: str, settings: Settings) -> int:
    return {
        "standard": settings.tariff_standard_stars,
        "premium": settings.tariff_premium_stars,
    }[plan_code]


def _parse_tariff_stars_payload(
    payload: str,
    *,
    currency: str,
    total_amount: int,
    settings: Settings,
) -> tuple[bool, str, int]:
    parts = payload.split(":")
    if len(parts) != 3 or parts[0] != "tariff_stars" or currency != "XTR":
        return False, "", 0
    plan_code = parts[1]
    if plan_code not in {"standard", "premium"}:
        return False, "", 0
    try:
        stars = int(parts[2])
    except ValueError:
        return False, "", 0
    valid = stars == _tariff_stars(plan_code, settings) == total_amount
    return valid, plan_code, stars


def _tariff_catalog_text(settings: Settings) -> str:
    return (
        "📋 <b>Tarifni tanlang</b>\n\n"
        f"🆓 <b>Bepul</b> — {settings.tariff_period_days} kun\n"
        f"Kuniga {settings.daily_free_limit} ta yuklash, 720p gacha.\n\n"
        f"⚡ <b>Standard</b> — "
        f"{format_money(settings.tariff_standard_price)} / "
        f"{settings.tariff_period_days} kun\n"
        f"Yoki {settings.tariff_standard_stars} Telegram Stars.\n"
        f"Kuniga {settings.tariff_standard_daily_limit} ta yuklash, "
        "720p gacha.\n\n"
        f"💎 <b>Premium</b> — "
        f"{format_money(settings.tariff_premium_price)} / "
        f"{settings.tariff_period_days} kun\n"
        f"Yoki {settings.tariff_premium_stars} Telegram Stars.\n"
        "Limitsiz yuklash va 1080p.\n\n"
        "Pullik tarifni ichki balans yoki Telegram Stars bilan to'lash mumkin."
    )


def _tariff_markup(settings: Settings) -> InlineKeyboardMarkup:
    return tariff_keyboard(
        settings.tariff_standard_price,
        settings.tariff_premium_price,
        settings.tariff_period_days,
    )


async def _require_active_tariff(
    message: Message,
    database: Database,
    settings: Settings,
) -> bool:
    if not message.from_user:
        return False
    if await database.get_active_tariff(message.from_user.id):
        return True
    await message.answer(
        "Tarifingiz faol emas. Xizmatlardan foydalanish uchun tarif tanlang.",
        reply_markup=ReplyKeyboardRemove(),
    )
    await message.answer(
        _tariff_catalog_text(settings),
        reply_markup=_tariff_markup(settings),
    )
    return False


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
    quality: str = "720",
    progress=None,
    cancel_event: asyncio.Event | None = None,
) -> Path:
    if message.text and message.text != CANCEL_BUTTON:
        url = _validate_text_url(message.text)
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
        if message.from_user and message.text:
            parts = message.text.split(maxsplit=1)
            if len(parts) == 2 and parts[1].startswith("ref_"):
                try:
                    inviter_id = int(parts[1][4:])
                except ValueError:
                    inviter_id = 0
                if inviter_id:
                    await database.apply_referral(
                        message.from_user.id,
                        inviter_id,
                        inviter_reward=settings.referral_reward,
                        invitee_reward=settings.referral_new_user_reward,
                    )
        language = (
            await database.get_language(message.from_user.id)
            if message.from_user
            else "uz"
        )
        tariff = (
            await database.get_active_tariff(message.from_user.id)
            if message.from_user
            else None
        )
        if not tariff:
            await message.answer(
                i18n_text(language, "welcome"),
                reply_markup=ReplyKeyboardRemove(),
            )
            await message.answer(
                _tariff_catalog_text(settings),
                reply_markup=_tariff_markup(settings),
            )
            return
        tariff_expiry = datetime.fromtimestamp(
            tariff.expires_at,
            UTC,
        ).strftime("%Y-%m-%d")
        daily_limit = await database.tariff_daily_limit(
            message.from_user.id,
            free_limit=settings.daily_free_limit,
            standard_limit=settings.tariff_standard_daily_limit,
        )
        daily_text = (
            "♾ Kunlik yuklash: <b>limitsiz</b>"
            if daily_limit < 0
            else f"🎁 Kunlik yuklash: <b>{daily_limit} ta</b>"
        )
        await message.answer(
            i18n_text(language, "welcome")
            + "\n\n"
            f"📋 Tarif: <b>{_tariff_name(tariff.plan_code)}</b> "
            f"({tariff_expiry} gacha)\n"
            f"{daily_text}\n"
            f"⭕ Aylana video narxi: <b>{format_money(settings.circle_price)}</b>\n\n"
            f"⏱ Maksimal davomiylik: <b>{settings.max_duration_minutes // 60} soat</b>\n"
            f"📦 Media limiti: <b>{settings.max_download_mb} MB gacha</b>",
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
        await message.answer(
            i18n_text(language, "help"),
            reply_markup=main_keyboard(language),
        )

    @router.message(Command("cancel"))
    @router.message(F.text.in_({CANCEL_BUTTON, "Bekor qilish"}))
    async def cancel_handler(message: Message, state: FSMContext) -> None:
        cancelled = False
        if message.from_user:
            cancelled = await services.jobs.cancel(message.from_user.id)
        await state.clear()
        await message.answer(
            "Aktiv yuklash bekor qilinmoqda."
            if cancelled
            else "Amal bekor qilindi.",
            reply_markup=main_keyboard(),
        )

    @router.message(Command("balance"))
    @router.message(F.text.in_(BALANCE_LABELS | {"Hisobim"}))
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
    @router.message(F.text.in_(BUY_LABELS | {"Hisob to'ldirish"}))
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

    @router.message(F.text.in_(TARIFF_LABELS | {"Tariflar"}))
    @router.message(Command("tarif"))
    async def tariff_handler(message: Message) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        tariff = await database.get_active_tariff(message.from_user.id)
        status = "Faol tarif yo'q."
        if tariff:
            expiry = datetime.fromtimestamp(
                tariff.expires_at,
                UTC,
            ).strftime("%Y-%m-%d")
            status = (
                f"Joriy tarif: <b>{_tariff_name(tariff.plan_code)}</b>\n"
                f"Amal qilish muddati: <b>{expiry}</b>"
            )
        await message.answer(
            f"{status}\n\n{_tariff_catalog_text(settings)}",
            reply_markup=_tariff_markup(settings),
        )

    @router.callback_query(F.data.startswith("tariff:"))
    async def tariff_callback(callback: CallbackQuery) -> None:
        if not callback.data:
            return
        await database.ensure_user(
            callback.from_user.id,
            callback.from_user.username,
            callback.from_user.full_name,
        )
        plan_code = callback.data.split(":", maxsplit=1)[1]
        if plan_code == "list":
            await callback.message.answer(
                _tariff_catalog_text(settings),
                reply_markup=_tariff_markup(settings),
            )
            await callback.answer()
            return
        if plan_code == "free":
            result = await database.activate_free_tariff(
                callback.from_user.id,
                period_seconds=_tariff_period_seconds(settings),
            )
            if result.success and result.expires_at:
                expiry = datetime.fromtimestamp(
                    result.expires_at,
                    UTC,
                ).strftime("%Y-%m-%d")
                await callback.message.answer(
                    "🆓 Bepul tarif faollashtirildi.\n"
                    f"Amal qilish muddati: <b>{expiry}</b>",
                    reply_markup=main_keyboard(
                        await database.get_language(callback.from_user.id)
                    ),
                )
            elif result.reason == "free_used":
                await callback.message.answer(
                    "Bepul tarifdan oldin foydalanilgansiz. "
                    "Standard yoki Premium tarifni tanlang.",
                    reply_markup=_tariff_markup(settings),
                )
            else:
                await callback.message.answer(
                    "Sizda hozir faol tarif mavjud. /tarif orqali holatini ko'ring.",
                    reply_markup=main_keyboard(
                        await database.get_language(callback.from_user.id)
                    ),
                )
            await callback.answer()
            return
        if plan_code not in {"standard", "premium"}:
            await callback.answer("Tarif noto'g'ri", show_alert=True)
            return
        balance = await database.get_balance(callback.from_user.id)
        price = _tariff_price(plan_code, settings)
        await callback.message.answer(
            f"{_tariff_name(plan_code)} tarif: "
            f"<b>{format_money(price)}</b>\n"
            f"Stars narxi: <b>{_tariff_stars(plan_code, settings)} ⭐</b>\n"
            f"Muddat: <b>{settings.tariff_period_days} kun</b>\n"
            f"Balansingiz: <b>{format_money(balance)}</b>\n\n"
            "To'lov usulini tanlang:",
            reply_markup=tariff_confirm_keyboard(
                plan_code,
                _tariff_stars(plan_code, settings),
            ),
        )
        await callback.answer()

    @router.callback_query(F.data.startswith("tariff_buy:"))
    async def tariff_buy_callback(callback: CallbackQuery) -> None:
        if not callback.data:
            return
        plan_code = callback.data.split(":", maxsplit=1)[1]
        if plan_code not in {"standard", "premium"}:
            await callback.answer("Tarif noto'g'ri", show_alert=True)
            return
        result = await database.purchase_tariff(
            callback.from_user.id,
            plan_code=plan_code,
            price=_tariff_price(plan_code, settings),
            period_seconds=_tariff_period_seconds(settings),
        )
        if result.success and result.expires_at:
            expiry = datetime.fromtimestamp(
                result.expires_at,
                UTC,
            ).strftime("%Y-%m-%d")
            await callback.message.answer(
                f"✅ {_tariff_name(plan_code)} tarif sotib olindi.\n"
                f"Amal qilish muddati: <b>{expiry}</b>\n"
                f"Qolgan balans: <b>{format_money(result.balance)}</b>",
                reply_markup=main_keyboard(
                    await database.get_language(callback.from_user.id)
                ),
            )
        elif result.reason == "insufficient":
            await callback.message.answer(
                "Balans yetarli emas.\n"
                f"Balans: <b>{format_money(result.balance)}</b>\n"
                f"Kerak: <b>{format_money(_tariff_price(plan_code, settings))}</b>\n\n"
                "Avval hisobni Telegram Stars orqali to'ldiring.",
                reply_markup=star_packages_keyboard(settings.star_packages),
            )
        elif result.reason == "higher_active":
            await callback.message.answer(
                "Sizda bundan yuqori tarif faol. Past tarifga o'tishda "
                "balansdan pul yechilmadi.",
                reply_markup=main_keyboard(
                    await database.get_language(callback.from_user.id)
                ),
            )
        else:
            await callback.message.answer(
                "Bu tarif hozir faol. Takroriy bosish uchun pul yechilmadi.",
                reply_markup=main_keyboard(
                    await database.get_language(callback.from_user.id)
                ),
            )
        await callback.answer()

    @router.callback_query(F.data.startswith("tariff_stars:"))
    async def tariff_stars_callback(callback: CallbackQuery, bot: Bot) -> None:
        if not callback.data:
            return
        plan_code = callback.data.split(":", maxsplit=1)[1]
        if plan_code not in {"standard", "premium"}:
            await callback.answer("Tarif noto'g'ri", show_alert=True)
            return
        active = await database.get_active_tariff(callback.from_user.id)
        if active and active.plan_code == "premium" and plan_code == "standard":
            await callback.answer(
                "Premium faol paytda Standard tarifga o'tib bo'lmaydi.",
                show_alert=True,
            )
            return
        stars = _tariff_stars(plan_code, settings)
        await bot.send_invoice(
            chat_id=callback.from_user.id,
            title=f"{_tariff_name(plan_code)} tarif",
            description=(
                f"{settings.tariff_period_days} kunlik "
                f"{_tariff_name(plan_code)} tarif"
            ),
            payload=f"tariff_stars:{plan_code}:{stars}",
            provider_token="",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label=f"{_tariff_name(plan_code)} tarif",
                    amount=stars,
                )
            ],
        )
        await callback.answer()

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
        await callback.message.answer(
            texts[language],
            reply_markup=main_keyboard(language),
        )
        await callback.answer()

    @router.message(F.text.in_(PREMIUM_LABELS | {"Premium"}))
    @router.message(Command("premium"))
    async def premium_handler(message: Message, bot: Bot) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        until = await database.premium_until(message.from_user.id)
        if until and until > int(datetime.now(UTC).timestamp()):
            expiry = datetime.fromtimestamp(until, UTC).strftime("%Y-%m-%d")
            await message.answer(
                f"💎 Premium faol.\nAmal qilish muddati: {expiry}",
                reply_markup=main_keyboard(),
            )
            return
        invoice_url = await bot.create_invoice_link(
            title="Saved Insta Premium",
            description=(
                "Kunlik limitsiz yuklash, ustuvor navbat va 1080p imkoniyati. "
                "Obuna har 30 kunda avtomatik yangilanadi."
            ),
            payload=f"premium:{settings.premium_stars}",
            provider_token="",
            currency="XTR",
            prices=[
                LabeledPrice(
                    label="30 kunlik Premium",
                    amount=settings.premium_stars,
                )
            ],
            subscription_period=30 * 24 * 60 * 60,
        )
        await message.answer(
            "💎 30 kunlik Premium obunani Telegram Stars orqali faollashtiring:",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text=f"💎 {settings.premium_stars} Stars bilan olish",
                            url=invoice_url,
                        )
                    ]
                ]
            ),
        )

    @router.message(Command("referral"))
    async def referral_handler(message: Message, bot: Bot) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        me = await bot.get_me()
        count, earned = await database.referral_stats(message.from_user.id)
        link = f"https://t.me/{me.username}?start=ref_{message.from_user.id}"
        await message.answer(
            "🎁 <b>Referral dasturi</b>\n\n"
            f"Takliflar: {count} ta\n"
            f"Topilgan bonus: {format_money(earned)}\n\n"
            f"Do'stlaringizga yuboring:\n<code>{link}</code>"
        )

    @router.message(Command("promo"))
    async def promo_handler(message: Message) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        parts = (message.text or "").split(maxsplit=1)
        if len(parts) != 2:
            await message.answer("Format: /promo KOD")
            return
        ok, text, balance = await database.redeem_promo(
            message.from_user.id,
            parts[1],
        )
        suffix = f"\nYangi balans: {format_money(balance)}" if ok else ""
        await message.answer(text + suffix, reply_markup=main_keyboard())

    @router.message(Command("createpromo"))
    async def create_promo_handler(message: Message) -> None:
        if not message.from_user or message.from_user.id not in settings.admin_ids:
            await message.answer("Bu komanda faqat admin uchun.")
            return
        parts = (message.text or "").split()
        if len(parts) != 4:
            await message.answer("Format: /createpromo KOD SUMMA LIMIT")
            return
        try:
            credits, max_uses = int(parts[2]), int(parts[3])
            await database.create_promo(parts[1], credits, max_uses)
        except ValueError:
            await message.answer("SUMMA va LIMIT musbat butun son bo'lishi kerak.")
            return
        await message.answer(f"Promo kod yaratildi: <code>{parts[1].upper()}</code>")

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
        tariff_valid, tariff_plan, _tariff_stars_amount = (
            _parse_tariff_stars_payload(
                query.invoice_payload,
                currency=query.currency,
                total_amount=query.total_amount,
                settings=settings,
            )
        )
        if tariff_valid:
            active = await database.get_active_tariff(query.from_user.id)
            if active and active.plan_code == "premium" and tariff_plan == "standard":
                await query.answer(
                    ok=False,
                    error_message="Premium faol paytda Standard tarif olinmaydi.",
                )
                return
        valid = tariff_valid or (
            query.currency == "XTR"
            and query.total_amount == settings.premium_stars
            and query.invoice_payload == f"premium:{settings.premium_stars}"
        )
        if query.invoice_payload and not valid:
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
        tariff_valid, tariff_plan, tariff_stars = _parse_tariff_stars_payload(
            payment.invoice_payload,
            currency=payment.currency,
            total_amount=payment.total_amount,
            settings=settings,
        )
        if tariff_valid:
            status = await _show_payment_processing(message)
            result = await database.activate_tariff_with_stars(
                message.from_user.id,
                plan_code=tariff_plan,
                stars=tariff_stars,
                charge_id=payment.telegram_payment_charge_id,
                period_seconds=_tariff_period_seconds(settings),
            )
            if result.expires_at:
                expiry = datetime.fromtimestamp(
                    result.expires_at,
                    UTC,
                ).strftime("%Y-%m-%d")
                text = (
                    f"✅ {_tariff_name(tariff_plan)} tarif Stars orqali "
                    f"faollashtirildi.\nAmal qilish muddati: <b>{expiry}</b>"
                    if result.success
                    else "Bu Stars to'lovi oldin qayta ishlangan. "
                    f"Tarif muddati: <b>{expiry}</b>"
                )
                await _update_status(status, text)
            await message.answer(
                "Menyu:",
                reply_markup=main_keyboard(
                    await database.get_language(message.from_user.id)
                ),
            )
            return
        if (
            payment.invoice_payload == f"premium:{settings.premium_stars}"
            and payment.currency == "XTR"
            and payment.total_amount == settings.premium_stars
        ):
            expires_at = await database.activate_premium(
                message.from_user.id,
                stars=settings.premium_stars,
                charge_id=payment.telegram_payment_charge_id,
            )
            expiry = datetime.fromtimestamp(expires_at, UTC).strftime("%Y-%m-%d")
            await message.answer(
                "💎 Premium faollashtirildi.\n"
                f"Amal qilish muddati: {expiry}",
                reply_markup=main_keyboard(),
            )
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

    @router.message(F.text.in_(VIDEO_LABELS | {"Video yuklash"}))
    async def choose_video(message: Message, state: FSMContext) -> None:
        await ensure_user(message, database)
        if not await _require_active_tariff(message, database, settings):
            await state.clear()
            return
        await state.set_state(MediaStates.video_quality)
        await message.answer(
            "📥 <b>Video sifatini tanlang</b>\n\n"
            "1080p hajmi katta bo'lishi mumkin. Premium foydalanuvchilar "
            "kunlik limitsiz foydalanadi.",
            reply_markup=quality_keyboard(),
        )

    @router.callback_query(MediaStates.video_quality, F.data.startswith("quality:"))
    async def quality_callback(callback: CallbackQuery, state: FSMContext) -> None:
        if not callback.data:
            return
        if not await database.get_active_tariff(callback.from_user.id):
            await state.clear()
            await callback.answer(
                "Tarif faol emas. /tarif orqali tarif tanlang.",
                show_alert=True,
            )
            return
        quality = callback.data.split(":", maxsplit=1)[1]
        if quality not in {"360", "720", "1080", "audio"}:
            await callback.answer("Sifat noto'g'ri", show_alert=True)
            return
        if quality == "1080" and not await database.is_premium(callback.from_user.id):
            await callback.answer(
                "1080p Premium foydalanuvchilar uchun.",
                show_alert=True,
            )
            return
        await state.update_data(quality=quality)
        await state.set_state(
            MediaStates.mp3_download if quality == "audio" else MediaStates.video_download
        )
        text = (
            "🎵 Havola, video yoki audio yuboring."
            if quality == "audio"
            else f"📥 {quality}p tanlandi. YouTube/Instagram havolasi yoki video yuboring."
        )
        await callback.message.answer(text, reply_markup=cancel_keyboard())
        await callback.answer()

    @router.message(F.text.in_(MP3_LABELS | {"MP3 yuklash"}))
    async def choose_mp3(message: Message, state: FSMContext) -> None:
        await ensure_user(message, database)
        if not await _require_active_tariff(message, database, settings):
            await state.clear()
            return
        await state.set_state(MediaStates.mp3_download)
        await message.answer(
            "🎵 <b>MP3 tayyorlash</b>\n\n"
            "YouTube/Instagram havolasini, video yoki audio faylni yuboring.",
            reply_markup=cancel_keyboard(),
        )

    @router.message(F.text.in_(HISTORY_LABELS | {"Yuklash tarixi"}))
    @router.message(Command("history"))
    async def history_handler(message: Message) -> None:
        await ensure_user(message, database)
        if not message.from_user:
            return
        if not await _require_active_tariff(message, database, settings):
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
        if not await database.get_active_tariff(callback.from_user.id):
            await callback.answer(
                "Tarif faol emas. /tarif orqali tarif tanlang.",
                show_alert=True,
            )
            return
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
        if not await _require_active_tariff(message, database, settings):
            await state.clear()
            return
        await state.set_state(MediaStates.circle)
        await message.answer(
            "⭕ <b>Aylana video tayyorlash</b>\n\n"
            f"Narxi: <b>{format_money(settings.circle_price)}</b>\n"
            "Video yoki havolani yuboring. Natija ko'pi bilan 60 soniya bo'ladi.",
            reply_markup=cancel_keyboard(),
        )

    @router.message(
        F.text.in_(RECTANGLE_LABELS | {"Aylanani to'rtburchak qilish"})
    )
    async def choose_rectangle(message: Message, state: FSMContext) -> None:
        await ensure_user(message, database)
        if not await _require_active_tariff(message, database, settings):
            await state.clear()
            return
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
        await ensure_user(message, database)
        if not message.from_user:
            return
        if not await _require_active_tariff(message, database, settings):
            await state.clear()
            return
        daily_limit = await database.tariff_daily_limit(
            message.from_user.id,
            free_limit=settings.daily_free_limit,
            standard_limit=settings.tariff_standard_daily_limit,
        )
        allowed, remaining = await database.reserve_daily_use(
            message.from_user.id,
            daily_limit,
        )
        if not allowed:
            await state.clear()
            await message.answer(
                "Bugungi bepul limitingiz tugadi. Ertaga qayta urinib ko'ring "
                "yoki Premium obuna oling.",
                reply_markup=main_keyboard(),
            )
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
        completed = False
        try:
            async def work(context: JobContext) -> tuple[Message, str]:
                await _update_status(status, "⏳ Yuklash boshlandi: 0%\n▱▱▱▱▱▱▱▱▱▱")
                progress = _ProgressUpdater(status)
                with tempfile.TemporaryDirectory(
                    prefix="video-",
                    dir=settings.temp_dir,
                ) as temp:
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
                        await bot.send_chat_action(
                            message.chat.id,
                            ChatAction.UPLOAD_VIDEO,
                        )
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
            completed = True
            await state.clear()
        except (DownloadCancelled, JobCancelled) as exc:
            await database.finish_download(
                download_id,
                status="cancelled",
                error_message=str(exc),
            )
            await state.clear()
            await message.answer("Yuklash bekor qilindi.", reply_markup=main_keyboard())
        except Exception as exc:
            await database.finish_download(
                download_id,
                status="failed",
                error_message=str(exc),
            )
            await database.log_error("video_download", str(exc), message.from_user.id)
            await _show_error(message, exc)
        finally:
            if not completed and remaining >= 0:
                await database.release_daily_use(message.from_user.id)
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
        if not await _require_active_tariff(message, database, settings):
            await state.clear()
            return
        daily_limit = await database.tariff_daily_limit(
            message.from_user.id,
            free_limit=settings.daily_free_limit,
            standard_limit=settings.tariff_standard_daily_limit,
        )
        allowed, remaining = await database.reserve_daily_use(
            message.from_user.id,
            daily_limit,
        )
        if not allowed:
            await state.clear()
            await message.answer(
                "Bugungi bepul limitingiz tugadi. Premium obuna kunlik limitni olib tashlaydi.",
                reply_markup=main_keyboard(),
            )
            return
        source_url = message.text.strip() if message.text else None
        download_id = await database.create_download(
            message.from_user.id,
            source_url=source_url,
            media_type="audio",
            quality="mp3",
        )
        status = await message.answer("⏳ Navbatga qo'shildi...")
        completed = False
        try:
            async def work(context: JobContext) -> tuple[Message, str]:
                progress = _ProgressUpdater(status)
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
                        await bot.send_chat_action(
                            message.chat.id,
                            ChatAction.UPLOAD_VOICE,
                        )
                        sent = await message.answer_audio(
                            FSInputFile(output),
                            title="Yuklangan audio",
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
            completed = True
            await state.clear()
        except (DownloadCancelled, JobCancelled) as exc:
            await database.finish_download(
                download_id,
                status="cancelled",
                error_message=str(exc),
            )
            await state.clear()
            await message.answer("Yuklash bekor qilindi.", reply_markup=main_keyboard())
        except Exception as exc:
            await database.finish_download(
                download_id,
                status="failed",
                error_message=str(exc),
            )
            await database.log_error("mp3_download", str(exc), message.from_user.id)
            await _show_error(message, exc)
        finally:
            if not completed and remaining >= 0:
                await database.release_daily_use(message.from_user.id)
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
        if not await _require_active_tariff(message, database, settings):
            await state.clear()
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
        await ensure_user(message, database)
        if not await _require_active_tariff(message, database, settings):
            await state.clear()
            return
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
                if output.stat().st_size > settings.telegram_upload_bytes:
                    if not message.from_user:
                        raise MediaConversionError("Foydalanuvchi aniqlanmadi")
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
                    await bot.send_chat_action(
                        message.chat.id,
                        ChatAction.UPLOAD_VIDEO,
                    )
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
        if not await _require_active_tariff(message, database, settings):
            return
        await message.answer(
            "Quyidagi tugmalardan kerakli xizmatni tanlang. "
            "Bot nima qilishini ko'rish uchun /help ni bosing.",
            reply_markup=main_keyboard(),
        )

    return router
