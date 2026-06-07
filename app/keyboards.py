from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

VIDEO_BUTTON = "📥 Video yuklab olish"
MP3_BUTTON = "🎵 MP3 yuklab olish"
CIRCLE_BUTTON = "⭕ Videoni aylana qilish (pullik)"
RECTANGLE_BUTTON = "🖼 Aylanani oddiy video qilish"
BALANCE_BUTTON = "💰 Balansim"
BUY_BUTTON = "⭐ Hisob to'ldirish"
CANCEL_BUTTON = "❌ Bekor qilish"
CUSTOM_STARS_BUTTON = "✍️ O'zim kiritaman"


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=VIDEO_BUTTON), KeyboardButton(text=MP3_BUTTON)],
            [KeyboardButton(text=CIRCLE_BUTTON)],
            [KeyboardButton(text=RECTANGLE_BUTTON)],
            [KeyboardButton(text=BALANCE_BUTTON), KeyboardButton(text=BUY_BUTTON)],
        ],
        resize_keyboard=True,
        input_field_placeholder="Quyidagi xizmatlardan birini tanlang",
    )


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text=CANCEL_BUTTON)]],
        resize_keyboard=True,
    )


def star_packages_keyboard(
    packages: tuple[tuple[int, int], ...],
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for index in range(0, len(packages), 2):
        row = []
        for stars, credits in packages[index : index + 2]:
            row.append(
                InlineKeyboardButton(
                    text=f"{stars} ⭐ -> {credits:,} so'm",
                    callback_data=f"stars:{stars}:{credits}",
                )
            )
        rows.append(row)
    rows.append(
        [
            InlineKeyboardButton(
                text=CUSTOM_STARS_BUTTON,
                callback_data="stars_custom",
            )
        ]
    )
    return InlineKeyboardMarkup(
        inline_keyboard=rows,
    )
