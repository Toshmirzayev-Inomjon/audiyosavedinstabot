from __future__ import annotations

TEXTS = {
    "uz": {
        "welcome": (
            "<b>Assalomu alaykum!</b>\n\n"
            "Bot link orqali video va MP3 yuklaydi, qo'shiq nomi yoki ijrochi "
            "bo'yicha musiqa qidiradi, ovozli xabardan qo'shiq nomini aniqlaydi, "
            "video note tayyorlaydi. AI qo'shiq tarifini /tarif orqali ko'rish mumkin."
        ),
        "help": (
            "<b>Yordam</b>\n\n"
            "Video uchun havola yuboring. MP3 uchun havola yoki qo'shiq nomini "
            "yozing. Ovozli xabarda qo'shiq nomini aytsangiz, bot uni matnga "
            "aylantirib qidiradi. Aylana video va oddiy videoga o'tkazish bepul. "
            "/cancel aktiv amalni bekor qiladi. AI obuna uchun /tarif ni bosing."
        ),
    },
    "ru": {
        "welcome": (
            "<b>Здравствуйте!</b>\n\n"
            "Бот скачивает видео и MP3 по ссылке, ищет музыку по названию "
            "или исполнителю и делает круглые видео."
        ),
        "help": (
            "<b>Помощь</b>\n\n"
            "Для видео отправьте ссылку. Для MP3 отправьте ссылку или название "
            "песни. /cancel отменяет активную операцию."
        ),
    },
    "en": {
        "welcome": (
            "<b>Welcome!</b>\n\n"
            "The bot downloads video and MP3 by link, searches songs by title "
            "or artist, and creates Telegram video notes."
        ),
        "help": (
            "<b>Help</b>\n\n"
            "Send a link for video. Send a link or song name for MP3. /cancel "
            "stops the active operation."
        ),
    },
}


def text(language: str, key: str) -> str:
    return TEXTS.get(language, TEXTS["uz"]).get(key, TEXTS["uz"][key])
