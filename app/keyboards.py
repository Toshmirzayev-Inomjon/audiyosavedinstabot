from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

VIDEO_BUTTON = "📥 Video yuklab olish"
MP3_BUTTON = "🎵 MP3 yuklab olish"
MUSIC_SEARCH_BUTTON = "🔎 Musiqa qidirish"
CIRCLE_BUTTON = "⭕ Videoni aylana qilish"
RECTANGLE_BUTTON = "🖼 Aylanani oddiy video qilish"
CANCEL_BUTTON = "❌ Bekor qilish"
HISTORY_BUTTON = "🕘 Yuklash tarixi"
LANGUAGE_BUTTON = "🌐 Til / Language"

MENU_LABELS = {
    "uz": {
        "video": VIDEO_BUTTON,
        "mp3": MP3_BUTTON,
        "music_search": MUSIC_SEARCH_BUTTON,
        "circle": CIRCLE_BUTTON,
        "rectangle": RECTANGLE_BUTTON,
        "history": HISTORY_BUTTON,
        "language": LANGUAGE_BUTTON,
        "placeholder": "Link yoki musiqa nomi yuboring",
    },
    "ru": {
        "video": "📥 Скачать видео",
        "mp3": "🎵 Скачать MP3",
        "music_search": "🔎 Поиск музыки",
        "circle": "⭕ Сделать круглое видео",
        "rectangle": "🖼 Сделать обычное видео",
        "history": "🕘 История загрузок",
        "language": LANGUAGE_BUTTON,
        "placeholder": "Отправьте ссылку или название песни",
    },
    "en": {
        "video": "📥 Download video",
        "mp3": "🎵 Download MP3",
        "music_search": "🔎 Search music",
        "circle": "⭕ Make video note",
        "rectangle": "🖼 Make regular video",
        "history": "🕘 Download history",
        "language": LANGUAGE_BUTTON,
        "placeholder": "Send a link or song name",
    },
}


def main_keyboard(language: str = "uz") -> ReplyKeyboardMarkup:
    labels = MENU_LABELS.get(language, MENU_LABELS["uz"])
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=labels["video"]), KeyboardButton(text=labels["mp3"])],
            [KeyboardButton(text=labels["music_search"])],
            [KeyboardButton(text=labels["circle"]), KeyboardButton(text=labels["rectangle"])],
            [
                KeyboardButton(text=labels["history"]),
                KeyboardButton(text=labels["language"]),
            ],
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
