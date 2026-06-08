from aiogram import Router

from bot.handlers import audio_tools, downloaders, image_tools, shazam, start, video_tools


def build_root_router() -> Router:
    router = Router(name="root")
    router.include_router(start.router)
    router.include_router(downloaders.router)
    router.include_router(audio_tools.router)
    router.include_router(video_tools.router)
    router.include_router(image_tools.router)
    router.include_router(shazam.router)
    return router
