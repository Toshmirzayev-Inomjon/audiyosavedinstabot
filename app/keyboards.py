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
HISTORY_BUTTON = "🕘 Yuklash tarixi"
PREMIUM_BUTTON = "💎 Premium"
LANGUAGE_BUTTON = "🌐 Til / Language"

MENU_LABELS = {
    "uz": {
        "video": VIDEO_BUTTON,
        "mp3": MP3_BUTTON,
        "circle": CIRCLE_BUTTON,
        "rectangle": RECTANGLE_BUTTON,
        "balance": BALANCE_BUTTON,
        "buy": BUY_BUTTON,
        "history": HISTORY_BUTTON,
        "premium": PREMIUM_BUTTON,
        "language": LANGUAGE_BUTTON,
        "placeholder": "Quyidagi xizmatlardan birini tanlang",
    },
    "ru": {
        "video": "📥 Скачать видео",
        "mp3": "🎵 Скачать MP3",
        "circle": "⭕ Сделать круглое видео",
        "rectangle": "🖼 Сделать обычное видео",
        "balance": "💰 Мой баланс",
        "buy": "⭐ Пополнить баланс",
        "history": "🕘 История загрузок",
        "premium": "💎 Премиум",
        "language": LANGUAGE_BUTTON,
        "placeholder": "Выберите услугу",
    },
    "en": {
        "video": "📥 Download video",
        "mp3": "🎵 Download MP3",
        "circle": "⭕ Make video note",
        "rectangle": "🖼 Make regular video",
        "balance": "💰 My balance",
        "buy": "⭐ Add balance",
        "history": "🕘 Download history",
        "premium": "💎 Premium",
        "language": LANGUAGE_BUTTON,
        "placeholder": "Choose a service",
    },
}


def main_keyboard(language: str = "uz") -> ReplyKeyboardMarkup:
    labels = MENU_LABELS.get(language, MENU_LABELS["uz"])
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=labels["video"]), KeyboardButton(text=labels["mp3"])],
            [KeyboardButton(text=labels["circle"])],
            [KeyboardButton(text=labels["rectangle"])],
            [KeyboardButton(text=labels["balance"]), KeyboardButton(text=labels["buy"])],
            [
                KeyboardButton(text=labels["history"]),
                KeyboardButton(text=labels["premium"]),
            ],
            [KeyboardButton(text=labels["language"])],
        ],
        resize_keyboard=True,
        input_field_placeholder=labels["placeholder"],
    )


def quality_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="360p", callback_data="quality:360"),
                InlineKeyboardButton(text="720p", callback_data="quality:720"),
                InlineKeyboardButton(text="1080p", callback_data="quality:1080"),
            ],
            [
                InlineKeyboardButton(
                    text="🎵 Faqat audio (MP3)",
                    callback_data="quality:audio",
                )
            ],
        ]
    )


def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang:uz"),
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en"),
            ]
        ]
    )


def history_keyboard(items: list[tuple[int, str]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"↻ {title[:35]}",
                    callback_data=f"history:{download_id}",
                )
            ]
            for download_id, title in items
        ]
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
