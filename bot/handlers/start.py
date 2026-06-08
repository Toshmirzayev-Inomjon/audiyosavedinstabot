from __future__ import annotations

from aiogram import Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

router = Router(name="start")


@router.message(CommandStart())
async def start_handler(message: Message) -> None:
    await message.answer(
        "👋 Media Super App tayyor.\n\n"
        "YouTube, Instagram, TikTok, Pinterest, X/Twitter, Facebook yoki "
        "SoundCloud havolasini yuboring. Bot cache, navbat va progress bilan ishlaydi."
    )


@router.message(Command("help"))
async def help_handler(message: Message) -> None:
    await message.answer(
        "Qisqa qo'llanma:\n"
        "1. Havola yuboring.\n"
        "2. Video/MP3/Subtitr tanlang.\n"
        "3. Bot yuklashni navbatga qo'yadi va progress ko'rsatadi.\n"
        "4. Avval yuklangan havola cache orqali tez qaytadi."
    )
