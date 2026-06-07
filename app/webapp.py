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

    button, input { font: inherit; }
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
    input {
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
    input::placeholder { color: rgba(143,163,184,.55); }
    input:focus {
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

    <section class="section">
      <div class="section-head">
        <div class="section-title">
          <div class="section-icon">●</div>
          <div><h2>Shaxsiy profil</h2><div class="section-sub">Ma'lumotlaringizni boshqaring</div></div>
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
    </section>

    <section class="section">
      <div class="section-head">
        <div class="section-title">
          <div class="section-icon">▣</div>
          <div><h2>Virtual hisoblar</h2><div class="section-sub">Bot ichidagi hisob raqamlaringiz</div></div>
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

    async function load() {
      try {
        const data = await api("/api/me");
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
