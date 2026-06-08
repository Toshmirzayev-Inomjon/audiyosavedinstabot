from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.types import User as TelegramUser
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bot.database.models import Download, User
from bot.database.session import session_scope
from bot.keyboards import audio_tools_keyboard, download_keyboard
from bot.services.cache import CacheIdentity, get_cached_media, normalize_url
from bot.services.platforms import UnsupportedPlatformError, detect_platform
from bot.tasks.media_tasks import download_media_task

router = Router(name="downloaders")


def looks_like_url(text: str) -> bool:
    return text.startswith(("http://", "https://"))


async def ensure_user(session: AsyncSession, telegram_user: TelegramUser) -> User:
    existing = await session.scalar(select(User).where(User.id == telegram_user.id))
    if existing:
        return existing
    item = User(
        id=telegram_user.id,
        username=telegram_user.username,
        full_name=telegram_user.full_name,
    )
    session.add(item)
    return item


@router.message(F.text.func(lambda text: isinstance(text, str) and looks_like_url(text)))
async def link_handler(message: Message, state: FSMContext) -> None:
    url = message.text or ""
    try:
        platform = detect_platform(url)
    except UnsupportedPlatformError as exc:
        await message.answer(f"❌ {exc}")
        return
    normalized = normalize_url(url)
    await state.update_data(url=normalized, platform=platform)
    await message.answer(
        f"🔎 {platform} havolasi topildi.\nKerakli formatni tanlang:",
        reply_markup=download_keyboard(),
    )


@router.callback_query(F.data.startswith("dl:"))
async def download_choice(
    callback: CallbackQuery,
    state: FSMContext,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    if not callback.message:
        await callback.answer("Xabar topilmadi", show_alert=True)
        return
    data = await state.get_data()
    url = data.get("url")
    if not url:
        await callback.answer("Avval havola yuboring", show_alert=True)
        return
    _, media_type, quality = callback.data.split(":", maxsplit=2)
    if media_type == "subtitles":
        quality = "auto"
    await callback.answer("Navbatga qo'yilmoqda...")
    identity = CacheIdentity(url, media_type, quality)
    async with session_scope(sessionmaker) as session:
        user = await ensure_user(session, callback.from_user)
        cached = await get_cached_media(session, identity)
        if cached:
            if media_type == "audio":
                await callback.message.answer_audio(
                    cached.telegram_file_id,
                    caption="⚡ Cache orqali tez yuborildi.",
                    reply_markup=audio_tools_keyboard(),
                )
            elif media_type == "subtitles":
                await callback.message.answer_document(
                    cached.telegram_file_id,
                    caption="⚡ Cache orqali tez yuborildi.",
                )
            else:
                await callback.message.answer_video(
                    cached.telegram_file_id,
                    caption="⚡ Cache orqali tez yuborildi.",
                    supports_streaming=True,
                )
            return
        status = await callback.message.answer("⏳ Navbatga qo'shildi...")
        platform = detect_platform(url)
        job = Download(
            user_id=user.id,
            chat_id=callback.message.chat.id,
            status_message_id=status.message_id,
            original_url=url,
            normalized_url=url,
            platform=platform,
            media_type=media_type,
            quality=quality,
            status="queued",
        )
        session.add(job)
        await session.flush()
        download_media_task.delay(
            {
                "download_id": job.id,
                "user_id": user.id,
                "chat_id": callback.message.chat.id,
                "status_message_id": status.message_id,
                "normalized_url": url,
                "media_type": media_type,
                "quality": quality,
            }
        )
