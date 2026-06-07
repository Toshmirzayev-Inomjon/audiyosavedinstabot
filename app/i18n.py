from __future__ import annotations

TEXTS = {
    "uz": {
        "welcome": (
            "<b>Assalomu alaykum!</b>\n\n"
            "YouTube va Instagram video/MP3 yuklash, video note tayyorlash, "
            "tarix, Premium va balans xizmatlari mavjud."
        ),
        "help": (
            "<b>Yordam</b>\n\n"
            "Kerakli xizmat tugmasini bosing, sifatni tanlang va havola yoki "
            "media yuboring. /cancel aktiv amalni bekor qiladi."
        ),
    },
    "ru": {
        "welcome": (
            "<b>Здравствуйте!</b>\n\n"
            "Доступны загрузка видео/MP3 из YouTube и Instagram, создание "
            "круглых видео, история, Premium и баланс."
        ),
        "help": (
            "<b>Помощь</b>\n\n"
            "Выберите услугу и качество, затем отправьте ссылку или медиа. "
            "/cancel отменяет активную операцию."
        ),
    },
    "en": {
        "welcome": (
            "<b>Welcome!</b>\n\n"
            "You can download YouTube and Instagram video/MP3, create video "
            "notes, access history, Premium and balance features."
        ),
        "help": (
            "<b>Help</b>\n\n"
            "Choose a service and quality, then send a link or media file. "
            "/cancel stops the active operation."
        ),
    },
}


def text(language: str, key: str) -> str:
    return TEXTS.get(language, TEXTS["uz"]).get(key, TEXTS["uz"][key])
