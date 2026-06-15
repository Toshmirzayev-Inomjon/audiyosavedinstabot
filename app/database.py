from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT NOT NULL DEFAULT '',
    language TEXT NOT NULL DEFAULT 'uz',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    phone_verified INTEGER NOT NULL DEFAULT 0 CHECK (phone_verified IN (0, 1)),
    password_hash TEXT,
    avatar_data TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS phone_verification_codes (
    user_id INTEGER PRIMARY KEY,
    phone TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS downloads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    source_url TEXT,
    media_type TEXT NOT NULL,
    quality TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    telegram_file_id TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_downloads_user_id
ON downloads(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS public_files (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    path TEXT NOT NULL,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'application/octet-stream',
    expires_at INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS error_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    context TEXT NOT NULL,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_subscriptions (
    user_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'active',
    expires_at INTEGER NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    created_by INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
"""

POSTGRES_SCHEMA = (
    SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    .replace("user_id INTEGER", "user_id BIGINT")
    .replace("created_by INTEGER", "created_by BIGINT")
)


class _Connection:
    def __init__(self, raw: Any, postgres: bool) -> None:
        self.raw = raw
        self.postgres = postgres

    def __enter__(self) -> _Connection:
        self.raw.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool | None:
        return self.raw.__exit__(exc_type, exc, traceback)

    def _query(self, query: str) -> str:
        if not self.postgres:
            return query
        converted = query.replace("?", "%s").replace("BEGIN IMMEDIATE", "BEGIN")
        if "INSERT OR IGNORE INTO" in converted:
            converted = converted.replace("INSERT OR IGNORE INTO", "INSERT INTO")
            converted = converted.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
        return converted

    def execute(self, query: str, parameters: tuple | list = ()):
        return self.raw.execute(self._query(query), parameters)

    def executescript(self, script: str) -> None:
        if not self.postgres:
            self.raw.executescript(script)
            return
        for statement in script.split(";"):
            if statement.strip():
                self.raw.execute(statement)


@dataclass(frozen=True, slots=True)
class Profile:
    user_id: int
    first_name: str
    last_name: str
    phone: str
    phone_verified: bool
    password_set: bool
    avatar_data: str = ""


@dataclass(frozen=True, slots=True)
class DownloadRecord:
    id: int
    source_url: str | None
    media_type: str
    quality: str
    title: str
    status: str
    telegram_file_id: str | None
    created_at: str


class Database:
    def __init__(self, location: Path | str) -> None:
        raw_location = str(location)
        self.postgres = raw_location.startswith(("postgres://", "postgresql://"))
        self.database_url = (
            raw_location.replace("postgres://", "postgresql://", 1)
            if self.postgres
            else None
        )
        self.path = None if self.postgres else Path(location)

    def _connect(self) -> _Connection:
        if self.postgres:
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError("PostgreSQL uchun psycopg o'rnatilmagan") from exc
            return _Connection(psycopg.connect(self.database_url), True)
        if self.path is None:
            raise RuntimeError("SQLite database path topilmadi")
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys=ON")
        return _Connection(connection, False)

    async def initialize(self) -> None:
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            if not self.postgres:
                db.execute("PRAGMA journal_mode=WAL")
            db.executescript(POSTGRES_SCHEMA if self.postgres else SCHEMA)
            if self.postgres:
                db.execute(
                    "ALTER TABLE ai_subscriptions "
                    "ALTER COLUMN created_by TYPE BIGINT"
                )
            migrations = (
                (
                    "users",
                    "language",
                    "TEXT NOT NULL DEFAULT 'uz'",
                ),
                (
                    "profiles",
                    "avatar_data",
                    "TEXT NOT NULL DEFAULT ''",
                ),
            )
            for table, column, definition in migrations:
                if self.postgres:
                    db.execute(
                        f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                        f"{column} {definition}"
                    )
                else:
                    try:
                        db.execute(
                            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
                        )
                    except sqlite3.OperationalError as exc:
                        if "duplicate column name" not in str(exc).lower():
                            raise

    async def ensure_user(
        self,
        user_id: int,
        username: str | None = None,
        full_name: str = "",
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO users (user_id, username, full_name)
                VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = COALESCE(excluded.username, users.username),
                    full_name = CASE
                        WHEN excluded.full_name != '' THEN excluded.full_name
                        ELSE users.full_name
                    END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, username, full_name),
            )

    async def get_profile(self, user_id: int) -> Profile | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT user_id, first_name, last_name, phone, phone_verified,
                       password_hash, avatar_data
                FROM profiles WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if not row:
                return None
            return Profile(
                user_id=int(row[0]),
                first_name=str(row[1]),
                last_name=str(row[2]),
                phone=str(row[3]),
                phone_verified=bool(row[4]),
                password_set=bool(row[5]),
                avatar_data=str(row[6] or ""),
            )

    async def upsert_profile(
        self,
        user_id: int,
        *,
        first_name: str,
        last_name: str,
        phone: str,
        avatar_data: str | None = None,
    ) -> Profile:
        await self.ensure_user(user_id)
        first_name = first_name.strip()
        last_name = last_name.strip()
        phone = phone.strip()
        with self._connect() as db:
            existing = db.execute(
                "SELECT phone, phone_verified FROM profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            verified = int(
                bool(existing and str(existing[0]) == phone and int(existing[1]) == 1)
            )
            db.execute(
                """
                INSERT INTO profiles
                    (user_id, first_name, last_name, phone, phone_verified, avatar_data)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    phone = excluded.phone,
                    phone_verified = excluded.phone_verified,
                    avatar_data = CASE
                        WHEN excluded.avatar_data != '' THEN excluded.avatar_data
                        ELSE profiles.avatar_data
                    END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, first_name, last_name, phone, verified, avatar_data or ""),
            )
        profile = await self.get_profile(user_id)
        if not profile:
            raise RuntimeError("Profil saqlanmadi")
        return profile

    async def set_profile_password_hash(self, user_id: int, password_hash: str) -> None:
        await self.ensure_user(user_id)
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO profiles (user_id) VALUES (?)",
                (user_id,),
            )
            db.execute(
                """
                UPDATE profiles
                SET password_hash = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (password_hash, user_id),
            )

    async def store_phone_code(
        self,
        user_id: int,
        *,
        phone: str,
        code_hash: str,
        expires_at: int,
    ) -> None:
        await self.ensure_user(user_id)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO phone_verification_codes
                    (user_id, phone, code_hash, expires_at, attempts)
                VALUES (?, ?, ?, ?, 0)
                ON CONFLICT(user_id) DO UPDATE SET
                    phone = excluded.phone,
                    code_hash = excluded.code_hash,
                    expires_at = excluded.expires_at,
                    attempts = 0,
                    created_at = CURRENT_TIMESTAMP
                """,
                (user_id, phone.strip(), code_hash, expires_at),
            )

    async def verify_phone_code(self, user_id: int, code_hash: str) -> tuple[bool, str]:
        now = int(time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT phone, code_hash, expires_at, attempts
                FROM phone_verification_codes WHERE user_id = ?
                """,
                (user_id,),
            ).fetchone()
            if not row:
                return False, "Tasdiqlash kodi topilmadi"
            phone, expected_hash, expires_at, attempts = row
            if int(expires_at) < now:
                db.execute(
                    "DELETE FROM phone_verification_codes WHERE user_id = ?",
                    (user_id,),
                )
                return False, "Kod muddati tugagan"
            if int(attempts) >= 5:
                return False, "Urinishlar soni tugagan"
            if str(expected_hash) != code_hash:
                db.execute(
                    """
                    UPDATE phone_verification_codes
                    SET attempts = attempts + 1 WHERE user_id = ?
                    """,
                    (user_id,),
                )
                return False, "Kod noto'g'ri"
            db.execute(
                "INSERT OR IGNORE INTO profiles (user_id, phone) VALUES (?, ?)",
                (user_id, str(phone)),
            )
            db.execute(
                """
                UPDATE profiles
                SET phone = ?, phone_verified = 1, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (str(phone), user_id),
            )
            db.execute(
                "DELETE FROM phone_verification_codes WHERE user_id = ?",
                (user_id,),
            )
            return True, "Telefon tasdiqlandi"

    async def get_language(self, user_id: int) -> str:
        with self._connect() as db:
            row = db.execute(
                "SELECT language FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return str(row[0]) if row and row[0] in {"uz", "ru", "en"} else "uz"

    async def set_language(self, user_id: int, language: str) -> None:
        if language not in {"uz", "ru", "en"}:
            raise ValueError("Unsupported language")
        await self.ensure_user(user_id)
        with self._connect() as db:
            db.execute(
                """
                UPDATE users
                SET language = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (language, user_id),
            )

    async def create_download(
        self,
        user_id: int,
        *,
        source_url: str | None,
        media_type: str,
        quality: str,
    ) -> int:
        await self.ensure_user(user_id)
        with self._connect() as db:
            if self.postgres:
                return int(
                    db.execute(
                        """
                        INSERT INTO downloads
                            (user_id, source_url, media_type, quality)
                        VALUES (?, ?, ?, ?) RETURNING id
                        """,
                        (user_id, source_url, media_type, quality),
                    ).fetchone()[0]
                )
            db.execute(
                """
                INSERT INTO downloads (user_id, source_url, media_type, quality)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, source_url, media_type, quality),
            )
            return int(db.execute("SELECT last_insert_rowid()").fetchone()[0])

    async def finish_download(
        self,
        download_id: int,
        *,
        status: str,
        telegram_file_id: str | None = None,
        title: str = "",
        error_message: str = "",
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE downloads
                SET status = ?, telegram_file_id = ?, title = ?,
                    error_message = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, telegram_file_id, title, error_message[:2_000], download_id),
            )

    async def recent_downloads(
        self,
        user_id: int,
        limit: int = 20,
    ) -> list[DownloadRecord]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, source_url, media_type, quality, title, status,
                       telegram_file_id, created_at
                FROM downloads
                WHERE user_id = ?
                ORDER BY id DESC LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [self._download_record(row) for row in rows]

    async def get_download(
        self,
        user_id: int,
        download_id: int,
    ) -> DownloadRecord | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT id, source_url, media_type, quality, title, status,
                       telegram_file_id, created_at
                FROM downloads
                WHERE user_id = ? AND id = ?
                """,
                (user_id, download_id),
            ).fetchone()
            return self._download_record(row) if row else None

    @staticmethod
    def _download_record(row) -> DownloadRecord:
        return DownloadRecord(
            id=int(row[0]),
            source_url=str(row[1]) if row[1] else None,
            media_type=str(row[2]),
            quality=str(row[3]),
            title=str(row[4]),
            status=str(row[5]),
            telegram_file_id=str(row[6]) if row[6] else None,
            created_at=str(row[7]),
        )

    async def create_public_file(
        self,
        user_id: int,
        *,
        path: str,
        filename: str,
        mime_type: str,
        ttl_seconds: int,
    ) -> str:
        import secrets

        token = secrets.token_urlsafe(24)
        expires_at = int(time.time()) + ttl_seconds
        await self.ensure_user(user_id)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO public_files
                    (token, user_id, path, filename, mime_type, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (token, user_id, path, filename, mime_type, expires_at),
            )
        return token

    async def get_public_file(self, token: str) -> tuple[str, str, str] | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT path, filename, mime_type FROM public_files
                WHERE token = ? AND expires_at > ?
                """,
                (token, int(time.time())),
            ).fetchone()
            return (str(row[0]), str(row[1]), str(row[2])) if row else None

    async def log_error(
        self,
        context: str,
        message: str,
        user_id: int | None = None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO error_logs (user_id, context, message) VALUES (?, ?, ?)",
                (user_id, context[:100], message[-2_000:]),
            )

    async def ai_subscription_until(self, user_id: int) -> int | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT expires_at FROM ai_subscriptions
                WHERE user_id = ? AND status = 'active' AND expires_at > ?
                """,
                (user_id, int(time.time())),
            ).fetchone()
            return int(row[0]) if row else None

    async def activate_ai_subscription(
        self,
        user_id: int,
        *,
        days: int,
        admin_id: int,
        note: str = "",
    ) -> int:
        if days <= 0:
            raise ValueError("Kun musbat bo'lishi kerak")
        await self.ensure_user(user_id)
        now = int(time.time())
        current = await self.ai_subscription_until(user_id)
        expires_at = max(current or 0, now) + days * 24 * 60 * 60
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO ai_subscriptions
                    (user_id, status, expires_at, note, created_by)
                VALUES (?, 'active', ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    status = 'active',
                    expires_at = excluded.expires_at,
                    note = excluded.note,
                    created_by = excluded.created_by,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, expires_at, note[:500], admin_id),
            )
        return expires_at

    async def admin_search_users(
        self,
        query: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        value = query.strip()
        if not value:
            return await self.admin_users(limit)
        like = f"%{value.lower()}%"
        numeric_id = int(value) if value.isdigit() else -1
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT u.user_id, u.username, u.full_name, u.language, u.created_at,
                       p.first_name, p.last_name, p.phone, a.expires_at
                FROM users u
                LEFT JOIN profiles p ON p.user_id = u.user_id
                LEFT JOIN ai_subscriptions a
                    ON a.user_id = u.user_id
                    AND a.status = 'active'
                    AND a.expires_at > ?
                WHERE u.user_id = ?
                   OR LOWER(COALESCE(u.username, '')) LIKE ?
                   OR LOWER(COALESCE(u.full_name, '')) LIKE ?
                   OR LOWER(COALESCE(p.first_name, '') || ' ' ||
                            COALESCE(p.last_name, '')) LIKE ?
                   OR COALESCE(p.phone, '') LIKE ?
                ORDER BY u.created_at DESC LIMIT ?
                """,
                (int(time.time()), numeric_id, like, like, like, f"%{value}%", limit),
            ).fetchall()
            return [self._admin_user(row) for row in rows]

    async def admin_stats(self) -> dict[str, int]:
        now = int(time.time())
        with self._connect() as db:
            queries = {
                "users": "SELECT COUNT(*) FROM users",
                "downloads": "SELECT COUNT(*) FROM downloads",
                "errors": "SELECT COUNT(*) FROM error_logs",
                "ai_subscriptions": (
                    "SELECT COUNT(*) FROM ai_subscriptions "
                    f"WHERE status = 'active' AND expires_at > {now}"
                ),
            }
            return {
                key: int(db.execute(query).fetchone()[0])
                for key, query in queries.items()
            }

    async def admin_users(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT u.user_id, u.username, u.full_name, u.language, u.created_at,
                       p.first_name, p.last_name, p.phone, a.expires_at
                FROM users u
                LEFT JOIN profiles p ON p.user_id = u.user_id
                LEFT JOIN ai_subscriptions a
                    ON a.user_id = u.user_id
                    AND a.status = 'active'
                    AND a.expires_at > ?
                ORDER BY u.created_at DESC LIMIT ?
                """,
                (int(time.time()), limit),
            ).fetchall()
            return [self._admin_user(row) for row in rows]

    @staticmethod
    def _admin_user(row) -> dict[str, Any]:
        return {
            "user_id": int(row[0]),
            "username": str(row[1] or ""),
            "full_name": str(row[2] or ""),
            "language": str(row[3] or "uz"),
            "created_at": str(row[4]),
            "first_name": str(row[5] or ""),
            "last_name": str(row[6] or ""),
            "phone": str(row[7] or ""),
            "ai_subscription_until": int(row[8]) if row[8] else None,
        }

    async def admin_errors(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT user_id, context, message, created_at
                FROM error_logs ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "user_id": int(row[0]) if row[0] else None,
                    "context": str(row[1]),
                    "message": str(row[2]),
                    "created_at": str(row[3]),
                }
                for row in rows
            ]
