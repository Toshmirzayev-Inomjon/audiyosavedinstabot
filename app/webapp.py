from __future__ import annotations

# ruff: noqa: E501
import hashlib
import hmac
import json
import logging
import time
from html import escape
from urllib.parse import parse_qsl

from aiogram import Bot
from aiohttp import web

from app.config import Settings
from app.database import Database
from app.security import generate_code, hash_code, hash_password

logger = logging.getLogger(__name__)


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
            "limitations": {
                "real_bank_cards": False,
                "message": (
                    "Bu ichki virtual hisob. Real karta/bank hisob ochish uchun "
                    "alohida to'lov provayderi integratsiyasi kerak."
                ),
            },
        }
    )


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
) -> web.AppRunner:
    app = web.Application()
    app["settings"] = settings
    app["database"] = database
    app["bot"] = bot
    app.add_routes(
        [
            web.get("/", index_handler),
            web.get("/health", health_handler),
            web.get("/api/me", me_handler),
            web.post("/api/profile", save_profile_handler),
            web.post("/api/phone/request-code", request_code_handler),
            web.post("/api/phone/verify", verify_code_handler),
            web.post("/api/accounts", create_account_handler),
            web.delete("/api/accounts/{account_id:\\d+}", remove_account_handler),
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
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Profil</title>
  <script src="https://telegram.org/js/telegram-web-app.js"></script>
  <style>
    :root { color-scheme: dark; font-family: Arial, sans-serif; }
    body { margin: 0; background: #0f1720; color: #f8fafc; }
    main { padding: 16px; max-width: 720px; margin: auto; }
    .card { background: #17212b; border: 1px solid #263442; border-radius: 14px; padding: 14px; margin-bottom: 14px; }
    label { display: block; font-size: 13px; color: #93a4b7; margin: 10px 0 5px; }
    input { width: 100%; box-sizing: border-box; padding: 11px; border-radius: 10px; border: 1px solid #33485c; background: #0b121a; color: white; }
    button { border: 0; border-radius: 10px; padding: 11px 14px; background: #3b82f6; color: white; font-weight: 700; margin-top: 10px; cursor: pointer; }
    button.secondary { background: #334155; }
    button.danger { background: #dc2626; }
    .row { display: flex; gap: 8px; flex-wrap: wrap; }
    .muted { color: #94a3b8; font-size: 13px; }
    .ok { color: #22c55e; }
    .warn { color: #f59e0b; }
    .account { display:flex; align-items:center; justify-content:space-between; gap: 10px; padding: 10px 0; border-top: 1px solid #263442; }
    #overlay { display:none; position:fixed; inset:0; background:rgba(2,6,23,.86); align-items:center; justify-content:center; text-align:center; z-index:10; }
    .spinner { width: 54px; height: 54px; border-radius: 50%; border: 5px solid #334155; border-top-color: #38bdf8; animation: spin 1s linear infinite; margin: 0 auto 14px; }
    @keyframes spin { to { transform: rotate(360deg); } }
  </style>
</head>
<body>
  <main>
    <h2>Profil va ichki hisob</h2>
    <p class="muted">Bu bo'lim faqat Telegram WebApp orqali ishlaydi. Real bank kartasi ochilmaydi; bu bot ichidagi virtual hisob.</p>

    <section class="card">
      <h3>Balans</h3>
      <div id="balance">Yuklanmoqda...</div>
      <p class="muted">Stars to'lovi 5 soniya tekshiruvdan keyin ichki balansga tushadi.</p>
    </section>

    <section class="card">
      <h3>Profil</h3>
      <label>Ism</label>
      <input id="first_name" autocomplete="given-name" />
      <label>Familiya</label>
      <input id="last_name" autocomplete="family-name" />
      <label>Telefon</label>
      <input id="phone" placeholder="+998901234567" autocomplete="tel" />
      <label>Yangi parol (kamida 6 belgi)</label>
      <input id="password" type="password" autocomplete="new-password" />
      <div class="row">
        <button onclick="saveProfile()">Profilni saqlash</button>
        <button class="secondary" onclick="requestCode()">Telegram kod yuborish</button>
      </div>
      <label>Tasdiqlash kodi</label>
      <input id="code" placeholder="123456" inputmode="numeric" />
      <button class="secondary" onclick="verifyCode()">Kodni tasdiqlash</button>
      <p id="profile_status" class="muted"></p>
    </section>

    <section class="card">
      <h3>Hisoblar</h3>
      <label>Yangi virtual hisob nomi</label>
      <input id="account_title" placeholder="Asosiy hisob" />
      <button onclick="createAccount()">Yangi hisob ochish</button>
      <div id="accounts"></div>
    </section>
  </main>

  <div id="overlay">
    <div>
      <div class="spinner"></div>
      <h3>To'lov tekshirilmoqda...</h3>
      <p class="muted">Iltimos, kuting.</p>
    </div>
  </div>

  <script>
    const tg = window.Telegram?.WebApp;
    if (tg) { tg.ready(); tg.expand(); }
    const initData = tg?.initData || "";

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

    function showStatus(text, ok = true) {
      const el = document.getElementById("profile_status");
      el.textContent = text;
      el.className = ok ? "ok" : "warn";
    }

    async function load() {
      try {
        const data = await api("/api/me");
        document.getElementById("balance").textContent = money(data.balance);
        const p = data.profile || {};
        document.getElementById("first_name").value = p.first_name || data.telegram_user.first_name || "";
        document.getElementById("last_name").value = p.last_name || data.telegram_user.last_name || "";
        document.getElementById("phone").value = p.phone || "";
        showStatus(
          p.phone_verified ? "Telefon tasdiqlangan. Parol: " + (p.password_set ? "o'rnatilgan" : "o'rnatilmagan") : "Telefon hali tasdiqlanmagan",
          !!p.phone_verified
        );
        renderAccounts(data.accounts || []);
      } catch (e) {
        showStatus(e.message, false);
      }
    }

    function renderAccounts(accounts) {
      const root = document.getElementById("accounts");
      if (!accounts.length) {
        root.innerHTML = "<p class='muted'>Hali hisob ochilmagan.</p>";
        return;
      }
      root.innerHTML = accounts.map(a => `
        <div class="account">
          <div><b>${a.title}</b><br><span class="muted">${a.account_number}</span></div>
          <button class="danger" onclick="removeAccount(${a.id})">Olib tashlash</button>
        </div>
      `).join("");
    }

    async function saveProfile() {
      try {
        const payload = {
          first_name: document.getElementById("first_name").value,
          last_name: document.getElementById("last_name").value,
          phone: document.getElementById("phone").value,
          password: document.getElementById("password").value
        };
        await api("/api/profile", { method: "POST", body: JSON.stringify(payload) });
        document.getElementById("password").value = "";
        showStatus("Profil saqlandi.");
        await load();
      } catch (e) { showStatus(e.message, false); }
    }

    async function requestCode() {
      try {
        const phone = document.getElementById("phone").value;
        await api("/api/phone/request-code", { method: "POST", body: JSON.stringify({ phone }) });
        showStatus("Kod Telegram chatga yuborildi.");
      } catch (e) { showStatus(e.message, false); }
    }

    async function verifyCode() {
      try {
        const code = document.getElementById("code").value;
        await api("/api/phone/verify", { method: "POST", body: JSON.stringify({ code }) });
        document.getElementById("code").value = "";
        showStatus("Telefon tasdiqlandi.");
        await load();
      } catch (e) { showStatus(e.message, false); }
    }

    async function createAccount() {
      try {
        const title = document.getElementById("account_title").value || "Asosiy hisob";
        await api("/api/accounts", { method: "POST", body: JSON.stringify({ title }) });
        document.getElementById("account_title").value = "";
        await load();
      } catch (e) { showStatus(e.message, false); }
    }

    async function removeAccount(id) {
      try {
        await api("/api/accounts/" + id, { method: "DELETE" });
        await load();
      } catch (e) { showStatus(e.message, false); }
    }

    load();
  </script>
</body>
</html>
"""
