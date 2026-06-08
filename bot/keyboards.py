from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


def download_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🎥 360p", callback_data="dl:video:360"),
                InlineKeyboardButton(text="🎥 720p", callback_data="dl:video:720"),
                InlineKeyboardButton(text="🎥 1080p", callback_data="dl:video:1080"),
            ],
            [
                InlineKeyboardButton(text="🎵 MP3", callback_data="dl:audio:audio"),
                InlineKeyboardButton(text="📝 Subtitr", callback_data="dl:subtitles:auto"),
            ],
        ]
    )


def audio_tools_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✂️ Audio Kesish", callback_data="audio:cut"),
                InlineKeyboardButton(text="🎙 Vokalni ajratish", callback_data="audio:vocal"),
            ],
            [
                InlineKeyboardButton(text="✏️ Taglarni tahrirlash", callback_data="audio:tags"),
            ],
        ]
    )


def image_tools_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✂️ Background Remove", callback_data="img:bg"),
                InlineKeyboardButton(text="⬆️ Upscale", callback_data="img:upscale"),
            ],
            [InlineKeyboardButton(text="🧩 Sticker Maker", callback_data="img:sticker")],
        ]
    )
