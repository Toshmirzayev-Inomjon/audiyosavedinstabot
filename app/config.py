from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

DEFAULT_ADMIN_ID = 7795087338


def _as_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{name} butun son bo'lishi kerak") from exc


def _as_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} true/false bo'lishi kerak")


def _webapp_public_url() -> str | None:
    explicit_url = os.getenv("WEBAPP_PUBLIC_URL", "").strip().rstrip("/")
    if explicit_url:
        return explicit_url

    railway_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip().strip("/")
    if railway_domain:
        return f"https://{railway_domain}"

    return None


def _webapp_port() -> int:
    if os.getenv("WEBAPP_PORT", "").strip():
        return _as_int("WEBAPP_PORT", 8080)
    return _as_int("PORT", 8080)


def _parse_admins(raw: str) -> frozenset[int]:
    if not raw.strip():
        return frozenset()
    try:
        return frozenset(int(item.strip()) for item in raw.split(",") if item.strip())
    except ValueError as exc:
        raise ValueError("ADMIN_IDS vergul bilan ajratilgan Telegram IDlar bo'lishi kerak") from exc


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    admin_ids: frozenset[int]
    database_path: Path
    temp_dir: Path
    max_download_mb: int
    max_duration_minutes: int
    cookies_file: Path | None
    telegram_api_id: int | None
    telegram_api_hash: str | None
    telegram_session_path: Path
    bot_api_base: str | None
    bot_api_local: bool
    webapp_public_url: str | None
    webapp_host: str
    webapp_port: int
    phone_code_ttl_seconds: int
    database_url: str | None = None
    telegram_upload_mb: int = 49
    queue_concurrency: int = 2
    public_file_ttl_seconds: int = 3_600
    huggingface_api_token: str | None = None
    huggingface_music_model: str = "facebook/musicgen-small"
    huggingface_asr_model: str = "openai/whisper-large-v3-turbo"
    audd_api_token: str | None = None

    @property
    def max_download_bytes(self) -> int:
        return self.max_download_mb * 1024 * 1024

    @property
    def max_duration_seconds(self) -> int:
        return self.max_duration_minutes * 60

    @property
    def telegram_upload_bytes(self) -> int:
        return self.telegram_upload_mb * 1024 * 1024

    @property
    def telegram_links_enabled(self) -> bool:
        return bool(self.telegram_api_id and self.telegram_api_hash)

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> Settings:
        load_dotenv(env_file)
        root = Path(os.getenv("APP_ROOT", Path.cwd())).resolve()
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("BOT_TOKEN .env faylida berilishi kerak")

        cookies_raw = os.getenv("YTDLP_COOKIES_FILE", "").strip()
        api_id = _as_int("TELEGRAM_API_ID", 0) or None
        api_hash = os.getenv("TELEGRAM_API_HASH", "").strip() or None
        if bool(api_id) != bool(api_hash):
            raise ValueError("TELEGRAM_API_ID va TELEGRAM_API_HASH birga berilishi kerak")

        settings = cls(
            bot_token=token,
            admin_ids=_parse_admins(
                os.getenv("ADMIN_IDS", "").strip() or str(DEFAULT_ADMIN_ID)
            ),
            database_path=Path(
                os.getenv("DATABASE_PATH", root / "data" / "bot.sqlite3")
            ).resolve(),
            temp_dir=Path(os.getenv("TEMP_DIR", root / "tmp")).resolve(),
            max_download_mb=_as_int("MAX_DOWNLOAD_MB", 500),
            max_duration_minutes=_as_int("MAX_DURATION_MINUTES", 660),
            cookies_file=Path(cookies_raw).resolve() if cookies_raw else None,
            telegram_api_id=api_id,
            telegram_api_hash=api_hash,
            telegram_session_path=Path(
                os.getenv("TELEGRAM_SESSION_PATH", root / "data" / "telegram_bot")
            ).resolve(),
            bot_api_base=os.getenv("BOT_API_BASE", "").strip().rstrip("/") or None,
            bot_api_local=_as_bool("BOT_API_LOCAL"),
            webapp_public_url=_webapp_public_url(),
            webapp_host=os.getenv("WEBAPP_HOST", "0.0.0.0").strip(),
            webapp_port=_webapp_port(),
            phone_code_ttl_seconds=_as_int("PHONE_CODE_TTL_SECONDS", 300),
            database_url=os.getenv("DATABASE_URL", "").strip() or None,
            telegram_upload_mb=_as_int("TELEGRAM_UPLOAD_MB", 49),
            queue_concurrency=_as_int("QUEUE_CONCURRENCY", 2),
            public_file_ttl_seconds=_as_int("PUBLIC_FILE_TTL_SECONDS", 3_600),
            huggingface_api_token=(
                os.getenv("HUGGINGFACE_API_TOKEN", "").strip() or None
            ),
            huggingface_music_model=os.getenv(
                "HUGGINGFACE_MUSIC_MODEL",
                "facebook/musicgen-small",
            ).strip(),
            huggingface_asr_model=os.getenv(
                "HUGGINGFACE_ASR_MODEL",
                "openai/whisper-large-v3-turbo",
            ).strip(),
            audd_api_token=os.getenv("AUDD_API_TOKEN", "").strip() or None,
        )
        if settings.max_download_mb <= 0 or settings.max_duration_minutes <= 0:
            raise ValueError("Media limitlari musbat bo'lishi kerak")
        if settings.webapp_port <= 0 or settings.phone_code_ttl_seconds <= 0:
            raise ValueError("WebApp sozlamalari musbat bo'lishi kerak")
        if (
            settings.telegram_upload_mb <= 0
            or settings.queue_concurrency <= 0
            or settings.public_file_ttl_seconds <= 0
        ):
            raise ValueError("Limit sozlamalari musbat bo'lishi kerak")
        if settings.bot_api_local and not settings.bot_api_base:
            raise ValueError("BOT_API_LOCAL=true bo'lsa BOT_API_BASE berilishi kerak")
        if not settings.huggingface_music_model:
            raise ValueError("HUGGINGFACE_MUSIC_MODEL bo'sh bo'lishi mumkin emas")
        if not settings.huggingface_asr_model:
            raise ValueError("HUGGINGFACE_ASR_MODEL bo'sh bo'lishi mumkin emas")
        return settings

    def prepare_directories(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self.telegram_session_path.parent.mkdir(parents=True, exist_ok=True)
