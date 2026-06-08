from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def _as_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} integer bo'lishi kerak") from exc


def _as_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} true/false bo'lishi kerak")


def _as_list(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, "").split(",") if item.strip())


@dataclass(frozen=True, slots=True)
class Settings:
    bot_token: str
    database_url: str
    redis_url: str
    sentry_dsn: str | None
    webhook_url: str | None
    webhook_secret: str | None
    host: str
    port: int
    storage_dir: Path
    max_download_mb: int
    max_duration_seconds: int
    concurrent_downloads: int
    rotating_proxies: tuple[str, ...]
    proxy_file: Path | None
    yt_dlp_cookies: Path | None
    audd_api_key: str | None
    local_ai_enabled: bool
    progress_interval_seconds: int
    cache_ttl_days: int

    @property
    def max_download_bytes(self) -> int:
        return self.max_download_mb * 1024 * 1024

    @classmethod
    def load(cls, env_file: str | Path | None = None) -> Settings:
        load_dotenv(env_file)
        root = Path(os.getenv("APP_ROOT", Path.cwd())).resolve()
        token = os.getenv("BOT_TOKEN", "").strip()
        if not token:
            raise ValueError("BOT_TOKEN majburiy")

        database_url = os.getenv("DATABASE_URL", "").strip() or (
            "postgresql+asyncpg://postgres:postgres@postgres:5432/media_bot"
        )
        redis_url = os.getenv("REDIS_URL", "").strip() or "redis://redis:6379/0"
        cookies = os.getenv("YTDLP_COOKIES_FILE", "").strip()
        proxy_file = os.getenv("ROTATING_PROXY_FILE", "").strip()
        return cls(
            bot_token=token,
            database_url=database_url,
            redis_url=redis_url,
            sentry_dsn=os.getenv("SENTRY_DSN", "").strip() or None,
            webhook_url=os.getenv("WEBHOOK_URL", "").strip().rstrip("/") or None,
            webhook_secret=os.getenv("WEBHOOK_SECRET", "").strip() or None,
            host=os.getenv("BOT_HOST", "0.0.0.0").strip(),
            port=_as_int("PORT", _as_int("BOT_PORT", 8080)),
            storage_dir=Path(os.getenv("STORAGE_DIR", root / "tmp" / "superapp")).resolve(),
            max_download_mb=_as_int("MAX_DOWNLOAD_MB", 1500),
            max_duration_seconds=_as_int("MAX_DURATION_SECONDS", 4 * 60 * 60),
            concurrent_downloads=_as_int("CONCURRENT_DOWNLOADS", 4),
            rotating_proxies=_as_list("ROTATING_PROXIES"),
            proxy_file=Path(proxy_file).resolve() if proxy_file else None,
            yt_dlp_cookies=Path(cookies).resolve() if cookies else None,
            audd_api_key=os.getenv("AUDD_API_KEY", "").strip() or None,
            local_ai_enabled=_as_bool("LOCAL_AI_ENABLED", True),
            progress_interval_seconds=_as_int("PROGRESS_INTERVAL_SECONDS", 3),
            cache_ttl_days=_as_int("CACHE_TTL_DAYS", 90),
        )

    def prepare(self) -> None:
        self.storage_dir.mkdir(parents=True, exist_ok=True)


settings = Settings.load()
