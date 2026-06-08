from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from bot.keyboards import image_tools_keyboard

router = Router(name="image_tools")


@router.message(Command("image_tools"))
async def image_tools_menu(message: Message) -> None:
    await message.answer("🖼 Rasm vositasini tanlang:", reply_markup=image_tools_keyboard())


@router.callback_query(F.data.startswith("img:"))
async def image_tool_callback(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "Rasm yuboring. Worker Pillow orqali sticker/upscale/background fallback qiladi."
        )
