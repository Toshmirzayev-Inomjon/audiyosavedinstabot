from __future__ import annotations

# ruff: noqa: E501
import asyncio
import base64
import hashlib
import hmac
import json
import logging
import mimetypes
import secrets
import shutil
import tempfile
import time
from html import escape
from pathlib import Path
from urllib.parse import parse_qsl, quote

from aiogram import Bot
from aiogram.types import FSInputFile
from aiohttp import web

from app.catalog import SERVICES, plan_allows, serialize_catalog
from app.config import Settings
from app.database import Database
from app.security import generate_code, hash_code, hash_password
from app.services.ai import AIServiceError
from app.services.catalog_executor import CatalogExecutionError, execute_local
from app.services.downloader import MediaDownloadError, platform_for_url

logger = logging.getLogger(__name__)
MAX_INIT_DATA_AGE_SECONDS = 24 * 60 * 60


class WebAppAuthError(RuntimeError):
    pass


def verify_init_data(init_data: str, bot_token: str) -> dict:
    values = dict(parse_qsl(init_data, keep_blank_values=True))
    received_hash = values.pop("hash", "")
    if not received_hash:
        raise WebAppAuthError("Telegram WebApp imzosi topilmadi")
    data_check_string = "\n".join(
        f"{key}={value}" for key, value in sorted(values.items())
    )
    secret_key = hmac.new(
        b"WebAppData",
        bot_token.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    calculated_hash = hmac.new(
        secret_key,
        data_check_string.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(calculated_hash, received_hash):
        raise WebAppAuthError("Telegram WebApp imzosi noto'g'ri")
    try:
        auth_date = int(values.get("auth_date", "0"))
    except ValueError as exc:
        raise WebAppAuthError("Telegram WebApp vaqti noto'g'ri") from exc
    now = int(time.time())
    if auth_date <= 0 or auth_date > now + 60 or now - auth_date > MAX_INIT_DATA_AGE_SECONDS:
        raise WebAppAuthError("Telegram WebApp sessiyasi eskirgan")
    user_raw = values.get("user")
    if not user_raw:
        raise WebAppAuthError("Telegram foydalanuvchi ma'lumoti topilmadi")
    user = json.loads(user_raw)
    if not user.get("id"):
        raise WebAppAuthError("Telegram user id topilmadi")
    return user


async def _json_body(request: web.Request) -> dict:
    try:
        data = await request.json()
    except json.JSONDecodeError as exc:
        raise web.HTTPBadRequest(text="JSON noto'g'ri") from exc
    if not isinstance(data, dict):
        raise web.HTTPBadRequest(text="JSON object bo'lishi kerak")
    return data


def _auth_user(request: web.Request) -> dict:
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    settings: Settings = request.app["settings"]
    try:
        return verify_init_data(init_data, settings.bot_token)
    except WebAppAuthError as exc:
        raise web.HTTPUnauthorized(text=str(exc)) from exc


def _serialize_profile(profile) -> dict | None:
    if not profile:
        return None
    return {
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "phone": profile.phone,
        "phone_verified": profile.phone_verified,
        "password_set": profile.password_set,
    }


def _serialize_account(account) -> dict:
    return {
        "id": account.id,
        "title": account.title,
        "account_number": account.account_number,
        "status": account.status,
        "created_at": account.created_at,
    }


async def index_handler(_request: web.Request) -> web.Response:
    return web.Response(text=WEBAPP_HTML, content_type="text/html")


async def health_handler(_request: web.Request) -> web.Response:
    return web.json_response({"ok": True})


async def public_file_handler(request: web.Request) -> web.StreamResponse:
    token = request.match_info["token"]
    database: Database = request.app["database"]
    item = await database.get_public_file(token)
    if not item:
        raise web.HTTPNotFound(text="Fayl topilmadi yoki havola muddati tugagan")
    raw_path, filename, mime_type = item
    settings: Settings = request.app["settings"]
    allowed_root = (settings.temp_dir / "public").resolve()
    path = Path(raw_path).resolve()
    if not path.is_relative_to(allowed_root) or not path.is_file():
        raise web.HTTPNotFound(text="Fayl topilmadi")
    return web.FileResponse(
        path,
        headers={
            "Content-Type": mime_type,
            "Content-Disposition": (
                "attachment; "
                f"filename*=UTF-8''{quote(filename, safe='')}"
            ),
            "Cache-Control": "private, max-age=300",
        },
    )


async def me_handler(request: web.Request) -> web.Response:
    user = _auth_user(request)
    user_id = int(user["id"])
    database: Database = request.app["database"]
    await database.ensure_user(
        user_id,
        user.get("username"),
        " ".join(
            item for item in [user.get("first_name"), user.get("last_name")] if item
        ),
    )
    profile = await database.get_profile(user_id)
    accounts = await database.list_accounts(user_id)
    balance = await database.get_balance(user_id)
    downloads = await database.recent_downloads(user_id, 15)
    premium_until = await database.premium_until(user_id)
    tariff = await database.get_active_tariff(user_id)
    referral_count, referral_earned = await database.referral_stats(user_id)
    language = await database.get_language(user_id)
    settings: Settings = request.app["settings"]
    return web.json_response(
        {
            "telegram_user": {
                "id": user_id,
                "username": user.get("username"),
                "first_name": user.get("first_name", ""),
                "last_name": user.get("last_name", ""),
            },
            "balance": balance,
            "profile": _serialize_profile(profile),
            "accounts": [_serialize_account(account) for account in accounts],
            "downloads": [
                {
                    "id": item.id,
                    "source_url": item.source_url,
                    "media_type": item.media_type,
                    "quality": item.quality,
                    "title": item.title,
                    "status": item.status,
                    "created_at": item.created_at,
                }
                for item in downloads
            ],
            "premium_until": premium_until,
            "tariff": (
                {
                    "plan_code": tariff.plan_code,
                    "expires_at": tariff.expires_at,
                    "source": tariff.source,
                }
                if tariff
                else None
            ),
            "language": language,
            "is_admin": user_id in settings.admin_ids,
            "referral": {
                "count": referral_count,
                "earned": referral_earned,
            },
            "limitations": {
                "real_bank_cards": False,
                "message": (
                    "Bu ichki virtual hisob. Real karta/bank hisob ochish uchun "
                    "alohida to'lov provayderi integratsiyasi kerak."
                ),
            },
            "service_count": len(SERVICES),
            "tariff_options": {
                "period_days": settings.tariff_period_days,
                "standard_price": settings.tariff_standard_price,
                "premium_price": settings.tariff_premium_price,
                "standard_stars": settings.tariff_standard_stars,
                "premium_stars": settings.tariff_premium_stars,
                "bot_username": request.app["bot_username"],
            },
        }
    )


async def catalog_handler(request: web.Request) -> web.Response:
    user = _auth_user(request)
    database: Database = request.app["database"]
    tariff = await database.get_active_tariff(int(user["id"]))
    services = request.app["services"]
    return web.json_response(
        {
            "active_plan": tariff.plan_code if tariff else None,
            "categories": serialize_catalog(
                tariff.plan_code if tariff else None,
                ai_configured=services.ai.configured,
            ),
        }
    )


def _auth_admin(request: web.Request) -> dict:
    user = _auth_user(request)
    settings: Settings = request.app["settings"]
    if int(user["id"]) not in settings.admin_ids:
        raise web.HTTPForbidden(text="Admin huquqi kerak")
    return user


async def _web_public_link(
    *,
    services,
    database: Database,
    user_id: int,
    path: Path,
) -> str:
    if not services.public_base_url:
        raise RuntimeError("Public HTTPS manzil topilmadi")
    public_dir = services.settings.temp_dir / "public"
    public_dir.mkdir(parents=True, exist_ok=True)
    destination = public_dir / f"{user_id}-{secrets.token_hex(8)}{path.suffix}"
    await asyncio.to_thread(shutil.move, path, destination)
    token = await database.create_public_file(
        user_id,
        path=str(destination),
        filename=path.name,
        mime_type=mimetypes.guess_type(path.name)[0] or "application/octet-stream",
        ttl_seconds=services.settings.public_file_ttl_seconds,
    )
    return f"{services.public_base_url}/files/{token}"


async def _web_download_job(
    *,
    request_app: web.Application,
    user_id: int,
    url: str,
    quality: str,
    download_id: int,
) -> None:
    services = request_app["services"]
    bot: Bot = request_app["bot"]
    database: Database = request_app["database"]
    settings: Settings = request_app["settings"]
    status = await bot.send_message(user_id, "⏳ Mini App so'rovi navbatga qo'shildi...")
    completed = False
    try:
        async def work(context):
            with tempfile.TemporaryDirectory(
                prefix="web-download-",
                dir=settings.temp_dir,
            ) as temp:
                temp_dir = Path(temp)
                source = await services.downloader.download(
                    url,
                    temp_dir,
                    audio=quality == "audio",
                    quality=quality,
                    cancel_event=context.cancel_event,
                )
                context.check_cancelled()
                if quality == "audio":
                    await status.edit_text("⚙️ MP3 tayyorlanmoqda...")
                    output = await services.media.to_mp3(
                        source,
                        temp_dir / "converted.mp3",
                        cancel_event=context.cancel_event,
                    )
                    if output.stat().st_size > settings.telegram_upload_bytes:
                        link = await _web_public_link(
                            services=services,
                            database=database,
                            user_id=user_id,
                            path=output,
                        )
                        await bot.send_message(
                            user_id,
                            f"✅ MP3 tayyor. Katta fayl havolasi:\n{link}",
                        )
                        return None, output.stem
                    sent = await bot.send_audio(
                        user_id,
                        FSInputFile(output),
                        caption="✅ Mini App orqali MP3 tayyor.",
                    )
                    return sent.audio.file_id if sent.audio else None, output.stem
                if source.stat().st_size > settings.telegram_upload_bytes:
                    link = await _web_public_link(
                        services=services,
                        database=database,
                        user_id=user_id,
                        path=source,
                    )
                    await bot.send_message(
                        user_id,
                        f"✅ Video tayyor. Katta fayl havolasi:\n{link}",
                    )
                    return None, source.stem
                sent = await bot.send_video(
                    user_id,
                    FSInputFile(source),
                    caption=f"✅ Mini App orqali {quality}p video tayyor.",
                    supports_streaming=True,
                )
                return sent.video.file_id if sent.video else None, source.stem

        file_id, title = await services.jobs.run(user_id, work)
        await database.finish_download(
            download_id,
            status="completed",
            telegram_file_id=file_id,
            title=title,
        )
        completed = True
        await status.edit_text("✅ Tayyor fayl bot chatiga yuborildi.")
    except Exception as exc:
        await database.finish_download(
            download_id,
            status="failed",
            error_message=str(exc),
        )
        await database.log_error("webapp_download", str(exc), user_id)
        await status.edit_text(f"❌ Yuklash bajarilmadi: {str(exc)[:500]}")
    finally:
        if not completed:
            await database.release_daily_use(user_id)


async def create_download_handler(request: web.Request) -> web.Response:
    user = _auth_user(request)
    user_id = int(user["id"])
    data = await _json_body(request)
    url = str(data.get("url", "")).strip()
    quality = str(data.get("quality", "720"))
    if quality not in {"360", "720", "1080", "audio"}:
        raise web.HTTPBadRequest(text="Sifat noto'g'ri")
    try:
        platform_for_url(url)
    except MediaDownloadError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    database: Database = request.app["database"]
    settings: Settings = request.app["settings"]
    tariff = await database.get_active_tariff(user_id)
    if not tariff:
        raise web.HTTPPaymentRequired(
            text="Tarif faol emas. Botda /tarif orqali tarif tanlang."
        )
    if tariff.plan_code == "free" and quality != "audio":
        raise web.HTTPPaymentRequired(
            text="Bepul tarifda faqat musiqa/MP3 yuklash ishlaydi."
        )
    if quality == "1080" and not await database.is_premium(user_id):
        raise web.HTTPPaymentRequired(text="1080p uchun Premium kerak")
    daily_limit = await database.tariff_daily_limit(
        user_id,
        free_limit=settings.daily_free_limit,
        standard_limit=settings.tariff_standard_daily_limit,
    )
    allowed, remaining = await database.reserve_daily_use(
        user_id,
        daily_limit,
    )
    if not allowed:
        raise web.HTTPTooManyRequests(text="Bugungi bepul limit tugagan")
    download_id = await database.create_download(
        user_id,
        source_url=url,
        media_type="audio" if quality == "audio" else "video",
        quality=quality,
    )
    task = asyncio.create_task(
        _web_download_job(
            request_app=request.app,
            user_id=user_id,
            url=url,
            quality=quality,
            download_id=download_id,
        )
    )
    tasks: set[asyncio.Task] = request.app["tasks"]
    tasks.add(task)
    task.add_done_callback(tasks.discard)
    return web.json_response(
        {"ok": True, "download_id": download_id, "remaining": remaining}
    )


async def execute_service_handler(request: web.Request) -> web.Response:
    user = _auth_user(request)
    user_id = int(user["id"])
    slug = request.match_info["slug"]
    item = SERVICES.get(slug)
    if not item:
        raise web.HTTPNotFound(text="Xizmat topilmadi")
    database: Database = request.app["database"]
    tariff = await database.get_active_tariff(user_id)
    if not tariff:
        raise web.HTTPPaymentRequired(
            text="Botda /tarif orqali tarif tanlang."
        )
    if not plan_allows(tariff.plan_code, item.min_plan):
        raise web.HTTPPaymentRequired(
            text=f"Bu xizmat uchun kamida {item.min_plan.title()} tarif kerak."
        )
    data = await _json_body(request)
    value = str(data.get("input", "")).strip()
    if len(value) > 12_000:
        raise web.HTTPRequestEntityTooLarge(
            max_size=12_000,
            actual_size=len(value),
        )
    if not value and item.mode not in {"media", "media_audio"}:
        raise web.HTTPBadRequest(text="Ma'lumot kiriting")
    if item.mode == "planned":
        raise web.HTTPNotImplemented(
            text="Bu xizmat tashqi integratsiya talab qiladi va hozir sozlanmoqda."
        )
    if item.mode in {"media", "media_audio"}:
        return web.json_response(
            {
                "action": "media",
                "quality": "audio" if item.mode == "media_audio" else "720",
            }
        )
    if item.mode in {"local", "local_image"}:
        try:
            result = await asyncio.to_thread(execute_local, item.slug, value)
        except CatalogExecutionError as exc:
            raise web.HTTPBadRequest(text=str(exc)) from exc
        if result.image:
            encoded = base64.b64encode(result.image).decode("ascii")
            return web.json_response(
                {
                    "text": result.text,
                    "image_data": f"data:image/png;base64,{encoded}",
                    "image_name": result.image_name,
                }
            )
        return web.json_response({"text": result.text})

    services = request.app["services"]
    if not services.ai.configured:
        raise web.HTTPServiceUnavailable(
            text="AI kaliti Railway Variables bo'limida sozlanmagan."
        )
    settings: Settings = request.app["settings"]
    ai_limit = (
        settings.premium_ai_daily_limit
        if tariff.plan_code == "premium"
        else settings.standard_ai_daily_limit
    )
    allowed, remaining = await database.reserve_service_use(user_id, ai_limit)
    if not allowed:
        raise web.HTTPTooManyRequests(
            text="Bugungi AI xizmatlari limitingiz tugagan."
        )
    try:
        if item.mode == "ai_image":
            image = await services.ai.generate_image(
                prompt=value,
                instructions=item.prompt,
            )
            encoded = base64.b64encode(image).decode("ascii")
            return web.json_response(
                {
                    "image_data": f"data:image/png;base64,{encoded}",
                    "remaining": remaining,
                }
            )
        result = await services.ai.respond(
            user_input=value,
            instructions=item.prompt,
            web_search=item.mode == "ai_web",
            domains=item.domains,
        )
    except AIServiceError as exc:
        await database.release_service_use(user_id)
        await database.log_error(f"service:{slug}", str(exc), user_id)
        raise web.HTTPBadGateway(text=str(exc)) from exc
    except Exception as exc:
        await database.release_service_use(user_id)
        await database.log_error(f"service:{slug}", str(exc), user_id)
        raise web.HTTPInternalServerError(
            text="AI xizmati vaqtincha ishlamayapti."
        ) from exc
    return web.json_response(
        {
            "text": result.text,
            "sources": list(result.sources),
            "remaining": remaining,
        }
    )


async def set_language_handler(request: web.Request) -> web.Response:
    user = _auth_user(request)
    data = await _json_body(request)
    language = str(data.get("language", ""))
    database: Database = request.app["database"]
    try:
        await database.set_language(int(user["id"]), language)
    except ValueError as exc:
        raise web.HTTPBadRequest(text=str(exc)) from exc
    return web.json_response({"ok": True, "language": language})


async def admin_stats_handler(request: web.Request) -> web.Response:
    _auth_admin(request)
    database: Database = request.app["database"]
    return web.json_response({"stats": await database.admin_stats()})


async def admin_users_handler(request: web.Request) -> web.Response:
    _auth_admin(request)
    database: Database = request.app["database"]
    return web.json_response({"users": await database.admin_users()})


async def admin_errors_handler(request: web.Request) -> web.Response:
    _auth_admin(request)
    database: Database = request.app["database"]
    return web.json_response({"errors": await database.admin_errors()})


async def admin_payments_handler(request: web.Request) -> web.Response:
    _auth_admin(request)
    database: Database = request.app["database"]
    return web.json_response({"payments": await database.admin_payments()})


async def admin_balance_handler(request: web.Request) -> web.Response:
    admin = _auth_admin(request)
    data = await _json_body(request)
    try:
        user_id = int(data.get("user_id"))
        amount = int(data.get("amount"))
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text="USER_ID yoki summa noto'g'ri") from exc
    if amount <= 0:
        raise web.HTTPBadRequest(text="Summa musbat bo'lishi kerak")
    database: Database = request.app["database"]
    _, balance = await database.add_balance(
        user_id,
        amount,
        f"WebApp admin {admin['id']} hisobni to'ldirdi",
        kind="admin_credit",
    )
    return web.json_response({"ok": True, "balance": balance})


async def save_profile_handler(request: web.Request) -> web.Response:
    user = _auth_user(request)
    user_id = int(user["id"])
    data = await _json_body(request)
    first_name = str(data.get("first_name", "")).strip()
    last_name = str(data.get("last_name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    password = str(data.get("password", ""))
    if not first_name or not last_name:
        raise web.HTTPBadRequest(text="Ism va familiya majburiy")
    if phone and not phone.startswith("+"):
        raise web.HTTPBadRequest(text="Telefon +998... formatida bo'lishi kerak")
    database: Database = request.app["database"]
    profile = await database.upsert_profile(
        user_id,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
    )
    if password:
        await database.set_profile_password_hash(user_id, hash_password(password))
        profile = await database.get_profile(user_id)
    return web.json_response({"profile": _serialize_profile(profile)})


async def request_code_handler(request: web.Request) -> web.Response:
    user = _auth_user(request)
    user_id = int(user["id"])
    data = await _json_body(request)
    phone = str(data.get("phone", "")).strip()
    if not phone.startswith("+"):
        raise web.HTTPBadRequest(text="Telefon +998... formatida bo'lishi kerak")
    settings: Settings = request.app["settings"]
    database: Database = request.app["database"]
    bot: Bot = request.app["bot"]
    code = generate_code()
    await database.store_phone_code(
        user_id,
        phone=phone,
        code_hash=hash_code(code),
        expires_at=int(time.time()) + settings.phone_code_ttl_seconds,
    )
    await bot.send_message(
        user_id,
        "Profil telefonini tasdiqlash kodi:\n"
        f"<code>{escape(code)}</code>\n\n"
        "Bu kodni hech kimga bermang.",
    )
    return web.json_response({"ok": True, "ttl_seconds": settings.phone_code_ttl_seconds})


async def verify_code_handler(request: web.Request) -> web.Response:
    user = _auth_user(request)
    user_id = int(user["id"])
    data = await _json_body(request)
    code = str(data.get("code", "")).strip()
    if not code.isdigit() or len(code) != 6:
        raise web.HTTPBadRequest(text="6 xonali kod kiriting")
    database: Database = request.app["database"]
    ok, message = await database.verify_phone_code(user_id, hash_code(code))
    if not ok:
        raise web.HTTPBadRequest(text=message)
    profile = await database.get_profile(user_id)
    return web.json_response({"ok": True, "message": message, "profile": _serialize_profile(profile)})


async def create_account_handler(request: web.Request) -> web.Response:
    user = _auth_user(request)
    user_id = int(user["id"])
    data = await _json_body(request)
    title = str(data.get("title", "")).strip() or "Asosiy hisob"
    database: Database = request.app["database"]
    account = await database.create_account(user_id, title)
    return web.json_response({"account": _serialize_account(account)})


async def remove_account_handler(request: web.Request) -> web.Response:
    user = _auth_user(request)
    user_id = int(user["id"])
    account_id = int(request.match_info["account_id"])
    database: Database = request.app["database"]
    removed = await database.remove_account(user_id, account_id)
    if not removed:
        raise web.HTTPNotFound(text="Hisob topilmadi")
    return web.json_response({"ok": True})


async def start_web_app(
    *,
    settings: Settings,
    database: Database,
    bot: Bot,
    services=None,
) -> web.AppRunner:
    app = web.Application()
    app["settings"] = settings
    app["database"] = database
    app["bot"] = bot
    app["services"] = services
    app["tasks"] = set()
    app["bot_username"] = ""

    async def load_bot_username() -> None:
        try:
            bot_info = await asyncio.wait_for(bot.get_me(), timeout=10)
        except Exception:
            logger.exception("Bot username olishda xato")
            return
        app["bot_username"] = bot_info.username or ""

    username_task = asyncio.create_task(load_bot_username())
    app["tasks"].add(username_task)
    username_task.add_done_callback(app["tasks"].discard)
    app.add_routes(
        [
            web.get("/", index_handler),
            web.get("/health", health_handler),
            web.get("/files/{token}", public_file_handler),
            web.get("/api/me", me_handler),
            web.get("/api/catalog", catalog_handler),
            web.post("/api/downloads", create_download_handler),
            web.post("/api/services/{slug}/execute", execute_service_handler),
            web.post("/api/language", set_language_handler),
            web.post("/api/profile", save_profile_handler),
            web.post("/api/phone/request-code", request_code_handler),
            web.post("/api/phone/verify", verify_code_handler),
            web.post("/api/accounts", create_account_handler),
            web.delete("/api/accounts/{account_id:\\d+}", remove_account_handler),
            web.get("/api/admin/stats", admin_stats_handler),
            web.get("/api/admin/users", admin_users_handler),
            web.get("/api/admin/errors", admin_errors_handler),
            web.get("/api/admin/payments", admin_payments_handler),
            web.post("/api/admin/balance", admin_balance_handler),
        ]
    )
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, settings.webapp_host, settings.webapp_port)
    await site.start()
    logger.info("WebApp server started on %s:%s", settings.webapp_host, settings.webapp_port)
    return runner


WEBAPP_HTML = """<!doctype html>
<html lang="uz">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover" />
  <meta name="theme-color" content="#08111f" />
  <title>Saved Insta</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: var(--tg-theme-bg-color, #07101d);
      --surface: var(--tg-theme-secondary-bg-color, #101c2c);
      --text: var(--tg-theme-text-color, #f7fbff);
      --muted: var(--tg-theme-hint-color, #8fa3b8);
      --link: var(--tg-theme-link-color, #66b8ff);
      --button: var(--tg-theme-button-color, #2aabee);
      --button-text: var(--tg-theme-button-text-color, #ffffff);
      --border: rgba(148, 163, 184, .14);
      --green: #37d67a;
      --orange: #ffb648;
      --red: #ff5f69;
      --radius: 22px;
      font-family: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    * { box-sizing: border-box; -webkit-tap-highlight-color: transparent; }
    html { scroll-behavior: smooth; }
    body {
      min-height: 100vh;
      margin: 0;
      color: var(--text);
      background:
        radial-gradient(circle at 15% -5%, rgba(42, 171, 238, .22), transparent 34%),
        radial-gradient(circle at 105% 22%, rgba(111, 78, 255, .17), transparent 30%),
        var(--bg);
      overflow-x: hidden;
    }
    body::before {
      content: "";
      position: fixed;
      inset: 0;
      pointer-events: none;
      opacity: .18;
      background-image: linear-gradient(rgba(255,255,255,.025) 1px, transparent 1px),
                        linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
      background-size: 28px 28px;
      mask-image: linear-gradient(to bottom, black, transparent 70%);
    }

    button, input, select { font: inherit; }
    button { border: 0; cursor: pointer; }
    button:disabled { opacity: .55; cursor: wait; }

    .shell {
      position: relative;
      width: min(100%, 760px);
      margin: 0 auto;
      padding: calc(14px + env(safe-area-inset-top)) 14px calc(34px + env(safe-area-inset-bottom));
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      margin-bottom: 18px;
    }
    .brand { display: flex; align-items: center; gap: 11px; }
    .brand-logo {
      width: 42px;
      height: 42px;
      display: grid;
      place-items: center;
      border-radius: 14px;
      font-size: 20px;
      background: linear-gradient(145deg, #42c7ff, #4578ff 56%, #845cff);
      box-shadow: 0 10px 28px rgba(42, 171, 238, .28);
    }
    .brand strong { display: block; font-size: 16px; letter-spacing: -.2px; }
    .brand small { display: block; color: var(--muted); margin-top: 2px; }
    .secure-pill {
      display: flex;
      align-items: center;
      gap: 6px;
      padding: 8px 10px;
      border: 1px solid rgba(55, 214, 122, .22);
      border-radius: 999px;
      color: #83eba9;
      background: rgba(55, 214, 122, .09);
      font-size: 11px;
      font-weight: 800;
    }

    .hero {
      display: flex;
      align-items: center;
      gap: 13px;
      margin: 6px 3px 17px;
    }
    .avatar {
      width: 52px;
      height: 52px;
      flex: 0 0 auto;
      display: grid;
      place-items: center;
      border: 2px solid rgba(255,255,255,.14);
      border-radius: 18px;
      color: white;
      background: linear-gradient(145deg, #764eff, #2aabee);
      box-shadow: 0 9px 25px rgba(82, 99, 255, .22);
      font-weight: 900;
      font-size: 18px;
    }
    .hero-copy { min-width: 0; }
    .hero-copy p { margin: 0 0 4px; color: var(--muted); font-size: 12px; }
    .hero-copy h1 {
      margin: 0;
      overflow: hidden;
      font-size: clamp(21px, 6vw, 28px);
      letter-spacing: -.7px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .username { color: var(--link); font-size: 12px; margin-top: 3px; }

    .balance-card {
      position: relative;
      min-height: 190px;
      padding: 22px;
      overflow: hidden;
      border: 1px solid rgba(255,255,255,.13);
      border-radius: 28px;
      background: linear-gradient(135deg, #1437aa 0%, #2563eb 45%, #5d45e8 100%);
      box-shadow: 0 24px 60px rgba(30, 76, 190, .26);
    }
    .balance-card::before, .balance-card::after {
      content: "";
      position: absolute;
      border-radius: 50%;
      background: rgba(255,255,255,.1);
    }
    .balance-card::before { width: 230px; height: 230px; right: -90px; top: -125px; }
    .balance-card::after { width: 145px; height: 145px; right: 38px; bottom: -105px; }
    .balance-head {
      position: relative;
      z-index: 1;
      display: flex;
      justify-content: space-between;
      align-items: center;
      color: rgba(255,255,255,.75);
      font-size: 12px;
      font-weight: 700;
    }
    .live-dot {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 9px;
      border-radius: 999px;
      color: white;
      background: rgba(255,255,255,.13);
    }
    .live-dot::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: #79ffa8;
      box-shadow: 0 0 0 4px rgba(121,255,168,.15);
    }
    #balance {
      position: relative;
      z-index: 1;
      margin-top: 22px;
      color: white;
      font-size: clamp(30px, 9vw, 45px);
      font-weight: 900;
      letter-spacing: -1.7px;
    }
    .balance-foot {
      position: relative;
      z-index: 1;
      display: flex;
      justify-content: space-between;
      align-items: flex-end;
      margin-top: 24px;
      color: rgba(255,255,255,.78);
      font-size: 11px;
    }
    .card-chip {
      width: 35px;
      height: 26px;
      border: 1px solid rgba(255,255,255,.28);
      border-radius: 8px;
      background: linear-gradient(135deg, #ffcf67, #ff9d41);
      box-shadow: inset 0 0 0 5px rgba(255,255,255,.12);
    }

    .stats {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 9px;
      margin: 12px 0 20px;
    }
    .stat {
      min-width: 0;
      padding: 12px 10px;
      border: 1px solid var(--border);
      border-radius: 17px;
      background: rgba(16, 28, 44, .72);
      backdrop-filter: blur(16px);
    }
    .stat-icon { display: block; font-size: 17px; margin-bottom: 7px; }
    .stat strong {
      display: block;
      overflow: hidden;
      font-size: 12px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .stat small { display: block; color: var(--muted); font-size: 9px; margin-top: 3px; }

    .section {
      margin-top: 14px;
      padding: 18px;
      border: 1px solid var(--border);
      border-radius: var(--radius);
      background: rgba(14, 25, 40, .88);
      box-shadow: 0 16px 45px rgba(0, 0, 0, .12);
      backdrop-filter: blur(18px);
    }
    .section-head {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-bottom: 16px;
    }
    .section-title { display: flex; align-items: center; gap: 10px; }
    .section-icon {
      width: 36px;
      height: 36px;
      display: grid;
      place-items: center;
      border-radius: 12px;
      background: rgba(42, 171, 238, .12);
      color: #6cc9ff;
      font-size: 17px;
    }
    .section h2 { margin: 0; font-size: 16px; letter-spacing: -.2px; }
    .section-sub { color: var(--muted); font-size: 10px; margin-top: 2px; }
    .status-badge {
      padding: 6px 9px;
      border-radius: 999px;
      font-size: 10px;
      font-weight: 800;
      white-space: nowrap;
    }
    .status-badge.ok { color: #7beaa3; background: rgba(55, 214, 122, .1); }
    .status-badge.warn { color: #ffc567; background: rgba(255, 182, 72, .1); }

    .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 11px; }
    .field { min-width: 0; }
    .field.full { grid-column: 1 / -1; }
    label {
      display: block;
      margin: 0 0 7px 3px;
      color: var(--muted);
      font-size: 11px;
      font-weight: 700;
    }
    .input-wrap { position: relative; }
    input, select {
      width: 100%;
      height: 48px;
      padding: 0 13px;
      outline: none;
      border: 1px solid rgba(148,163,184,.17);
      border-radius: 14px;
      color: var(--text);
      background: rgba(3, 10, 20, .44);
      transition: border-color .2s, box-shadow .2s, transform .2s;
    }
    select { appearance: none; padding-right: 30px; }
    input::placeholder { color: rgba(143,163,184,.55); }
    input:focus, select:focus {
      border-color: rgba(42,171,238,.65);
      box-shadow: 0 0 0 4px rgba(42,171,238,.09);
    }
    .actions { display: flex; gap: 9px; margin-top: 14px; }
    .btn {
      min-height: 47px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 0 15px;
      border-radius: 14px;
      color: var(--button-text);
      background: linear-gradient(135deg, #2aabee, #3478f6);
      box-shadow: 0 10px 24px rgba(42,171,238,.18);
      font-size: 12px;
      font-weight: 850;
    }
    .btn.flex { flex: 1; }
    .btn.secondary {
      color: var(--text);
      background: rgba(148,163,184,.1);
      box-shadow: none;
    }
    .btn.danger {
      min-height: 38px;
      padding: 0 11px;
      color: #ff8991;
      background: rgba(255,95,105,.1);
      box-shadow: none;
    }
    .verify-box {
      margin-top: 13px;
      padding: 13px;
      border: 1px dashed rgba(42,171,238,.28);
      border-radius: 16px;
      background: rgba(42,171,238,.055);
    }
    .verify-row { display: flex; gap: 9px; }
    .verify-row input { text-align: center; letter-spacing: 5px; font-weight: 850; }
    .verify-row .btn { white-space: nowrap; }
    #profile_status { margin: 11px 2px 0; font-size: 11px; line-height: 1.45; }
    #profile_status.ok { color: #7beaa3; }
    #profile_status.warn { color: #ffc567; }

    .create-row { display: flex; gap: 9px; }
    .create-row input { flex: 1; }
    .create-row .btn { flex: 0 0 auto; }
    .accounts { margin-top: 13px; }
    .account {
      position: relative;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 11px;
      margin-top: 9px;
      padding: 14px;
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 17px;
      background: linear-gradient(135deg, rgba(37,99,235,.12), rgba(124,92,255,.07));
    }
    .account-main { min-width: 0; display: flex; align-items: center; gap: 11px; }
    .account-logo {
      width: 40px;
      height: 40px;
      flex: 0 0 auto;
      display: grid;
      place-items: center;
      border-radius: 13px;
      color: #8fd6ff;
      background: rgba(42,171,238,.12);
      font-size: 17px;
    }
    .account strong {
      display: block;
      overflow: hidden;
      font-size: 13px;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .account-number {
      display: block;
      margin-top: 4px;
      color: var(--muted);
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 10px;
      letter-spacing: .4px;
    }
    .empty {
      padding: 24px 12px 10px;
      text-align: center;
      color: var(--muted);
      font-size: 11px;
    }
    .empty-icon {
      width: 48px;
      height: 48px;
      display: grid;
      place-items: center;
      margin: 0 auto 10px;
      border-radius: 16px;
      background: rgba(148,163,184,.08);
      font-size: 21px;
    }

    .info-card {
      display: flex;
      gap: 12px;
      margin-top: 14px;
      padding: 15px;
      border: 1px solid rgba(55,214,122,.14);
      border-radius: 19px;
      color: var(--muted);
      background: rgba(55,214,122,.045);
      font-size: 10px;
      line-height: 1.55;
    }
    .info-card b { display: block; color: var(--text); font-size: 12px; margin-bottom: 2px; }
    .info-icon { color: #72e59d; font-size: 20px; }
    .service-hub {
      margin-top: 16px;
      padding: 18px;
      border: 1px solid var(--border);
      border-radius: 26px;
      background:
        radial-gradient(circle at 95% 0%, rgba(91, 69, 232, .2), transparent 35%),
        rgba(10, 20, 34, .94);
      box-shadow: 0 20px 55px rgba(0,0,0,.18);
    }
    .pricing-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 9px; }
    .price-card {
      position: relative;
      padding: 14px 11px;
      overflow: hidden;
      border: 1px solid var(--border);
      border-radius: 18px;
      background: rgba(255,255,255,.035);
    }
    .price-card.featured {
      border-color: rgba(169,108,255,.3);
      background: linear-gradient(145deg, rgba(91,69,232,.18), rgba(169,108,255,.08));
    }
    .price-card b { display: block; font-size: 12px; }
    .price-card strong { display: block; margin-top: 10px; font-size: 15px; }
    .price-card small { display: block; min-height: 28px; margin-top: 5px; color: var(--muted); font-size: 8px; line-height: 1.4; }
    .price-card button { width: 100%; min-height: 34px; margin-top: 10px; padding: 0 7px; border-radius: 10px; color: white; background: rgba(42,171,238,.18); font-size: 9px; font-weight: 900; }
    .hub-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }
    .hub-head h2 { margin: 0; font-size: 21px; letter-spacing: -.6px; }
    .hub-head p { margin: 5px 0 0; color: var(--muted); font-size: 11px; }
    .service-count {
      flex: 0 0 auto;
      padding: 8px 10px;
      border: 1px solid rgba(95, 198, 255, .25);
      border-radius: 999px;
      color: #8fd6ff;
      background: rgba(42,171,238,.09);
      font-size: 10px;
      font-weight: 900;
    }
    .catalog-search { position: relative; margin: 16px 0 14px; }
    .catalog-search input { padding-left: 42px; }
    .catalog-search::before {
      content: "⌕";
      position: absolute;
      z-index: 1;
      left: 15px;
      top: 11px;
      color: var(--muted);
      font-size: 22px;
    }
    .category-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }
    .category-card {
      position: relative;
      min-height: 132px;
      padding: 15px;
      overflow: hidden;
      text-align: left;
      border: 1px solid var(--border);
      border-radius: 20px;
      color: var(--text);
      background: rgba(255,255,255,.035);
    }
    .category-card::after {
      content: "";
      position: absolute;
      width: 90px;
      height: 90px;
      right: -35px;
      bottom: -40px;
      border-radius: 50%;
      background: var(--category-color);
      opacity: .18;
    }
    .category-icon {
      width: 42px;
      height: 42px;
      display: grid;
      place-items: center;
      margin-bottom: 11px;
      border-radius: 14px;
      background: color-mix(in srgb, var(--category-color) 18%, transparent);
      font-size: 20px;
    }
    .category-card strong { display: block; font-size: 13px; line-height: 1.25; }
    .category-card small { display: block; margin-top: 5px; color: var(--muted); font-size: 9px; line-height: 1.35; }
    .category-meta {
      display: flex;
      justify-content: space-between;
      margin-top: 10px;
      color: var(--category-color);
      font-size: 9px;
      font-weight: 800;
    }
    .catalog-toolbar { display: flex; align-items: center; gap: 10px; margin-bottom: 13px; }
    .back-button {
      width: 38px;
      height: 38px;
      flex: 0 0 auto;
      border-radius: 12px;
      color: var(--text);
      background: rgba(148,163,184,.1);
    }
    .catalog-toolbar h3 { margin: 0; font-size: 16px; }
    .service-grid { display: grid; gap: 9px; }
    .service-card {
      width: 100%;
      display: flex;
      align-items: center;
      gap: 12px;
      padding: 13px;
      text-align: left;
      border: 1px solid var(--border);
      border-radius: 17px;
      color: var(--text);
      background: rgba(255,255,255,.03);
    }
    .service-card.locked { opacity: .62; }
    .service-card-icon {
      width: 43px;
      height: 43px;
      flex: 0 0 auto;
      display: grid;
      place-items: center;
      border-radius: 14px;
      background: rgba(42,171,238,.1);
      font-size: 20px;
    }
    .service-card-copy { min-width: 0; flex: 1; }
    .service-card strong { display: block; font-size: 12px; }
    .service-card small { display: block; margin-top: 4px; overflow: hidden; color: var(--muted); font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
    .plan-chip {
      flex: 0 0 auto;
      padding: 5px 7px;
      border-radius: 999px;
      color: #8fd6ff;
      background: rgba(42,171,238,.09);
      font-size: 8px;
      font-weight: 900;
      text-transform: uppercase;
    }
    .plan-chip.premium { color: #e1c0ff; background: rgba(169,108,255,.12); }
    .plan-chip.free { color: #7beaa3; background: rgba(55,214,122,.1); }
    .service-modal {
      position: fixed;
      z-index: 60;
      inset: 0;
      display: none;
      align-items: flex-end;
      background: rgba(2,7,15,.78);
      backdrop-filter: blur(10px);
    }
    .service-modal.show { display: flex; }
    .service-sheet {
      width: min(100%, 760px);
      max-height: 88vh;
      margin: 0 auto;
      padding: 18px 16px calc(22px + env(safe-area-inset-bottom));
      overflow-y: auto;
      border: 1px solid var(--border);
      border-bottom: 0;
      border-radius: 27px 27px 0 0;
      background: #0d1928;
      box-shadow: 0 -25px 70px rgba(0,0,0,.45);
    }
    .sheet-grabber { width: 42px; height: 4px; margin: 0 auto 17px; border-radius: 9px; background: rgba(148,163,184,.35); }
    .sheet-head { display: flex; align-items: flex-start; gap: 12px; }
    .sheet-icon {
      width: 48px;
      height: 48px;
      flex: 0 0 auto;
      display: grid;
      place-items: center;
      border-radius: 16px;
      background: rgba(42,171,238,.12);
      font-size: 23px;
    }
    .sheet-copy { min-width: 0; flex: 1; }
    .sheet-copy h3 { margin: 2px 0 4px; font-size: 17px; }
    .sheet-copy p { margin: 0; color: var(--muted); font-size: 10px; line-height: 1.5; }
    .close-sheet { width: 37px; height: 37px; border-radius: 12px; color: var(--text); background: rgba(148,163,184,.1); }
    #service_input {
      width: 100%;
      min-height: 112px;
      margin-top: 16px;
      padding: 13px;
      resize: vertical;
      outline: none;
      border: 1px solid rgba(148,163,184,.17);
      border-radius: 15px;
      color: var(--text);
      background: rgba(3,10,20,.45);
      font: inherit;
    }
    .service-result {
      display: none;
      margin-top: 14px;
      padding: 14px;
      border: 1px solid var(--border);
      border-radius: 17px;
      color: var(--text);
      background: rgba(255,255,255,.035);
      font-size: 11px;
      line-height: 1.65;
      white-space: pre-wrap;
    }
    .service-result.show { display: block; }
    #service_image { display: none; width: 100%; margin-top: 13px; border-radius: 17px; }
    #service_sources { display: grid; gap: 7px; margin-top: 11px; }
    #service_sources a { color: var(--link); font-size: 10px; text-decoration: none; }
    .service-notice { margin-top: 14px; color: #ffc567; font-size: 10px; line-height: 1.5; }
    .footer { padding: 22px 10px 4px; text-align: center; color: var(--muted); font-size: 9px; }

    .toast {
      position: fixed;
      z-index: 40;
      left: 50%;
      bottom: calc(18px + env(safe-area-inset-bottom));
      width: min(calc(100% - 28px), 480px);
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 13px 14px;
      opacity: 0;
      transform: translate(-50%, 18px);
      pointer-events: none;
      border: 1px solid var(--border);
      border-radius: 16px;
      color: white;
      background: rgba(13, 24, 38, .96);
      box-shadow: 0 18px 50px rgba(0,0,0,.35);
      transition: .25s ease;
      font-size: 11px;
    }
    .toast.show { opacity: 1; transform: translate(-50%, 0); }
    .toast.error { border-color: rgba(255,95,105,.26); }
    .toast-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--green); }
    .toast.error .toast-dot { background: var(--red); }

    .overlay {
      position: fixed;
      z-index: 50;
      inset: 0;
      display: none;
      align-items: center;
      justify-content: center;
      padding: 24px;
      background: rgba(2, 7, 15, .75);
      backdrop-filter: blur(10px);
    }
    .overlay.show { display: flex; }
    .loader-card {
      width: min(100%, 300px);
      padding: 25px;
      text-align: center;
      border: 1px solid var(--border);
      border-radius: 24px;
      background: #101c2c;
      box-shadow: 0 25px 70px rgba(0,0,0,.4);
    }
    .spinner {
      width: 48px;
      height: 48px;
      margin: 0 auto 15px;
      border: 4px solid rgba(148,163,184,.15);
      border-top-color: #42bfff;
      border-radius: 50%;
      animation: spin .8s linear infinite;
    }
    .loader-card b { display: block; font-size: 14px; }
    .loader-card small { display: block; color: var(--muted); margin-top: 5px; }

    @keyframes spin { to { transform: rotate(360deg); } }
    @media (max-width: 410px) {
      .form-grid { grid-template-columns: 1fr; }
      .field.full { grid-column: auto; }
      .actions { flex-direction: column; }
      .verify-row { flex-direction: column; }
      .verify-row .btn { width: 100%; }
      .secure-pill span { display: none; }
      .balance-card { min-height: 180px; }
      .category-grid { grid-template-columns: 1fr 1fr; }
      .pricing-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <main class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="brand-logo">▶</div>
        <div><strong>Saved Insta</strong><small>Media &amp; Wallet</small></div>
      </div>
      <div class="secure-pill">◆ <span>Himoyalangan</span></div>
    </header>

    <section class="hero">
      <div class="avatar" id="avatar">SI</div>
      <div class="hero-copy">
        <p>Xush kelibsiz</p>
        <h1 id="display_name">Profil yuklanmoqda</h1>
        <div class="username" id="username">@telegram</div>
      </div>
    </section>

    <section class="balance-card">
      <div class="balance-head">
        <span>UMUMIY BALANS</span>
        <span class="live-dot">Faol</span>
      </div>
      <div id="balance">0 so'm</div>
      <div class="balance-foot">
        <span>Telegram Stars orqali to'ldiriladi<br />To'lov xavfsiz tekshiriladi</span>
        <div class="card-chip"></div>
      </div>
    </section>

    <section class="stats">
      <div class="stat"><span class="stat-icon">◉</span><strong id="phone_stat">Kutilmoqda</strong><small>Telefon</small></div>
      <div class="stat"><span class="stat-icon">◆</span><strong id="password_stat">Kutilmoqda</strong><small>Parol</small></div>
      <div class="stat"><span class="stat-icon">▣</span><strong id="account_stat">0 ta</strong><small>Hisoblar</small></div>
    </section>

    <section class="info-card">
      <div class="info-icon">★</div>
      <div>
        <b id="premium_status">Premium tekshirilmoqda</b>
        <span id="referral_status">Referral ma'lumoti yuklanmoqda...</span>
      </div>
    </section>

    <section class="section" id="tariffs_section">
      <div class="section-head">
        <div class="section-title">
          <div class="section-icon">★</div>
          <div><h2>Oylik tariflar</h2><div class="section-sub">Balans yoki Telegram Stars bilan to'lang</div></div>
        </div>
      </div>
      <div class="pricing-grid">
        <article class="price-card">
          <b>🆓 Bepul</b>
          <strong>0 so'm</strong>
          <small>30 kun · faqat musiqa/MP3 yuklash</small>
          <button onclick="openTariffs()">Tanlash</button>
        </article>
        <article class="price-card">
          <b>⚡ Standard</b>
          <strong id="standard_price">25 000 so'm</strong>
          <small id="standard_stars">25 Stars · katalogning yarmi</small>
          <button onclick="openTariffs()">Sotib olish</button>
        </article>
        <article class="price-card featured">
          <b>💎 Premium</b>
          <strong id="premium_price">50 000 so'm</strong>
          <small id="premium_stars">50 Stars · barcha tayyor servislar</small>
          <button onclick="openTariffs()">Sotib olish</button>
        </article>
      </div>
    </section>

    <section class="service-hub" id="services_hub">
      <div class="hub-head">
        <div>
          <h2>100 ta xizmat markazi</h2>
          <p>Kategoriyani oching, keyin kerakli funksiyani tanlang</p>
        </div>
        <span class="service-count" id="service_count">100 servis</span>
      </div>
      <div class="catalog-search">
        <input id="catalog_search" placeholder="Xizmat qidirish..." oninput="searchCatalog(this.value)" />
      </div>
      <div id="category_view" class="category-grid"></div>
      <div id="service_view" style="display:none">
        <div class="catalog-toolbar">
          <button class="back-button" onclick="showCategories()">←</button>
          <div><h3 id="category_title">Kategoriya</h3><div class="section-sub" id="category_subtitle"></div></div>
        </div>
        <div id="service_grid" class="service-grid"></div>
      </div>
    </section>

    <section class="section" id="media_download_section">
      <div class="section-head">
        <div class="section-title">
          <div class="section-icon">↓</div>
          <div><h2 id="ui_download_title">Media yuklash</h2><div class="section-sub" id="ui_download_sub">Natija bot chatiga yuboriladi</div></div>
        </div>
      </div>
      <div class="field full">
        <label for="download_url">YOUTUBE YOKI INSTAGRAM HAVOLASI</label>
        <input id="download_url" placeholder="https://youtube.com/watch?v=..." inputmode="url" />
      </div>
      <div class="form-grid" style="margin-top:11px">
        <div class="field">
          <label for="download_quality">SIFAT</label>
          <select id="download_quality">
            <option value="360">360p</option>
            <option value="720" selected>720p</option>
            <option value="1080">1080p Premium</option>
            <option value="audio">Faqat MP3</option>
          </select>
        </div>
        <div class="field" style="display:flex;align-items:flex-end">
          <button class="btn flex" id="ui_download_btn" onclick="submitDownload()">↓ Yuklashni boshlash</button>
        </div>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <div class="section-title">
          <div class="section-icon">↻</div>
          <div><h2 id="ui_history_title">Yuklash tarixi</h2><div class="section-sub">Oxirgi 15 ta so'rov</div></div>
        </div>
      </div>
      <div id="download_history" class="accounts"></div>
    </section>

    <section class="section">
      <div class="section-head">
        <div class="section-title">
          <div class="section-icon">●</div>
          <div><h2 id="ui_profile_title">Shaxsiy profil</h2><div class="section-sub">Ma'lumotlaringizni boshqaring</div></div>
        </div>
        <span id="profile_badge" class="status-badge warn">To'liq emas</span>
      </div>

      <div class="form-grid">
        <div class="field">
          <label for="first_name">ISM</label>
          <input id="first_name" autocomplete="given-name" placeholder="Ismingiz" />
        </div>
        <div class="field">
          <label for="last_name">FAMILIYA</label>
          <input id="last_name" autocomplete="family-name" placeholder="Familiyangiz" />
        </div>
        <div class="field full">
          <label for="phone">TELEFON RAQAMI</label>
          <input id="phone" placeholder="+998 90 123 45 67" autocomplete="tel" inputmode="tel" />
        </div>
        <div class="field full">
          <label for="password">YANGI PAROL</label>
          <input id="password" type="password" autocomplete="new-password" placeholder="Kamida 6 ta belgi" />
        </div>
      </div>

      <div class="actions">
        <button class="btn flex" id="save_btn" onclick="saveProfile()">✓ Profilni saqlash</button>
        <button class="btn secondary flex" id="code_btn" onclick="requestCode()">✦ Kod yuborish</button>
      </div>

      <div class="verify-box">
        <label for="code">TELEGRAMGA KELGAN 6 XONALI KOD</label>
        <div class="verify-row">
          <input id="code" maxlength="6" placeholder="••••••" inputmode="numeric" autocomplete="one-time-code" />
          <button class="btn secondary" id="verify_btn" onclick="verifyCode()">Tasdiqlash</button>
        </div>
      </div>
      <p id="profile_status">Profil holati tekshirilmoqda...</p>
      <div class="field full" style="margin-top:14px">
        <label for="language_select">INTERFEYS TILI</label>
        <select id="language_select" onchange="setLanguage(this.value)">
          <option value="uz">🇺🇿 O'zbekcha</option>
          <option value="ru">🇷🇺 Русский</option>
          <option value="en">🇬🇧 English</option>
        </select>
      </div>
    </section>

    <section class="section">
      <div class="section-head">
        <div class="section-title">
          <div class="section-icon">▣</div>
          <div><h2 id="ui_accounts_title">Virtual hisoblar</h2><div class="section-sub">Bot ichidagi hisob raqamlaringiz</div></div>
        </div>
      </div>
      <div class="create-row">
        <input id="account_title" maxlength="40" placeholder="Masalan: Asosiy hisob" />
        <button class="btn" id="account_btn" onclick="createAccount()">＋ Ochish</button>
      </div>
      <div id="accounts" class="accounts"></div>
    </section>

    <section class="info-card">
      <div class="info-icon">◆</div>
      <div>
        <b>Ma'lumotlaringiz himoyalangan</b>
        Telegram imzosi har bir so'rovda tekshiriladi. Parolingiz ochiq holda emas,
        xavfsiz hash ko'rinishida saqlanadi. Bu real bank kartasi emas.
      </div>
    </section>

    <section class="section" id="admin_section" style="display:none">
      <div class="section-head">
        <div class="section-title">
          <div class="section-icon">⚙</div>
          <div><h2>Admin panel</h2><div class="section-sub">Bot holati va foydalanuvchilar</div></div>
        </div>
      </div>
      <div id="admin_stats" class="stats"></div>
      <div class="form-grid">
        <div class="field">
          <label for="admin_user_id">TELEGRAM USER ID</label>
          <input id="admin_user_id" inputmode="numeric" placeholder="123456789" />
        </div>
        <div class="field">
          <label for="admin_amount">BALANS SUMMASI</label>
          <input id="admin_amount" inputmode="numeric" placeholder="5000" />
        </div>
      </div>
      <button class="btn flex" style="width:100%;margin-top:11px" onclick="adminAddBalance()">＋ Balans qo'shish</button>
      <div id="admin_users" class="accounts"></div>
      <div id="admin_payments" class="accounts"></div>
      <div id="admin_errors" class="accounts"></div>
    </section>

    <footer class="footer">Saved Insta · Telegram WebApp</footer>
  </main>

  <div id="toast" class="toast"><span class="toast-dot"></span><span id="toast_text"></span></div>
  <div id="overlay" class="overlay">
    <div class="loader-card">
      <div class="spinner"></div>
      <b id="loader_title">Amal bajarilmoqda</b>
      <small>Iltimos, bir necha soniya kuting</small>
    </div>
  </div>
  <div id="service_modal" class="service-modal" onclick="modalBackdrop(event)">
    <div class="service-sheet">
      <div class="sheet-grabber"></div>
      <div class="sheet-head">
        <div class="sheet-icon" id="service_icon">⚙</div>
        <div class="sheet-copy">
          <h3 id="service_title">Xizmat</h3>
          <p id="service_description"></p>
        </div>
        <button class="close-sheet" onclick="closeService()">×</button>
      </div>
      <div class="service-notice" id="service_notice"></div>
      <textarea id="service_input" placeholder="So'rovingizni yozing"></textarea>
      <button class="btn" id="service_run_btn" style="width:100%;margin-top:11px" onclick="runService()">Ishga tushirish</button>
      <div id="service_result" class="service-result"></div>
      <img id="service_image" alt="AI yoki QR natijasi" />
      <div id="service_sources"></div>
    </div>
  </div>

  <script>
    const tg = window.Telegram?.WebApp;
    if (tg) {
      tg.ready();
      tg.expand();
      tg.setHeaderColor?.("#08111f");
      tg.setBackgroundColor?.("#07101d");
    }
    const initData = tg?.initData || "";
    let toastTimer;
    let catalogData = [];
    let currentService = null;
    let activePlan = null;
    let botUsername = "";
    const UI_TEXT = {
      uz: {
        download: "Media yuklash", downloadSub: "Natija bot chatiga yuboriladi",
        downloadBtn: "↓ Yuklashni boshlash", history: "Yuklash tarixi",
        profile: "Shaxsiy profil", accounts: "Virtual hisoblar",
        save: "✓ Profilni saqlash", code: "✦ Kod yuborish", verify: "Tasdiqlash",
        openAccount: "＋ Ochish"
      },
      ru: {
        download: "Загрузка медиа", downloadSub: "Результат придёт в чат бота",
        downloadBtn: "↓ Начать загрузку", history: "История загрузок",
        profile: "Личный профиль", accounts: "Виртуальные счета",
        save: "✓ Сохранить профиль", code: "✦ Отправить код", verify: "Подтвердить",
        openAccount: "＋ Открыть"
      },
      en: {
        download: "Media download", downloadSub: "The result will be sent to the bot chat",
        downloadBtn: "↓ Start download", history: "Download history",
        profile: "Personal profile", accounts: "Virtual accounts",
        save: "✓ Save profile", code: "✦ Send code", verify: "Verify",
        openAccount: "＋ Open"
      }
    };

    function applyLanguage(language) {
      const value = UI_TEXT[language] || UI_TEXT.uz;
      document.documentElement.lang = language;
      document.getElementById("ui_download_title").textContent = value.download;
      document.getElementById("ui_download_sub").textContent = value.downloadSub;
      document.getElementById("ui_download_btn").textContent = value.downloadBtn;
      document.getElementById("ui_history_title").textContent = value.history;
      document.getElementById("ui_profile_title").textContent = value.profile;
      document.getElementById("ui_accounts_title").textContent = value.accounts;
      document.getElementById("save_btn").textContent = value.save;
      document.getElementById("code_btn").textContent = value.code;
      document.getElementById("verify_btn").textContent = value.verify;
      document.getElementById("account_btn").textContent = value.openAccount;
    }

    async function api(path, options = {}) {
      const response = await fetch(path, {
        ...options,
        headers: {
          "Content-Type": "application/json",
          "X-Telegram-Init-Data": initData,
          ...(options.headers || {})
        }
      });
      if (!response.ok) throw new Error(await response.text());
      return response.json();
    }

    function money(value) {
      return new Intl.NumberFormat("uz-UZ").format(value || 0) + " so'm";
    }

    function initials(firstName, lastName) {
      return ((firstName || "S")[0] + (lastName || "I")[0]).toUpperCase();
    }

    function escapeHtml(value) {
      return String(value).replace(/[&<>"']/g, char => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#039;"
      })[char]);
    }

    function haptic(type = "light") {
      tg?.HapticFeedback?.impactOccurred(type);
    }

    function toast(text, ok = true) {
      const root = document.getElementById("toast");
      document.getElementById("toast_text").textContent = text;
      root.className = ok ? "toast show" : "toast error show";
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => root.classList.remove("show"), 3000);
      if (!ok) tg?.HapticFeedback?.notificationOccurred("error");
    }

    function setBusy(show, title = "Amal bajarilmoqda") {
      document.getElementById("loader_title").textContent = title;
      document.getElementById("overlay").classList.toggle("show", show);
    }

    function showStatus(text, ok = true) {
      const el = document.getElementById("profile_status");
      el.textContent = text;
      el.className = ok ? "ok" : "warn";
    }

    function planLabel(plan) {
      return {free: "Bepul", standard: "Standard", premium: "Premium"}[plan] || plan;
    }

    function renderCategories() {
      const root = document.getElementById("category_view");
      document.getElementById("service_view").style.display = "none";
      root.style.display = "grid";
      root.innerHTML = catalogData.map(category => {
        const openCount = category.services.filter(item => item.unlocked).length;
        return `
          <button class="category-card" style="--category-color:${escapeHtml(category.color)}" onclick="openCategory('${category.slug}')">
            <span class="category-icon">${category.icon}</span>
            <strong>${escapeHtml(category.title)}</strong>
            <small>${escapeHtml(category.subtitle)}</small>
            <span class="category-meta"><span>${category.services.length} servis</span><span>${openCount} ochiq →</span></span>
          </button>`;
      }).join("");
    }

    function renderServices(items) {
      const root = document.getElementById("service_grid");
      root.innerHTML = items.map(item => `
        <button class="service-card ${item.unlocked ? "" : "locked"}" onclick="openService('${item.slug}')">
          <span class="service-card-icon">${item.icon}</span>
          <span class="service-card-copy">
            <strong>${escapeHtml(item.name)}</strong>
            <small>${escapeHtml(item.description)}</small>
          </span>
          <span class="plan-chip ${item.min_plan}">${item.unlocked ? planLabel(item.min_plan) : "🔒 " + planLabel(item.min_plan)}</span>
        </button>
      `).join("");
    }

    function openCategory(slug) {
      const category = catalogData.find(item => item.slug === slug);
      if (!category) return;
      document.getElementById("category_view").style.display = "none";
      document.getElementById("service_view").style.display = "block";
      document.getElementById("category_title").textContent = category.icon + " " + category.title;
      document.getElementById("category_subtitle").textContent = category.subtitle;
      renderServices(category.services);
      haptic();
    }

    function showCategories() {
      document.getElementById("catalog_search").value = "";
      renderCategories();
    }

    function searchCatalog(value) {
      const query = value.trim().toLowerCase();
      if (!query) {
        renderCategories();
        return;
      }
      const matches = catalogData.flatMap(category => category.services).filter(item =>
        (item.name + " " + item.description).toLowerCase().includes(query)
      );
      document.getElementById("category_view").style.display = "none";
      document.getElementById("service_view").style.display = "block";
      document.getElementById("category_title").textContent = "⌕ Qidiruv natijalari";
      document.getElementById("category_subtitle").textContent = matches.length + " ta servis topildi";
      renderServices(matches);
    }

    function findService(slug) {
      return catalogData.flatMap(category => category.services).find(item => item.slug === slug);
    }

    function openService(slug) {
      const item = findService(slug);
      if (!item) return;
      if (!item.unlocked) {
        toast("Bu xizmat uchun " + planLabel(item.min_plan) + " tarif kerak", false);
        tg?.HapticFeedback?.notificationOccurred("warning");
        return;
      }
      currentService = item;
      document.getElementById("service_icon").textContent = item.icon;
      document.getElementById("service_title").textContent = item.name;
      document.getElementById("service_description").textContent = item.description;
      document.getElementById("service_input").placeholder = item.placeholder || "So'rovingizni yozing";
      document.getElementById("service_input").value = "";
      document.getElementById("service_result").classList.remove("show");
      document.getElementById("service_result").textContent = "";
      document.getElementById("service_image").style.display = "none";
      document.getElementById("service_sources").innerHTML = "";
      const notice = document.getElementById("service_notice");
      const button = document.getElementById("service_run_btn");
      if (!item.ready) {
        notice.textContent = item.configured
          ? "Bu servis uchun tashqi integratsiya tayyorlanmoqda."
          : "AI xizmatlari uchun serverda GEMINI_API_KEY yoki OPENAI_API_KEY sozlanishi kerak.";
        button.disabled = true;
      } else {
        notice.textContent = item.mode === "ai_web"
          ? "Natija internet manbalari bilan tekshiriladi."
          : "";
        button.disabled = false;
      }
      document.getElementById("service_modal").classList.add("show");
      haptic();
    }

    function closeService() {
      document.getElementById("service_modal").classList.remove("show");
      currentService = null;
    }

    function modalBackdrop(event) {
      if (event.target.id === "service_modal") closeService();
    }

    async function runService() {
      if (!currentService) return;
      const input = document.getElementById("service_input").value.trim();
      if (!input && !["media", "media_audio"].includes(currentService.mode)) {
        toast("Ma'lumot kiriting", false);
        return;
      }
      setBusy(true, currentService.name + " ishlamoqda");
      try {
        const result = await api("/api/services/" + currentService.slug + "/execute", {
          method: "POST",
          body: JSON.stringify({ input })
        });
        if (result.action === "media") {
          closeService();
          document.getElementById("download_quality").value = result.quality || "720";
          document.getElementById("media_download_section").scrollIntoView({behavior: "smooth"});
          document.getElementById("download_url").focus();
          toast("Havolani kiriting va yuklashni boshlang");
          return;
        }
        const output = document.getElementById("service_result");
        output.textContent = result.text || "";
        output.classList.toggle("show", !!result.text);
        const image = document.getElementById("service_image");
        if (result.image_data) {
          image.src = result.image_data;
          image.style.display = "block";
        } else {
          image.style.display = "none";
        }
        const sources = document.getElementById("service_sources");
        sources.innerHTML = "";
        (result.sources || []).forEach(source => {
          try {
            const url = new URL(source.url);
            if (!["http:", "https:"].includes(url.protocol)) return;
            const link = document.createElement("a");
            link.href = url.href;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = "↗ " + (source.title || url.hostname);
            sources.appendChild(link);
          } catch (_) {}
        });
        toast("Xizmat natijasi tayyor");
        tg?.HapticFeedback?.notificationOccurred("success");
      } catch (error) {
        toast(error.message, false);
      } finally {
        setBusy(false);
      }
    }

    function applyPlanLimits(plan) {
      const select = document.getElementById("download_quality");
      Array.from(select.options).forEach(option => {
        option.disabled =
          (plan === "free" && option.value !== "audio") ||
          (plan === "standard" && option.value === "1080");
      });
      if (plan === "free") select.value = "audio";
      if (plan === "standard" && select.value === "1080") select.value = "720";
    }

    function openTariffs() {
      if (!botUsername) {
        toast("Bot username topilmadi. Bot chatida /tarif ni bosing.", false);
        return;
      }
      const url = "https://t.me/" + botUsername + "?start=tarif";
      if (tg?.openTelegramLink) {
        tg.openTelegramLink(url);
      } else {
        window.location.href = url;
      }
    }

    async function load() {
      try {
        const [data, catalog] = await Promise.all([
          api("/api/me"),
          api("/api/catalog")
        ]);
        catalogData = catalog.categories || [];
        activePlan = catalog.active_plan;
        botUsername = data.tariff_options?.bot_username || "";
        document.getElementById("service_count").textContent =
          (data.service_count || 100) + " servis";
        document.getElementById("standard_price").textContent =
          money(data.tariff_options?.standard_price || 0);
        document.getElementById("premium_price").textContent =
          money(data.tariff_options?.premium_price || 0);
        document.getElementById("standard_stars").textContent =
          (data.tariff_options?.standard_stars || 0) + " Stars · katalogning yarmi";
        document.getElementById("premium_stars").textContent =
          (data.tariff_options?.premium_stars || 0) + " Stars · barcha tayyor servislar";
        renderCategories();
        applyPlanLimits(activePlan);
        const p = data.profile || {};
        const user = data.telegram_user || {};
        const firstName = p.first_name || user.first_name || "Telegram";
        const lastName = p.last_name || user.last_name || "foydalanuvchi";
        document.getElementById("balance").textContent = money(data.balance);
        document.getElementById("display_name").textContent = firstName + " " + lastName;
        document.getElementById("username").textContent = user.username ? "@" + user.username : "Telegram ID: " + user.id;
        document.getElementById("avatar").textContent = initials(firstName, lastName);
        document.getElementById("first_name").value = p.first_name || user.first_name || "";
        document.getElementById("last_name").value = p.last_name || user.last_name || "";
        document.getElementById("phone").value = p.phone || "";

        document.getElementById("phone_stat").textContent = p.phone_verified ? "Tasdiqlangan" : "Tasdiqlanmagan";
        document.getElementById("password_stat").textContent = p.password_set ? "O'rnatilgan" : "O'rnatilmagan";
        document.getElementById("account_stat").textContent = (data.accounts || []).length + " ta";
        document.getElementById("language_select").value = data.language || "uz";
        applyLanguage(data.language || "uz");
        const tariffNames = {free: "Bepul", standard: "Standard", premium: "Premium"};
        document.getElementById("premium_status").textContent = data.tariff
          ? (tariffNames[data.tariff.plan_code] || data.tariff.plan_code) +
            " tarif · " + new Date(data.tariff.expires_at * 1000).toLocaleDateString()
          : "Tarif faol emas · botda /tarif ni bosing";
        document.getElementById("referral_status").textContent =
          "Takliflar: " + (data.referral?.count || 0) +
          " · Bonus: " + money(data.referral?.earned || 0);
        const complete = p.phone_verified && p.password_set;
        const badge = document.getElementById("profile_badge");
        badge.textContent = complete ? "Himoyalangan" : "To'liq emas";
        badge.className = complete ? "status-badge ok" : "status-badge warn";
        showStatus(
          p.phone_verified
            ? "Telefon tasdiqlangan. Parol " + (p.password_set ? "o'rnatilgan." : "hali o'rnatilmagan.")
            : "Telefon raqamingizni saqlang va Telegram kodi orqali tasdiqlang.",
          !!p.phone_verified
        );
        renderAccounts(data.accounts || []);
        renderHistory(data.downloads || []);
        if (data.is_admin) {
          document.getElementById("admin_section").style.display = "block";
          loadAdmin();
        }
      } catch (error) {
        showStatus(error.message, false);
        toast(error.message, false);
      }
    }

    function renderAccounts(accounts) {
      const root = document.getElementById("accounts");
      if (!accounts.length) {
        root.innerHTML = "<div class='empty'><div class='empty-icon'>▣</div>Hali virtual hisob ochilmagan.<br>Yuqoridan yangi hisob yarating.</div>";
        return;
      }
      root.innerHTML = accounts.map(account => `
        <article class="account">
          <div class="account-main">
            <div class="account-logo">▣</div>
            <div>
              <strong>${escapeHtml(account.title)}</strong>
              <span class="account-number">${escapeHtml(account.account_number)}</span>
            </div>
          </div>
          <button class="btn danger" onclick="removeAccount(${Number(account.id)})">O'chirish</button>
        </article>
      `).join("");
    }

    function renderHistory(items) {
      const root = document.getElementById("download_history");
      if (!items.length) {
        root.innerHTML = "<div class='empty'><div class='empty-icon'>↻</div>Tarix hozircha bo'sh.</div>";
        return;
      }
      const labels = {
        queued: "Navbatda",
        completed: "Tayyor",
        failed: "Xato",
        cancelled: "Bekor qilindi"
      };
      root.innerHTML = items.map(item => `
        <article class="account">
          <div class="account-main">
            <div class="account-logo">${item.media_type === "audio" ? "♫" : "▶"}</div>
            <div>
              <strong>${escapeHtml(item.title || item.source_url || "Media")}</strong>
              <span class="account-number">${escapeHtml(item.quality || "")} · ${labels[item.status] || item.status}</span>
            </div>
          </div>
        </article>
      `).join("");
    }

    async function submitDownload() {
      const url = document.getElementById("download_url").value.trim();
      const quality = document.getElementById("download_quality").value;
      if (!url) {
        toast("Havolani kiriting", false);
        return;
      }
      setBusy(true, "Navbatga qo'shilmoqda");
      try {
        await api("/api/downloads", {
          method: "POST",
          body: JSON.stringify({ url, quality })
        });
        document.getElementById("download_url").value = "";
        toast("So'rov qabul qilindi. Natija bot chatiga yuboriladi.");
        haptic("medium");
        setTimeout(load, 1200);
      } catch (error) {
        toast(error.message, false);
      } finally {
        setBusy(false);
      }
    }

    async function setLanguage(language) {
      try {
        await api("/api/language", {
          method: "POST",
          body: JSON.stringify({ language })
        });
        applyLanguage(language);
        toast("Til sozlamasi saqlandi");
      } catch (error) {
        toast(error.message, false);
      }
    }

    async function loadAdmin() {
      try {
        const [statsData, usersData, paymentsData, errorsData] = await Promise.all([
          api("/api/admin/stats"),
          api("/api/admin/users"),
          api("/api/admin/payments"),
          api("/api/admin/errors")
        ]);
        const stats = statsData.stats || {};
        document.getElementById("admin_stats").innerHTML = [
          ["Foydalanuvchi", stats.users],
          ["Yuklash", stats.downloads],
          ["Premium", stats.premium]
        ].map(item => `<div class="stat"><strong>${item[1] || 0}</strong><small>${item[0]}</small></div>`).join("");
        document.getElementById("admin_users").innerHTML =
          "<label style='margin-top:16px'>SO'NGGI FOYDALANUVCHILAR</label>" +
          (usersData.users || []).slice(0, 20).map(user => `
            <article class="account">
              <div class="account-main"><div class="account-logo">●</div><div>
                <strong>${escapeHtml(user.full_name || user.username || String(user.user_id))}</strong>
                <span class="account-number">${user.user_id} · ${money(user.balance)}</span>
              </div></div>
            </article>`).join("");
        document.getElementById("admin_payments").innerHTML =
          "<label style='margin-top:16px'>SO'NGGI TO'LOVLAR</label>" +
          (paymentsData.payments || []).slice(0, 10).map(payment => `
            <article class="account">
              <div class="account-main"><div class="account-logo">★</div><div>
                <strong>${payment.stars} Stars${payment.credits ? " · " + money(payment.credits) : ""}</strong>
                <span class="account-number">${payment.user_id} · ${escapeHtml(payment.status)}</span>
              </div></div>
            </article>`).join("");
        document.getElementById("admin_errors").innerHTML =
          "<label style='margin-top:16px'>SO'NGGI XATOLAR</label>" +
          (errorsData.errors || []).slice(0, 10).map(error => `
            <article class="account">
              <div class="account-main"><div class="account-logo">!</div><div>
                <strong>${escapeHtml(error.context)}</strong>
                <span class="account-number">${escapeHtml(error.message).slice(0, 110)}</span>
              </div></div>
            </article>`).join("");
      } catch (error) {
        toast(error.message, false);
      }
    }

    async function adminAddBalance() {
      const userId = document.getElementById("admin_user_id").value;
      const amount = document.getElementById("admin_amount").value;
      setBusy(true, "Balans qo'shilmoqda");
      try {
        const result = await api("/api/admin/balance", {
          method: "POST",
          body: JSON.stringify({ user_id: userId, amount })
        });
        toast("Yangi balans: " + money(result.balance));
        loadAdmin();
      } catch (error) {
        toast(error.message, false);
      } finally {
        setBusy(false);
      }
    }

    async function saveProfile() {
      setBusy(true, "Profil saqlanmoqda");
      try {
        const payload = {
          first_name: document.getElementById("first_name").value,
          last_name: document.getElementById("last_name").value,
          phone: document.getElementById("phone").value.replace(/\\s/g, ""),
          password: document.getElementById("password").value
        };
        await api("/api/profile", { method: "POST", body: JSON.stringify(payload) });
        document.getElementById("password").value = "";
        haptic("medium");
        toast("Profil muvaffaqiyatli saqlandi");
        await load();
      } catch (error) {
        showStatus(error.message, false);
        toast(error.message, false);
      } finally {
        setBusy(false);
      }
    }

    async function requestCode() {
      setBusy(true, "Kod yuborilmoqda");
      try {
        const phone = document.getElementById("phone").value.replace(/\\s/g, "");
        await api("/api/phone/request-code", {
          method: "POST",
          body: JSON.stringify({ phone })
        });
        showStatus("6 xonali kod Telegram chatga yuborildi.");
        toast("Tasdiqlash kodi bot chatiga yuborildi");
        haptic();
      } catch (error) {
        showStatus(error.message, false);
        toast(error.message, false);
      } finally {
        setBusy(false);
      }
    }

    async function verifyCode() {
      setBusy(true, "Kod tekshirilmoqda");
      try {
        const code = document.getElementById("code").value;
        await api("/api/phone/verify", { method: "POST", body: JSON.stringify({ code }) });
        document.getElementById("code").value = "";
        toast("Telefon raqami tasdiqlandi");
        tg?.HapticFeedback?.notificationOccurred("success");
        await load();
      } catch (error) {
        showStatus(error.message, false);
        toast(error.message, false);
      } finally {
        setBusy(false);
      }
    }

    async function createAccount() {
      setBusy(true, "Hisob ochilmoqda");
      try {
        const input = document.getElementById("account_title");
        const title = input.value.trim() || "Asosiy hisob";
        await api("/api/accounts", { method: "POST", body: JSON.stringify({ title }) });
        input.value = "";
        toast("Yangi virtual hisob ochildi");
        haptic("medium");
        await load();
      } catch (error) {
        toast(error.message, false);
      } finally {
        setBusy(false);
      }
    }

    async function removeAccount(id) {
      const confirmed = window.confirm("Bu virtual hisobni olib tashlamoqchimisiz?");
      if (!confirmed) return;
      setBusy(true, "Hisob olib tashlanmoqda");
      try {
        await api("/api/accounts/" + id, { method: "DELETE" });
        toast("Virtual hisob olib tashlandi");
        haptic();
        await load();
      } catch (error) {
        toast(error.message, false);
      } finally {
        setBusy(false);
      }
    }

    if (!initData) {
      showStatus("WebApp'ni Telegram bot ichidagi Open tugmasi orqali oching.", false);
    } else {
      load();
    }
  </script>
</body>
</html>
"""
