from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.redis import RedisStorage
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from bot.config import settings
from bot.database.session import create_schema, create_sessionmaker
from bot.handlers import build_root_router
from bot.observability import configure_sentry


async def health(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def build_dispatcher() -> Dispatcher:
    storage = RedisStorage.from_url(settings.redis_url)
    dispatcher = Dispatcher(storage=storage)
    dispatcher.include_router(build_root_router())
    return dispatcher


async def run_polling(bot: Bot, dispatcher: Dispatcher) -> None:
    await bot.delete_webhook(drop_pending_updates=False)
    await dispatcher.start_polling(bot)


async def run_webhook(bot: Bot, dispatcher: Dispatcher) -> None:
    if not settings.webhook_url:
        raise RuntimeError("WEBHOOK_URL berilmagan")
    webhook_path = "/telegram/webhook"
    await bot.set_webhook(
        f"{settings.webhook_url}{webhook_path}",
        secret_token=settings.webhook_secret,
        drop_pending_updates=False,
    )
    app = web.Application()
    app.router.add_get("/health", health)
    SimpleRequestHandler(
        dispatcher=dispatcher,
        bot=bot,
        secret_token=settings.webhook_secret,
    ).register(app, path=webhook_path)
    setup_application(app, dispatcher, bot=bot)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.host, settings.port)
    await site.start()
    logging.info("Webhook server started on %s:%s", settings.host, settings.port)
    await asyncio.Event().wait()


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    configure_sentry(settings.sentry_dsn)
    settings.prepare()
    await create_schema(settings.database_url)
    sessionmaker = create_sessionmaker(settings.database_url)
    bot = Bot(
        settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dispatcher = build_dispatcher()
    dispatcher["sessionmaker"] = sessionmaker
    try:
        if settings.webhook_url:
            await run_webhook(bot, dispatcher)
        else:
            await run_polling(bot, dispatcher)
    finally:
        await bot.session.close()
        await dispatcher.storage.close()


if __name__ == "__main__":
    asyncio.run(main())
