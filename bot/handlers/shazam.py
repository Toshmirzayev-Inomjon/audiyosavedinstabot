from __future__ import annotations

import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.types import Message

from bot.config import settings
from bot.services.shazam import RecognitionError, recognize_with_audd

router = Router(name="shazam")


@router.message(F.voice)
async def voice_recognition_handler(message: Message) -> None:
    if not message.voice:
        return
    status = await message.answer("🎧 Ovoz qabul qilindi, qo'shiq aniqlanmoqda...")
    with tempfile.TemporaryDirectory(dir=settings.storage_dir) as raw_temp:
        path = Path(raw_temp) / "voice.ogg"
        await message.bot.download(message.voice, destination=path)
        try:
            result = await recognize_with_audd(path, settings.audd_api_key)
        except RecognitionError:
            await status.edit_text(
                "🎧 Local rejim: qo'shiqni aniq tanish uchun AUDD_API_KEY kerak. "
                "Ovoz saqlandi, lekin tashqi tanish API ulanmagan."
            )
            return
    await status.edit_text(
        "✅ Qo'shiq topildi:\n"
        f"Artist: {result.get('artist')}\n"
        f"Title: {result.get('title')}\n\n"
        "Keyingi bosqich: YouTube Music cache orqali MP3 tayyorlash."
    )
