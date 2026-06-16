from __future__ import annotations

# ruff: noqa: E501
import asyncio
import hashlib
import hmac
import json
import logging
import shutil
import time
from html import escape
from pathlib import Path
from urllib.parse import parse_qsl, quote

from aiogram import Bot
from aiohttp import web

from app.config import Settings
from app.database import Database
from app.security import generate_code, hash_code, hash_password

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


async def _auth_admin(request: web.Request) -> dict:
    user = _auth_user(request)
    settings: Settings = request.app["settings"]
    database: Database = request.app["database"]
    if not await database.is_admin(int(user["id"]), settings.admin_ids):
        raise web.HTTPForbidden(text="Bu bo'lim faqat admin uchun")
    return user


def _serialize_profile(profile) -> dict | None:
    if not profile:
        return None
    return {
        "first_name": profile.first_name,
        "last_name": profile.last_name,
        "phone": profile.phone,
        "phone_verified": profile.phone_verified,
        "password_set": profile.password_set,
        "avatar_data": profile.avatar_data,
    }


async def index_handler(_request: web.Request) -> web.Response:
    return web.Response(text=WEBAPP_HTML, content_type="text/html")


async def health_handler(request: web.Request) -> web.Response:
    settings: Settings = request.app["settings"]
    return web.json_response(
        {
            "ok": True,
            "ai_configured": bool(settings.huggingface_api_token),
            "ai_model": settings.huggingface_music_model,
            "music_generation_configured": bool(
                settings.huggingface_api_token and settings.huggingface_music_model
            ),
            "voice_search_configured": bool(settings.huggingface_api_token),
            "asr_model": settings.huggingface_asr_model,
            "admin_configured": bool(settings.admin_ids),
            "deno_available": bool(shutil.which("deno")),
        }
    )


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
    downloads = await database.recent_downloads(user_id, 15)
    language = await database.get_language(user_id)
    settings: Settings = request.app["settings"]
    ai_until = await database.ai_subscription_until(user_id)
    is_admin = await database.is_admin(user_id, settings.admin_ids)
    return web.json_response(
        {
            "telegram_user": {
                "id": user_id,
                "username": user.get("username"),
                "first_name": user.get("first_name", ""),
                "last_name": user.get("last_name", ""),
            },
            "profile": _serialize_profile(profile),
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
            "ai_subscription_until": ai_until,
            "ai_configured": bool(settings.huggingface_api_token),
            "ai_model": settings.huggingface_music_model,
            "music_generation_configured": bool(
                settings.huggingface_api_token and settings.huggingface_music_model
            ),
            "voice_search_configured": bool(settings.huggingface_api_token),
            "asr_model": settings.huggingface_asr_model,
            "language": language,
            "is_admin": is_admin,
            "bot_username": request.app["bot_username"],
        }
    )


async def admin_summary_handler(request: web.Request) -> web.Response:
    await _auth_admin(request)
    database: Database = request.app["database"]
    return web.json_response(
        {
            "stats": await database.admin_stats(),
            "users": await database.admin_users(limit=30),
            "errors": await database.admin_errors(limit=20),
            "admins": await database.admin_list_admins(),
        }
    )


async def admin_users_handler(request: web.Request) -> web.Response:
    await _auth_admin(request)
    database: Database = request.app["database"]
    query = request.query.get("q", "").strip()
    users = (
        await database.admin_search_users(query, limit=50)
        if query
        else await database.admin_users(limit=50)
    )
    return web.json_response({"users": users})


async def admin_activate_ai_handler(request: web.Request) -> web.Response:
    admin = await _auth_admin(request)
    data = await _json_body(request)
    try:
        user_id = int(data.get("user_id", 0))
        days = int(data.get("days", 0))
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text="USER_ID va DAYS son bo'lishi kerak") from exc
    if days not in {30, 90, 365}:
        raise web.HTTPBadRequest(text="Muddat faqat 30, 90 yoki 365 kun")
    database: Database = request.app["database"]
    expires_at = await database.activate_ai_subscription(
        user_id,
        days=days,
        admin_id=int(admin["id"]),
        note=str(data.get("note", "WebApp admin activation")),
    )
    return web.json_response({"ok": True, "user_id": user_id, "expires_at": expires_at})


async def admin_add_admin_handler(request: web.Request) -> web.Response:
    admin = await _auth_admin(request)
    data = await _json_body(request)
    try:
        user_id = int(data.get("user_id", 0))
    except (TypeError, ValueError) as exc:
        raise web.HTTPBadRequest(text="Admin USER_ID son bo'lishi kerak") from exc
    if user_id <= 0:
        raise web.HTTPBadRequest(text="Admin USER_ID noto'g'ri")
    database: Database = request.app["database"]
    await database.add_admin(user_id, created_by=int(admin["id"]))
    return web.json_response({"ok": True, "admins": await database.admin_list_admins()})


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


async def save_profile_handler(request: web.Request) -> web.Response:
    user = _auth_user(request)
    user_id = int(user["id"])
    data = await _json_body(request)
    first_name = str(data.get("first_name", "")).strip()
    last_name = str(data.get("last_name", "")).strip()
    phone = str(data.get("phone", "")).strip()
    password = str(data.get("password", ""))
    avatar_data = str(data.get("avatar_data", "")).strip()
    if not first_name:
        raise web.HTTPBadRequest(text="Ism majburiy")
    if phone and not phone.startswith("+"):
        raise web.HTTPBadRequest(text="Telefon +998... formatida bo'lishi kerak")
    if avatar_data and (
        not avatar_data.startswith("data:image/") or len(avatar_data) > 350_000
    ):
        raise web.HTTPBadRequest(text="Rasm hajmi katta yoki format noto'g'ri")
    database: Database = request.app["database"]
    profile = await database.upsert_profile(
        user_id,
        first_name=first_name,
        last_name=last_name,
        phone=phone,
        avatar_data=avatar_data,
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
            web.get("/api/admin/summary", admin_summary_handler),
            web.get("/api/admin/users", admin_users_handler),
            web.post("/api/admin/activate-ai", admin_activate_ai_handler),
            web.post("/api/admin/add-admin", admin_add_admin_handler),
            web.post("/api/language", set_language_handler),
            web.post("/api/profile", save_profile_handler),
            web.post("/api/phone/request-code", request_code_handler),
            web.post("/api/phone/verify", verify_code_handler),
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
  <title>Saved Insta Bot</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root {
      color-scheme: dark;
      --bg: var(--tg-theme-bg-color, #07101d);
      --card: var(--tg-theme-secondary-bg-color, #101b2b);
      --text: var(--tg-theme-text-color, #f8fbff);
      --muted: var(--tg-theme-hint-color, #93a4b8);
      --button: var(--tg-theme-button-color, #2aabee);
      --button-text: var(--tg-theme-button-text-color, #fff);
      --border: rgba(148, 163, 184, .16);
      font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--text);
      background:
        radial-gradient(circle at 10% 0%, rgba(42,171,238,.22), transparent 35%),
        radial-gradient(circle at 100% 20%, rgba(124,92,255,.18), transparent 32%),
        var(--bg);
    }
    .app { width: min(100%, 760px); margin: 0 auto; padding: 16px 14px 34px; }
    .top { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
    .brand { display: flex; gap: 12px; align-items: center; }
    .logo, .avatar { display: grid; place-items: center; overflow: hidden; color: #fff; font-weight: 900; }
    .logo { width: 44px; height: 44px; border-radius: 15px; background: linear-gradient(135deg,#2aabee,#7c5cff); }
    .avatar { width: 72px; height: 72px; border-radius: 24px; background: linear-gradient(135deg,#2aabee,#7c5cff); font-size: 24px; }
    .avatar img { width: 100%; height: 100%; object-fit: cover; }
    h1, h2, h3, p { margin: 0; }
    h1 { font-size: 20px; }
    .muted { color: var(--muted); font-size: 12px; line-height: 1.45; }
    .pill { padding: 8px 10px; border: 1px solid rgba(80,220,140,.28); border-radius: 999px; color: #8df0b2; background: rgba(80,220,140,.09); font-size: 11px; font-weight: 800; }
    .card { margin-top: 14px; padding: 17px; border: 1px solid var(--border); border-radius: 22px; background: rgba(16,27,43,.88); box-shadow: 0 18px 50px rgba(0,0,0,.16); }
    .profile-head { display: flex; gap: 14px; align-items: center; }
    .grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 14px; }
    .full { grid-column: 1 / -1; }
    label { display: block; margin: 0 0 6px 3px; color: var(--muted); font-size: 11px; font-weight: 750; }
    input, select { width: 100%; height: 46px; padding: 0 13px; border: 1px solid var(--border); border-radius: 14px; outline: 0; color: var(--text); background: rgba(2,8,18,.46); font: inherit; }
    input[type=file] { height: auto; padding: 12px; }
    button { min-height: 46px; border: 0; border-radius: 14px; padding: 0 14px; color: var(--button-text); background: linear-gradient(135deg,var(--button),#477bff); font: inherit; font-weight: 850; cursor: pointer; }
    button.secondary { color: var(--text); background: rgba(148,163,184,.12); }
    .actions { display: flex; gap: 10px; margin-top: 12px; }
    .actions button { flex: 1; }
    .status { margin-top: 10px; color: #8df0b2; font-size: 12px; line-height: 1.45; }
    .status.err { color: #ff8991; }
    .hidden { display: none !important; }
    .stats { display: grid; grid-template-columns: repeat(2, 1fr); gap: 9px; margin-top: 12px; }
    .stat { padding: 12px; border: 1px solid var(--border); border-radius: 16px; background: rgba(148,163,184,.09); }
    .stat strong { display: block; font-size: 20px; }
    .list { display: grid; gap: 9px; margin-top: 12px; }
    .item { display: flex; justify-content: space-between; gap: 12px; padding: 13px; border: 1px solid var(--border); border-radius: 16px; background: rgba(42,171,238,.07); }
    .item strong { display: block; font-size: 13px; word-break: break-word; }
    .item span { color: var(--muted); font-size: 11px; }
    .row { display: flex; gap: 9px; margin-top: 10px; }
    .row input { flex: 1; }
    .toast { position: fixed; left: 14px; right: 14px; bottom: 18px; display: none; padding: 13px 14px; border-radius: 15px; color: #fff; background: rgba(8,16,28,.94); box-shadow: 0 18px 50px rgba(0,0,0,.35); }
    @media (max-width: 520px) { .grid { grid-template-columns: 1fr; } .row, .actions { flex-direction: column; } }
  </style>
</head>
<body>
  <main class="app">
    <section class="top">
      <div class="brand">
        <div class="logo">SB</div>
        <div>
          <h1>Saved Insta Bot</h1>
          <p class="muted">Profil va so'rovlar paneli</p>
        </div>
      </div>
      <div class="pill">Secure WebApp</div>
    </section>

    <section class="card">
      <div class="profile-head">
        <div class="avatar" id="avatar">U</div>
        <div>
          <h2 id="display_name">Profil</h2>
          <p class="muted" id="username">Telegram orqali ochilgan</p>
          <p class="muted" id="ai_server">AI server: tekshirilmoqda...</p>
          <p class="muted" id="voice_search">Ovozli qidiruv: tekshirilmoqda...</p>
          <p class="muted" id="ai_status">AI obuna: tekshirilmoqda...</p>
        </div>
      </div>

      <div class="grid">
        <div><label>Ism</label><input id="first_name" autocomplete="given-name" /></div>
        <div><label>Familiya</label><input id="last_name" autocomplete="family-name" /></div>
        <div class="full"><label>Telefon</label><input id="phone" placeholder="+998..." autocomplete="tel" /></div>
        <div class="full"><label>Yangi parol</label><input id="password" type="password" placeholder="Ixtiyoriy" /></div>
        <div class="full"><label>Profil rasmi</label><input id="avatar_file" type="file" accept="image/*" /></div>
      </div>
      <div class="actions">
        <button onclick="saveProfile()">Profilni saqlash</button>
        <button class="secondary" onclick="requestCode()">Telefon kodi</button>
      </div>
      <div class="row">
        <input id="code" placeholder="6 xonali kod" inputmode="numeric" maxlength="6" />
        <button class="secondary" onclick="verifyCode()">Tasdiqlash</button>
      </div>
      <div class="status" id="profile_status">Yuklanmoqda...</div>
    </section>

    <section class="card hidden" id="history_card">
      <h2>So'rovlarim</h2>
      <p class="muted">Bot orqali yuborgan video/MP3 yuklashlaringiz.</p>
      <div class="list" id="download_history"></div>
    </section>

    <section class="card">
      <h2>AI qo'shiq obunasi</h2>
      <p class="muted">Matn asosida AI musiqa yaratish uchun muddatli obuna.</p>
      <div class="list">
        <article class="item">
          <div><strong>30 / 90 / 365 kunlik AI tarif</strong><span id="ai_plan_model">Model tekshirilmoqda...</span></div>
          <span>Narx admin bilan</span>
        </article>
      </div>
      <p class="muted">Obuna olish uchun botda “AI qo'shiq / Obuna” tugmasini yoki /tarif komandasini bosing.</p>
    </section>

    <section class="card hidden" id="admin_panel">
      <h2>Admin panel</h2>
      <p class="muted">Foydalanuvchilar, obunalar, xatolar va adminlar.</p>
      <div class="stats" id="admin_stats"></div>

      <h3 style="margin-top:16px">User qidirish</h3>
      <div class="row">
        <input id="admin_query" placeholder="ID, username, ism yoki telefon" />
        <button class="secondary" onclick="searchAdminUsers()">Qidirish</button>
      </div>
      <div class="list" id="admin_users"></div>

      <h3 style="margin-top:16px">AI obuna berish</h3>
      <div class="grid">
        <div><label>User ID</label><input id="activate_user_id" inputmode="numeric" /></div>
        <div><label>Muddat</label><select id="activate_days"><option>30</option><option>90</option><option>365</option></select></div>
      </div>
      <button style="margin-top:10px;width:100%" onclick="activateAi()">AI obunani faollashtirish</button>

      <h3 style="margin-top:16px">Admin qo'shish</h3>
      <div class="row">
        <input id="new_admin_id" placeholder="Telegram user ID" inputmode="numeric" />
        <button class="secondary" onclick="addAdmin()">Qo'shish</button>
      </div>
      <div class="list" id="admin_list"></div>

      <h3 style="margin-top:16px">Oxirgi xatolar</h3>
      <div class="list" id="admin_errors"></div>
    </section>

  </main>
  <div class="toast" id="toast"></div>

  <script>
    const tg = window.Telegram?.WebApp;
    const initData = tg?.initData || "";
    let avatarData = "";
    tg?.ready();
    tg?.expand();

    const htmlEscapes = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
    function escapeHtml(value) {
      return String(value ?? "").replace(/[&<>"']/g, ch => htmlEscapes[ch]);
    }
    function api(path, options = {}) {
      return fetch(path, {
        ...options,
        headers: {"Content-Type":"application/json", "X-Telegram-Init-Data": initData, ...(options.headers || {})}
      }).then(async response => {
        if (!response.ok) throw new Error(await response.text() || "So'rov bajarilmadi");
        return response.json();
      });
    }
    function toast(text, ok = true) {
      const el = document.getElementById("toast");
      el.textContent = text;
      el.style.display = "block";
      el.style.border = ok ? "1px solid rgba(80,220,140,.32)" : "1px solid rgba(255,95,105,.38)";
      clearTimeout(window.__toastTimer);
      window.__toastTimer = setTimeout(() => el.style.display = "none", 2800);
    }
    function initials(first, last) {
      return ((first || "").trim()[0] || "U") + ((last || "").trim()[0] || "");
    }
    function setAvatar(data, first, last) {
      const root = document.getElementById("avatar");
      if (data) root.innerHTML = `<img src="${data}" alt="avatar">`;
      else root.textContent = initials(first, last).toUpperCase();
    }
    function dateText(timestamp) {
      if (!timestamp) return "yo'q";
      return new Date(timestamp * 1000).toLocaleDateString();
    }
    function showStatus(text, ok = true) {
      const el = document.getElementById("profile_status");
      el.textContent = text;
      el.className = ok ? "status" : "status err";
    }

    document.getElementById("avatar_file").addEventListener("change", event => {
      const file = event.target.files?.[0];
      if (!file) return;
      if (file.size > 250000) { toast("Rasm 250 KBdan kichik bo'lsin", false); return; }
      const reader = new FileReader();
      reader.onload = () => { avatarData = String(reader.result || ""); setAvatar(avatarData); };
      reader.readAsDataURL(file);
    });

    async function load() {
      try {
        const data = await api("/api/me");
        const p = data.profile || {};
        const user = data.telegram_user || {};
        const first = p.first_name || user.first_name || "Telegram";
        const last = p.last_name || user.last_name || "User";
        avatarData = p.avatar_data || "";
        document.getElementById("display_name").textContent = `${first} ${last}`;
        document.getElementById("username").textContent = user.username ? `@${user.username}` : `Telegram ID: ${user.id}`;
        document.getElementById("first_name").value = p.first_name || user.first_name || "";
        document.getElementById("last_name").value = p.last_name || user.last_name || "";
        document.getElementById("phone").value = p.phone || "";
        document.getElementById("ai_server").textContent = data.ai_configured ? `AI server: ulangan (${data.ai_model})` : "AI server: ulanmagan";
        document.getElementById("voice_search").textContent = data.voice_search_configured ? `Ovozli qidiruv: ulangan (${data.asr_model})` : "Ovozli qidiruv: ulanmagan";
        document.getElementById("ai_status").textContent = data.ai_subscription_until ? `AI obuna: ${dateText(data.ai_subscription_until)} gacha` : "AI obuna: faol emas";
        document.getElementById("ai_plan_model").textContent = data.ai_configured ? `AI model: ${data.ai_model}` : "AI server ulanmagan";
        setAvatar(avatarData, first, last);
        showStatus(p.phone_verified ? "Telefon tasdiqlangan." : "Telefon hali tasdiqlanmagan.", !!p.phone_verified);
        if (data.is_admin) {
          document.getElementById("admin_panel").classList.remove("hidden");
          document.getElementById("history_card").classList.remove("hidden");
          renderHistory(data.downloads || []);
          await loadAdmin();
        }
      } catch (error) {
        showStatus(error.message, false);
        toast(error.message, false);
      }
    }

    function renderHistory(items) {
      const root = document.getElementById("download_history");
      if (!items.length) { root.innerHTML = "<div class='muted'>Hali so'rovlar yo'q.</div>"; return; }
      root.innerHTML = items.map(item => `
        <article class="item">
          <div><strong>${escapeHtml(item.title || item.source_url || "Media")}</strong><span>${escapeHtml(item.media_type)} · ${escapeHtml(item.quality)} · ${escapeHtml(item.status)}</span></div>
          <span>${escapeHtml(item.created_at)}</span>
        </article>`).join("");
    }

    function renderStats(stats) {
      const labels = {
        users: "Jami userlar",
        new_today: "Yangi 24 soat",
        active_today: "Aktiv 24 soat",
        downloads: "Yuklashlar",
        ai_generations: "AI urinishlari",
        ai_subscriptions: "AI obunalar",
        errors: "Xatolar"
      };
      document.getElementById("admin_stats").innerHTML = Object.keys(labels).map(key => `
        <div class="stat"><strong>${escapeHtml(stats[key] ?? 0)}</strong><span class="muted">${labels[key]}</span></div>
      `).join("");
    }
    function userBadge(user) {
      if (user.online) return "🟢 online";
      if (user.ai_subscription_until) return "💎 obunachi";
      if ((user.download_count || 0) >= 10) return "⭐ doimiy";
      return "⚪ user";
    }
    function renderAdminUsers(users) {
      const root = document.getElementById("admin_users");
      if (!users.length) { root.innerHTML = "<div class='muted'>User topilmadi.</div>"; return; }
      root.innerHTML = users.map(user => `
        <article class="item">
          <div>
            <strong>${escapeHtml(user.first_name || user.full_name || user.username || user.user_id)} ${escapeHtml(user.last_name || "")}</strong>
            <span>ID: ${escapeHtml(user.user_id)} · ${escapeHtml(user.username ? "@" + user.username : "username yo'q")} · ${escapeHtml(user.phone || "tel yo'q")}</span>
            <span>${userBadge(user)} · yuklash: ${escapeHtml(user.download_count || 0)} · AI: ${user.ai_subscription_until ? dateText(user.ai_subscription_until) : "yo'q"}</span>
          </div>
          <button class="secondary" onclick="fillActivate(${Number(user.user_id)})">Tanlash</button>
        </article>
      `).join("");
    }
    function renderAdminErrors(errors) {
      const root = document.getElementById("admin_errors");
      if (!errors.length) { root.innerHTML = "<div class='muted'>Xato loglari yo'q.</div>"; return; }
      root.innerHTML = errors.map(error => `
        <article class="item">
          <div><strong>${escapeHtml(error.context)} · ${escapeHtml(error.user_id || "")}</strong><span>${escapeHtml(error.message)}</span></div>
          <span>${escapeHtml(error.created_at)}</span>
        </article>
      `).join("");
    }
    function renderAdmins(admins) {
      const root = document.getElementById("admin_list");
      if (!admins.length) { root.innerHTML = "<div class='muted'>Adminlar ro'yxati bo'sh.</div>"; return; }
      root.innerHTML = admins.map(admin => `
        <article class="item">
          <div><strong>${escapeHtml(admin.full_name || admin.username || admin.user_id)}</strong><span>ID: ${escapeHtml(admin.user_id)} · qo'shgan: ${escapeHtml(admin.created_by || "")}</span></div>
          <span>${escapeHtml(admin.created_at)}</span>
        </article>
      `).join("");
    }
    async function loadAdmin() {
      try {
        const data = await api("/api/admin/summary");
        renderStats(data.stats || {});
        renderAdminUsers(data.users || []);
        renderAdminErrors(data.errors || []);
        renderAdmins(data.admins || []);
      } catch (error) { toast(error.message, false); }
    }
    async function searchAdminUsers() {
      try {
        const q = encodeURIComponent(document.getElementById("admin_query").value);
        const data = await api(`/api/admin/users?q=${q}`);
        renderAdminUsers(data.users || []);
      } catch (error) { toast(error.message, false); }
    }
    function fillActivate(userId) {
      document.getElementById("activate_user_id").value = String(userId);
      toast("User ID aktivatsiya maydoniga qo'yildi");
    }
    async function activateAi() {
      try {
        const payload = {
          user_id: document.getElementById("activate_user_id").value,
          days: document.getElementById("activate_days").value,
          note: "WebApp admin"
        };
        await api("/api/admin/activate-ai", {method:"POST", body: JSON.stringify(payload)});
        toast("AI obuna faollashtirildi");
        await loadAdmin();
      } catch (error) { toast(error.message, false); }
    }
    async function addAdmin() {
      try {
        await api("/api/admin/add-admin", {method:"POST", body: JSON.stringify({user_id: document.getElementById("new_admin_id").value})});
        document.getElementById("new_admin_id").value = "";
        toast("Admin qo'shildi");
        await loadAdmin();
      } catch (error) { toast(error.message, false); }
    }

    async function saveProfile() {
      try {
        const payload = {
          first_name: document.getElementById("first_name").value,
          last_name: document.getElementById("last_name").value,
          phone: document.getElementById("phone").value.replace(/\\s/g, ""),
          password: document.getElementById("password").value,
          avatar_data: avatarData
        };
        await api("/api/profile", {method:"POST", body: JSON.stringify(payload)});
        document.getElementById("password").value = "";
        toast("Profil saqlandi");
        await load();
      } catch (error) { showStatus(error.message, false); toast(error.message, false); }
    }
    async function requestCode() {
      try {
        const phone = document.getElementById("phone").value.replace(/\\s/g, "");
        await api("/api/phone/request-code", {method:"POST", body: JSON.stringify({phone})});
        toast("Kod bot chatiga yuborildi");
      } catch (error) { showStatus(error.message, false); toast(error.message, false); }
    }
    async function verifyCode() {
      try {
        await api("/api/phone/verify", {method:"POST", body: JSON.stringify({code: document.getElementById("code").value})});
        document.getElementById("code").value = "";
        toast("Telefon tasdiqlandi");
        await load();
      } catch (error) { showStatus(error.message, false); toast(error.message, false); }
    }
    if (!initData) showStatus("WebApp'ni Telegram ichidagi Open tugmasi orqali oching.", false);
    else load();
  </script>
</body>
</html>
"""
