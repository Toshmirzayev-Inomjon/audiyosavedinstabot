from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.types import BotCommand, MenuButtonCommands, MenuButtonWebApp, WebAppInfo

from app.config import Settings
from app.database import Database
from app.handlers import Services, build_router
from app.jobs import JobManager
from app.services.downloader import DownloadService
from app.services.media import MediaService
from app.services.telegram_downloader import TelegramDownloadService
from app.tunnel import QuickTunnel, start_quick_tunnel
from app.webapp import start_web_app


async def configure_bot_profile(bot: Bot, webapp_public_url: str | None) -> None:
    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Botni ochish va xizmatlarni ko'rish"),
            BotCommand(command="help", description="Botdan foydalanish bo'yicha yordam"),
            BotCommand(command="balance", description="Balans va oxirgi amallar"),
            BotCommand(command="buy", description="Telegram Stars orqali hisob to'ldirish"),
            BotCommand(command="cancel", description="Joriy amalni bekor qilish"),
        ]
    )
    await bot.set_my_short_description(
        "YouTube va Instagram video/MP3 yuklash, aylana video tayyorlash boti."
    )
    await bot.set_my_description(
        "YouTube va Instagram havolasidan video yoki MP3 yuklaydi. "
        "Videoni Telegram aylana videosiga, aylana videoni esa oddiy 16:9 videoga "
        "aylantiradi. Ishlash uchun /start ni bosing."
    )
    if webapp_public_url:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonWebApp(
                text="Open",
                web_app=WebAppInfo(url=webapp_public_url),
            )
        )
    else:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())


async def run() -> None:
    settings = Settings.load()
    settings.prepare_directories()

    database = Database(
        settings.database_url or settings.database_path,
        settings.initial_balance,
    )
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
        await configure_bot_profile(bot, webapp_public_url)
        await bot.delete_webhook(drop_pending_updates=False)
        await dispatcher.start_polling(bot)
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
