from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.types import (
    BotCommand,
    BotCommandScopeChat,
    MenuButtonCommands,
    MenuButtonWebApp,
    WebAppInfo,
)

from app.config import Settings
from app.database import Database
from app.handlers import Services, build_router
from app.jobs import JobManager
from app.services.ai import MusicGenerationService
from app.services.downloader import DownloadService
from app.services.media import MediaService
from app.services.speech import SpeechRecognitionService
from app.services.telegram_downloader import TelegramDownloadService
from app.tunnel import QuickTunnel, start_quick_tunnel
from app.webapp import start_web_app


async def configure_bot_profile(
    bot: Bot,
    webapp_public_url: str | None,
    admin_ids: frozenset[int] = frozenset(),
) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Botni ochish va xizmatlarni ko'rish"),
            BotCommand(command="help", description="Botdan foydalanish bo'yicha yordam"),
            BotCommand(command="history", description="Yuklash tarixini ko'rish"),
            BotCommand(command="ai", description="AI qo'shiq va obuna holati"),
            BotCommand(command="tarif", description="AI obuna tarifini ko'rish"),
            BotCommand(command="cancel", description="Joriy amalni bekor qilish"),
        ]
    )
    await bot.set_my_short_description(
        "Link, matn yoki ovozli xabar orqali video/MP3, musiqa va AI qo'shiq."
    )
    await bot.set_my_description(
        "Video va MP3 yuklash, qo'shiq nomi, ijrochi yoki ovozli xabar bo'yicha "
        "musiqa qidirish, aylana video tayyorlash va uni oddiy videoga o'tkazish. "
        "AI obuna faol bo'lsa matndan qo'shiq yaratadi. Open tugmasi orqali profil "
        "va so'rovlaringizni ko'ring."
    )
    for admin_id in admin_ids:
        try:
            await bot.set_my_commands(
                [
                    BotCommand(command="admin", description="Userlarni qidirish"),
                    BotCommand(
                        command="aiactivate",
                        description="AI obunani faollashtirish",
                    ),
                    BotCommand(command="start", description="Asosiy menyu"),
                ],
                scope=BotCommandScopeChat(chat_id=admin_id),
            )
        except Exception:
            logging.exception("Admin komandalarini sozlashda xato: %s", admin_id)
    if webapp_public_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Open",
                web_app=WebAppInfo(url=webapp_public_url),
            )
        )
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def run_polling_forever(
    *,
    bot: Bot,
    dispatcher: Dispatcher,
    webapp_public_url: str | None,
    admin_ids: frozenset[int] = frozenset(),
) -> None:
    while True:
        try:
            try:
                await configure_bot_profile(bot, webapp_public_url, admin_ids)
            except Exception:
                logging.exception("Bot profilini sozlashda xato")
            await bot.delete_webhook(drop_pending_updates=False)
            await dispatcher.start_polling(bot)
        except asyncio.CancelledError:
            raise
        except Exception:
            logging.exception("Bot polling to'xtadi, 30 soniyadan keyin qayta urinadi")
            await asyncio.sleep(30)


async def run() -> None:
    settings = Settings.load()
    settings.prepare_directories()

    database = Database(settings.database_url or settings.database_path)
    await database.initialize()

    telegram = TelegramDownloadService(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        bot_token=settings.bot_token,
        session_path=settings.telegram_session_path,
        max_bytes=settings.max_download_bytes,
    )
    services = Services(
        settings=settings,
        database=database,
        downloader=DownloadService(
            max_bytes=settings.max_download_bytes,
            max_duration_seconds=settings.max_duration_seconds,
            cookies_file=settings.cookies_file,
        ),
        media=MediaService(),
        telegram=telegram,
        jobs=JobManager(settings.queue_concurrency),
        music_ai=MusicGenerationService(
            api_token=settings.huggingface_api_token,
            model=settings.huggingface_music_model,
        ),
        speech=SpeechRecognitionService(
            api_token=settings.huggingface_api_token,
            model=settings.huggingface_asr_model,
        ),
    )

    session = None
    if settings.bot_api_base:
        api_server = TelegramAPIServer.from_base(
            settings.bot_api_base,
            is_local=settings.bot_api_local,
        )
        session = AiohttpSession(api=api_server)
        logging.info(
            "Bot API server: %s (local=%s)",
            settings.bot_api_base,
            settings.bot_api_local,
        )

    bot = Bot(
        settings.bot_token,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = Dispatcher()
    dispatcher.include_router(build_router(services))
    web_runner = await start_web_app(
        settings=settings,
        database=database,
        bot=bot,
        services=services,
    )
    tunnel: QuickTunnel | None = None
    webapp_public_url = settings.webapp_public_url
    if not webapp_public_url:
        try:
            tunnel = await start_quick_tunnel(settings.webapp_port)
            webapp_public_url = tunnel.url
        except Exception:
            logging.exception(
                "Vaqtinchalik WebApp tunnelini ishga tushirib bo'lmadi"
            )
    services.public_base_url = webapp_public_url

    if not MediaService.available():
        logging.warning("ffmpeg/ffprobe topilmadi: konvertatsiya funksiyalari ishlamaydi")
    if settings.telegram_links_enabled:
        await telegram.start()
    else:
        logging.warning(
            "TELEGRAM_API_ID/HASH berilmagan: Telegram post havolalari o'chirilgan"
        )

    try:
        await run_polling_forever(
            bot=bot,
            dispatcher=dispatcher,
            webapp_public_url=webapp_public_url,
            admin_ids=settings.admin_ids,
        )
    finally:
        if tunnel is not None:
            await tunnel.stop()
        await web_runner.cleanup()
        await telegram.stop()
        await bot.session.close()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    asyncio.run(run())


if __name__ == "__main__":
    main()
