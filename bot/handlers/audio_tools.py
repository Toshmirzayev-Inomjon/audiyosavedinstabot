from __future__ import annotations

from aiogram import F, Router
from aiogram.types import CallbackQuery

router = Router(name="audio_tools")


@router.callback_query(F.data.startswith("audio:"))
async def audio_tool_callback(callback: CallbackQuery) -> None:
    tool = callback.data.split(":", maxsplit=1)[1] if callback.data else ""
    messages = {
        "cut": "✂️ Kesish uchun format: 00:10 00:30 deb yuboring.",
        "vocal": "🎙 Vokal ajratish navbat orqali FFmpeg/Demucs workerga ulanadi.",
        "tags": "✏️ Tag format: Artist - Title deb yuboring.",
    }
    await callback.answer()
    if callback.message:
        await callback.message.answer(messages.get(tool, "Audio tool tayyor."))
