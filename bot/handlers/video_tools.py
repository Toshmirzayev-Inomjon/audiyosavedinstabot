from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="video_tools")


@router.message(Command("video_tools"))
async def video_tools_menu(message: Message) -> None:
    await message.answer(
        "🎞 Video tools:\n"
        "- Compressor\n"
        "- Video to GIF\n"
        "- Muter\n"
        "- Reverse\n\n"
        "Video yuboring va kerakli amalni tanlang."
    )
