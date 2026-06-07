from __future__ import annotations

import secrets
import sqlite3
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT NOT NULL DEFAULT '',
    balance INTEGER NOT NULL DEFAULT 0 CHECK (balance >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    amount INTEGER NOT NULL,
    kind TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    external_id TEXT UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_transactions_user_id
ON transactions(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS profiles (
    user_id INTEGER PRIMARY KEY,
    first_name TEXT NOT NULL DEFAULT '',
    last_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    phone_verified INTEGER NOT NULL DEFAULT 0 CHECK (phone_verified IN (0, 1)),
    password_hash TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS user_accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    account_number TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    removed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_user_accounts_user_id
ON user_accounts(user_id, status);

CREATE TABLE IF NOT EXISTS phone_verification_codes (
    user_id INTEGER PRIMARY KEY,
    phone TEXT NOT NULL,
    code_hash TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS star_payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    credits INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    external_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    confirmed_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_star_payments_user_id
ON star_payments(user_id, created_at DESC);

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

CREATE TABLE IF NOT EXISTS daily_usage (
    user_id INTEGER NOT NULL,
    usage_date TEXT NOT NULL,
    count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, usage_date),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS subscriptions (
    user_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'active',
    expires_at INTEGER NOT NULL,
    charge_id TEXT UNIQUE,
    stars INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS subscription_payments (
    charge_id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    stars INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS tariff_memberships (
    user_id INTEGER PRIMARY KEY,
    plan_code TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    free_claimed INTEGER NOT NULL DEFAULT 0 CHECK (free_claimed IN (0, 1)),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS tariff_purchases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plan_code TEXT NOT NULL,
    price INTEGER NOT NULL,
    expires_at INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_tariff_purchases_user_id
ON tariff_purchases(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS referrals (
    invitee_id INTEGER PRIMARY KEY,
    inviter_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (invitee_id) REFERENCES users(user_id),
    FOREIGN KEY (inviter_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS promo_codes (
    code TEXT PRIMARY KEY,
    credits INTEGER NOT NULL,
    max_uses INTEGER NOT NULL,
    uses INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS promo_redemptions (
    code TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (code, user_id),
    FOREIGN KEY (code) REFERENCES promo_codes(code),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

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
"""

POSTGRES_SCHEMA = (
    SCHEMA.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGSERIAL PRIMARY KEY")
    .replace("user_id INTEGER", "user_id BIGINT")
    .replace("invitee_id INTEGER", "invitee_id BIGINT")
    .replace("inviter_id INTEGER", "inviter_id BIGINT")
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

    def rollback(self) -> None:
        self.raw.rollback()


@dataclass(frozen=True, slots=True)
class ChargeResult:
    success: bool
    balance: int


@dataclass(frozen=True, slots=True)
class Profile:
    user_id: int
    first_name: str
    last_name: str
    phone: str
    phone_verified: bool
    password_set: bool


@dataclass(frozen=True, slots=True)
class UserAccount:
    id: int
    title: str
    account_number: str
    status: str
    created_at: str


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


@dataclass(frozen=True, slots=True)
class TariffMembership:
    plan_code: str
    expires_at: int
    source: str = "balance"


@dataclass(frozen=True, slots=True)
class TariffPurchaseResult:
    success: bool
    reason: str
    balance: int
    expires_at: int | None = None


class Database:
    def __init__(self, location: Path | str, initial_balance: int = 0) -> None:
        raw_location = str(location)
        self.postgres = raw_location.startswith(("postgres://", "postgresql://"))
        self.database_url = (
            raw_location.replace("postgres://", "postgresql://", 1)
            if self.postgres
            else None
        )
        self.path = None if self.postgres else Path(location)
        self.initial_balance = initial_balance

    def _connect(self) -> _Connection:
        if self.postgres:
            try:
                import psycopg
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL uchun psycopg o'rnatilmagan"
                ) from exc
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
                    "ALTER TABLE users ADD COLUMN IF NOT EXISTS language TEXT "
                    "NOT NULL DEFAULT 'uz'"
                )
            else:
                try:
                    db.execute(
                        "ALTER TABLE users ADD COLUMN language TEXT "
                        "NOT NULL DEFAULT 'uz'"
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
                INSERT INTO users (user_id, username, full_name, balance)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    username = excluded.username,
                    full_name = excluded.full_name,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, username, full_name, self.initial_balance),
            )

    async def get_balance(self, user_id: int) -> int:
        with self._connect() as db:
            cursor = db.execute(
                "SELECT balance FROM users WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            return int(row[0]) if row else 0

    async def charge(
        self,
        user_id: int,
        amount: int,
        description: str,
    ) -> ChargeResult:
        if amount < 0:
            raise ValueError("Charge amount cannot be negative")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            cursor = db.execute(
                "SELECT balance FROM users WHERE user_id = ?"
                + (" FOR UPDATE" if self.postgres else ""),
                (user_id,),
            )
            row = cursor.fetchone()
            balance = int(row[0]) if row else 0
            if balance < amount:
                db.rollback()
                return ChargeResult(False, balance)

            new_balance = balance - amount
            db.execute(
                """
                UPDATE users
                SET balance = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (new_balance, user_id),
            )
            db.execute(
                """
                INSERT INTO transactions (user_id, amount, kind, description)
                VALUES (?, ?, 'charge', ?)
                """,
                (user_id, -amount, description),
            )
            return ChargeResult(True, new_balance)

    async def add_balance(
        self,
        user_id: int,
        amount: int,
        description: str,
        *,
        kind: str = "credit",
        external_id: str | None = None,
    ) -> tuple[bool, int]:
        if amount <= 0:
            raise ValueError("Credit amount must be positive")
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """
                INSERT OR IGNORE INTO users (user_id, balance)
                VALUES (?, 0)
                """,
                (user_id,),
            )
            if external_id:
                cursor = db.execute(
                    "SELECT 1 FROM transactions WHERE external_id = ?",
                    (external_id,),
                )
                if cursor.fetchone():
                    cursor = db.execute(
                        "SELECT balance FROM users WHERE user_id = ?",
                        (user_id,),
                    )
                    row = cursor.fetchone()
                    db.rollback()
                    return False, int(row[0])

            db.execute(
                """
                UPDATE users
                SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (amount, user_id),
            )
            db.execute(
                """
                INSERT INTO transactions
                    (user_id, amount, kind, description, external_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (user_id, amount, kind, description, external_id),
            )
            cursor = db.execute(
                "SELECT balance FROM users WHERE user_id = ?",
                (user_id,),
            )
            row = cursor.fetchone()
            return True, int(row[0])

    async def recent_transactions(
        self,
        user_id: int,
        limit: int = 5,
    ) -> list[tuple[int, str, str, str]]:
        with self._connect() as db:
            cursor = db.execute(
                """
                SELECT amount, kind, description, created_at
                FROM transactions
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            rows = cursor.fetchall()
            return [
                (int(row[0]), str(row[1]), str(row[2]), str(row[3]))
                for row in rows
            ]

    async def get_profile(self, user_id: int) -> Profile | None:
        with self._connect() as db:
            cursor = db.execute(
                """
                SELECT user_id, first_name, last_name, phone, phone_verified,
                    password_hash
                FROM profiles
                WHERE user_id = ?
                """,
                (user_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return Profile(
                user_id=int(row[0]),
                first_name=str(row[1]),
                last_name=str(row[2]),
                phone=str(row[3]),
                phone_verified=bool(row[4]),
                password_set=bool(row[5]),
            )

    async def upsert_profile(
        self,
        user_id: int,
        *,
        first_name: str,
        last_name: str,
        phone: str,
    ) -> Profile:
        first_name = first_name.strip()
        last_name = last_name.strip()
        phone = phone.strip()
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                (user_id,),
            )
            existing = db.execute(
                "SELECT phone, phone_verified FROM profiles WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            phone_verified = 0
            if existing and str(existing[0]) == phone and int(existing[1]) == 1:
                phone_verified = 1
            db.execute(
                """
                INSERT INTO profiles
                    (user_id, first_name, last_name, phone, phone_verified)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    phone = excluded.phone,
                    phone_verified = excluded.phone_verified,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, first_name, last_name, phone, phone_verified),
            )
        profile = await self.get_profile(user_id)
        if not profile:
            raise RuntimeError("Profile was not saved")
        return profile

    async def set_profile_password_hash(self, user_id: int, password_hash: str) -> None:
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
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                (user_id,),
            )
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
                FROM phone_verification_codes
                WHERE user_id = ?
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
                    SET attempts = attempts + 1
                    WHERE user_id = ?
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

    async def list_accounts(self, user_id: int) -> list[UserAccount]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT id, title, account_number, status, created_at
                FROM user_accounts
                WHERE user_id = ? AND status = 'active'
                ORDER BY id DESC
                """,
                (user_id,),
            ).fetchall()
            return [
                UserAccount(
                    id=int(row[0]),
                    title=str(row[1]),
                    account_number=str(row[2]),
                    status=str(row[3]),
                    created_at=str(row[4]),
                )
                for row in rows
            ]

    async def create_account(self, user_id: int, title: str) -> UserAccount:
        title = title.strip() or "Asosiy hisob"
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                (user_id,),
            )
            account_number = f"VIRT-{user_id}-{secrets.token_hex(3).upper()}"
            if self.postgres:
                account_id = db.execute(
                    """
                    INSERT INTO user_accounts (user_id, title, account_number)
                    VALUES (?, ?, ?)
                    RETURNING id
                    """,
                    (user_id, title, account_number),
                ).fetchone()[0]
            else:
                db.execute(
                    """
                    INSERT INTO user_accounts (user_id, title, account_number)
                    VALUES (?, ?, ?)
                    """,
                    (user_id, title, account_number),
                )
                account_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            row = db.execute(
                """
                SELECT id, title, account_number, status, created_at
                FROM user_accounts
                WHERE id = ?
                """,
                (account_id,),
            ).fetchone()
            return UserAccount(
                id=int(row[0]),
                title=str(row[1]),
                account_number=str(row[2]),
                status=str(row[3]),
                created_at=str(row[4]),
            )

    async def remove_account(self, user_id: int, account_id: int) -> bool:
        with self._connect() as db:
            cursor = db.execute(
                """
                UPDATE user_accounts
                SET status = 'removed', removed_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND id = ? AND status = 'active'
                """,
                (user_id, account_id),
            )
            return cursor.rowcount > 0

    async def create_pending_star_payment(
        self,
        user_id: int,
        *,
        stars: int,
        credits: int,
        external_id: str,
    ) -> bool:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                (user_id,),
            )
            cursor = db.execute(
                """
                INSERT INTO star_payments
                    (user_id, stars, credits, status, external_id)
                VALUES (?, ?, ?, 'pending', ?)
                ON CONFLICT(external_id) DO NOTHING
                """,
                (user_id, stars, credits, external_id),
            )
            return cursor.rowcount > 0

    async def confirm_star_payment(
        self,
        external_id: str,
        description: str,
    ) -> tuple[bool, int]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """
                SELECT user_id, credits, status
                FROM star_payments
                WHERE external_id = ?
                """
                + (" FOR UPDATE" if self.postgres else ""),
                (external_id,),
            ).fetchone()
            if not row:
                return False, 0
            user_id, credits, status = int(row[0]), int(row[1]), str(row[2])
            balance_row = db.execute(
                "SELECT balance FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            balance = int(balance_row[0]) if balance_row else 0
            if status == "confirmed":
                return False, balance
            db.execute(
                """
                UPDATE users
                SET balance = balance + ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (credits, user_id),
            )
            db.execute(
                """
                UPDATE star_payments
                SET status = 'confirmed', confirmed_at = CURRENT_TIMESTAMP
                WHERE external_id = ?
                """,
                (external_id,),
            )
            db.execute(
                """
                INSERT INTO transactions
                    (user_id, amount, kind, description, external_id)
                VALUES (?, ?, 'payment', ?, ?)
                """,
                (user_id, credits, description, f"star:{external_id}"),
            )
            row = db.execute(
                "SELECT balance FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return True, int(row[0])

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
        with self._connect() as db:
            db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                (user_id,),
            )
            db.execute(
                "UPDATE users SET language = ?, updated_at = CURRENT_TIMESTAMP "
                "WHERE user_id = ?",
                (language, user_id),
            )

    async def is_premium(self, user_id: int) -> bool:
        now = int(time.time())
        with self._connect() as db:
            row = db.execute(
                """
                SELECT expires_at
                FROM subscriptions
                WHERE user_id = ? AND status = 'active'
                """,
                (user_id,),
            ).fetchone()
            if row and int(row[0]) > now:
                return True
            tariff = db.execute(
                """
                SELECT expires_at
                FROM tariff_memberships
                WHERE user_id = ? AND plan_code = 'premium'
                """,
                (user_id,),
            ).fetchone()
            return bool(tariff and int(tariff[0]) > now)

    async def premium_until(self, user_id: int) -> int | None:
        with self._connect() as db:
            subscription = db.execute(
                "SELECT expires_at FROM subscriptions WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            tariff = db.execute(
                """
                SELECT expires_at FROM tariff_memberships
                WHERE user_id = ? AND plan_code = 'premium'
                """,
                (user_id,),
            ).fetchone()
            values = [
                int(row[0])
                for row in (subscription, tariff)
                if row is not None
            ]
            return max(values) if values else None

    async def get_active_tariff(self, user_id: int) -> TariffMembership | None:
        now = int(time.time())
        with self._connect() as db:
            subscription = db.execute(
                """
                SELECT expires_at
                FROM subscriptions
                WHERE user_id = ? AND status = 'active' AND expires_at > ?
                """,
                (user_id, now),
            ).fetchone()
            row = db.execute(
                """
                SELECT plan_code, expires_at
                FROM tariff_memberships
                WHERE user_id = ? AND expires_at > ?
                """,
                (user_id, now),
            ).fetchone()
            if subscription:
                if (
                    row
                    and str(row[0]) == "premium"
                    and int(row[1]) >= int(subscription[0])
                ):
                    return TariffMembership("premium", int(row[1]))
                return TariffMembership(
                    "premium",
                    int(subscription[0]),
                    source="stars",
                )
            if row:
                return TariffMembership(str(row[0]), int(row[1]))
            return None

    async def activate_free_tariff(
        self,
        user_id: int,
        *,
        period_seconds: int,
    ) -> TariffPurchaseResult:
        if period_seconds <= 0:
            raise ValueError("Tarif muddati musbat bo'lishi kerak")
        now = int(time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                (user_id,),
            )
            balance_row = db.execute(
                "SELECT balance FROM users WHERE user_id = ?"
                + (" FOR UPDATE" if self.postgres else ""),
                (user_id,),
            ).fetchone()
            balance = int(balance_row[0]) if balance_row else 0
            row = db.execute(
                "SELECT plan_code, expires_at, free_claimed "
                "FROM tariff_memberships WHERE user_id = ?"
                + (" FOR UPDATE" if self.postgres else ""),
                (user_id,),
            ).fetchone()
            subscription = db.execute(
                """
                SELECT expires_at FROM subscriptions
                WHERE user_id = ? AND status = 'active' AND expires_at > ?
                """,
                (user_id, now),
            ).fetchone()
            if subscription:
                return TariffPurchaseResult(
                    False,
                    "active",
                    balance,
                    int(subscription[0]),
                )
            if row and int(row[1]) > now:
                return TariffPurchaseResult(
                    False,
                    "active",
                    balance,
                    int(row[1]),
                )
            if row and int(row[2]) == 1:
                return TariffPurchaseResult(False, "free_used", balance)
            expires_at = now + period_seconds
            db.execute(
                """
                INSERT INTO tariff_memberships
                    (user_id, plan_code, expires_at, free_claimed)
                VALUES (?, 'free', ?, 1)
                ON CONFLICT(user_id) DO UPDATE SET
                    plan_code = 'free',
                    expires_at = excluded.expires_at,
                    free_claimed = 1,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, expires_at),
            )
            return TariffPurchaseResult(True, "activated", balance, expires_at)

    async def purchase_tariff(
        self,
        user_id: int,
        *,
        plan_code: str,
        price: int,
        period_seconds: int,
    ) -> TariffPurchaseResult:
        if plan_code not in {"standard", "premium"}:
            raise ValueError("Pullik tarif noto'g'ri")
        if price <= 0 or period_seconds <= 0:
            raise ValueError("Tarif narxi va muddati musbat bo'lishi kerak")
        now = int(time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                (user_id,),
            )
            balance_row = db.execute(
                "SELECT balance FROM users WHERE user_id = ?"
                + (" FOR UPDATE" if self.postgres else ""),
                (user_id,),
            ).fetchone()
            balance = int(balance_row[0]) if balance_row else 0
            membership = db.execute(
                "SELECT plan_code, expires_at FROM tariff_memberships "
                "WHERE user_id = ?"
                + (" FOR UPDATE" if self.postgres else ""),
                (user_id,),
            ).fetchone()
            subscription = db.execute(
                """
                SELECT expires_at FROM subscriptions
                WHERE user_id = ? AND status = 'active' AND expires_at > ?
                """,
                (user_id, now),
            ).fetchone()
            if subscription:
                return TariffPurchaseResult(
                    False,
                    "already_active",
                    balance,
                    int(subscription[0]),
                )
            if (
                membership
                and str(membership[0]) == plan_code
                and int(membership[1]) > now
            ):
                return TariffPurchaseResult(
                    False,
                    "already_active",
                    balance,
                    int(membership[1]),
                )
            plan_rank = {"free": 0, "standard": 1, "premium": 2}
            if (
                membership
                and int(membership[1]) > now
                and plan_rank.get(str(membership[0]), 0) > plan_rank[plan_code]
            ):
                return TariffPurchaseResult(
                    False,
                    "higher_active",
                    balance,
                    int(membership[1]),
                )
            if balance < price:
                return TariffPurchaseResult(False, "insufficient", balance)
            current_expiry = int(membership[1]) if membership else 0
            expires_at = max(now, current_expiry) + period_seconds
            new_balance = balance - price
            db.execute(
                """
                UPDATE users
                SET balance = ?, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ?
                """,
                (new_balance, user_id),
            )
            db.execute(
                """
                INSERT INTO transactions (user_id, amount, kind, description)
                VALUES (?, ?, 'tariff', ?)
                """,
                (user_id, -price, f"{plan_code.title()} tarif"),
            )
            db.execute(
                """
                INSERT INTO tariff_memberships
                    (user_id, plan_code, expires_at, free_claimed)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(user_id) DO UPDATE SET
                    plan_code = excluded.plan_code,
                    expires_at = excluded.expires_at,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, plan_code, expires_at),
            )
            db.execute(
                """
                INSERT INTO tariff_purchases
                    (user_id, plan_code, price, expires_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, plan_code, price, expires_at),
            )
            return TariffPurchaseResult(
                True,
                "purchased",
                new_balance,
                expires_at,
            )

    async def tariff_daily_limit(
        self,
        user_id: int,
        *,
        free_limit: int,
        standard_limit: int,
    ) -> int:
        tariff = await self.get_active_tariff(user_id)
        if not tariff:
            return 0
        if tariff.plan_code == "premium":
            return -1
        if tariff.plan_code == "standard":
            return standard_limit
        return free_limit

    async def activate_premium(
        self,
        user_id: int,
        *,
        stars: int,
        charge_id: str,
        period_seconds: int = 30 * 24 * 60 * 60,
    ) -> int:
        now = int(time.time())
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                (user_id,),
            )
            duplicate = db.execute(
                "SELECT 1 FROM subscription_payments WHERE charge_id = ?",
                (charge_id,),
            ).fetchone()
            existing = db.execute(
                "SELECT expires_at FROM subscriptions WHERE user_id = ?"
                + (" FOR UPDATE" if self.postgres else ""),
                (user_id,),
            ).fetchone()
            if duplicate and existing:
                return int(existing[0])
            base = max(now, int(existing[0])) if existing else now
            expires_at = base + period_seconds
            db.execute(
                """
                INSERT INTO subscription_payments (charge_id, user_id, stars)
                VALUES (?, ?, ?)
                ON CONFLICT(charge_id) DO NOTHING
                """,
                (charge_id, user_id, stars),
            )
            db.execute(
                """
                INSERT INTO subscriptions
                    (user_id, status, expires_at, charge_id, stars)
                VALUES (?, 'active', ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    status = 'active',
                    expires_at = excluded.expires_at,
                    charge_id = excluded.charge_id,
                    stars = excluded.stars,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (user_id, expires_at, charge_id, stars),
            )
            return expires_at

    async def reserve_daily_use(self, user_id: int, limit: int) -> tuple[bool, int]:
        if await self.is_premium(user_id):
            return True, -1
        usage_date = datetime.now(UTC).date().isoformat()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if self.postgres:
                row = db.execute(
                    """
                    INSERT INTO daily_usage (user_id, usage_date, count)
                    VALUES (?, ?, 1)
                    ON CONFLICT(user_id, usage_date) DO UPDATE SET
                        count = daily_usage.count + 1
                    WHERE daily_usage.count < ?
                    RETURNING count
                    """,
                    (user_id, usage_date, limit),
                ).fetchone()
                if not row:
                    return False, 0
                used = int(row[0])
                return True, max(0, limit - used)
            row = db.execute(
                "SELECT count FROM daily_usage WHERE user_id = ? AND usage_date = ?",
                (user_id, usage_date),
            ).fetchone()
            used = int(row[0]) if row else 0
            if used >= limit:
                return False, 0
            db.execute(
                """
                INSERT INTO daily_usage (user_id, usage_date, count)
                VALUES (?, ?, 1)
                ON CONFLICT(user_id, usage_date) DO UPDATE SET
                    count = daily_usage.count + 1
                """,
                (user_id, usage_date),
            )
            return True, max(0, limit - used - 1)

    async def release_daily_use(self, user_id: int) -> None:
        usage_date = datetime.now(UTC).date().isoformat()
        with self._connect() as db:
            db.execute(
                """
                UPDATE daily_usage
                SET count = CASE WHEN count > 0 THEN count - 1 ELSE 0 END
                WHERE user_id = ? AND usage_date = ?
                """,
                (user_id, usage_date),
            )

    async def create_download(
        self,
        user_id: int,
        *,
        source_url: str | None,
        media_type: str,
        quality: str = "",
        title: str = "",
        status: str = "queued",
    ) -> int:
        with self._connect() as db:
            if self.postgres:
                row = db.execute(
                    """
                    INSERT INTO downloads
                        (user_id, source_url, media_type, quality, title, status)
                    VALUES (?, ?, ?, ?, ?, ?)
                    RETURNING id
                    """,
                    (user_id, source_url, media_type, quality, title, status),
                ).fetchone()
                return int(row[0])
            cursor = db.execute(
                """
                INSERT INTO downloads
                    (user_id, source_url, media_type, quality, title, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, source_url, media_type, quality, title, status),
            )
            return int(cursor.lastrowid)

    async def finish_download(
        self,
        download_id: int,
        *,
        status: str,
        telegram_file_id: str | None = None,
        title: str = "",
        error_message: str | None = None,
    ) -> None:
        with self._connect() as db:
            db.execute(
                """
                UPDATE downloads
                SET status = ?, telegram_file_id = ?, title = ?,
                    error_message = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, telegram_file_id, title, error_message, download_id),
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
                ORDER BY id DESC
                LIMIT ?
                """,
                (user_id, limit),
            ).fetchall()
            return [
                DownloadRecord(
                    id=int(row[0]),
                    source_url=str(row[1]) if row[1] else None,
                    media_type=str(row[2]),
                    quality=str(row[3]),
                    title=str(row[4]),
                    status=str(row[5]),
                    telegram_file_id=str(row[6]) if row[6] else None,
                    created_at=str(row[7]),
                )
                for row in rows
            ]

    async def get_download(self, user_id: int, download_id: int) -> DownloadRecord | None:
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
            if not row:
                return None
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

    async def apply_referral(
        self,
        invitee_id: int,
        inviter_id: int,
        *,
        inviter_reward: int,
        invitee_reward: int,
    ) -> bool:
        if invitee_id == inviter_id:
            return False
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                (invitee_id,),
            )
            db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                (inviter_id,),
            )
            inserted = db.execute(
                "INSERT OR IGNORE INTO referrals (invitee_id, inviter_id) "
                "VALUES (?, ?)",
                (invitee_id, inviter_id),
            )
            if inserted.rowcount == 0:
                return False
            for user_id, amount, description in (
                (inviter_id, inviter_reward, "Referral bonusi"),
                (invitee_id, invitee_reward, "Yangi foydalanuvchi bonusi"),
            ):
                if amount <= 0:
                    continue
                db.execute(
                    "UPDATE users SET balance = balance + ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                    (amount, user_id),
                )
                db.execute(
                    """
                    INSERT INTO transactions (user_id, amount, kind, description)
                    VALUES (?, ?, 'referral', ?)
                    """,
                    (user_id, amount, description),
                )
            return True

    async def referral_stats(self, user_id: int) -> tuple[int, int]:
        with self._connect() as db:
            row = db.execute(
                "SELECT COUNT(*) FROM referrals WHERE inviter_id = ?",
                (user_id,),
            ).fetchone()
            count = int(row[0]) if row else 0
            earned = db.execute(
                """
                SELECT COALESCE(SUM(amount), 0)
                FROM transactions
                WHERE user_id = ? AND kind = 'referral'
                """,
                (user_id,),
            ).fetchone()
            return count, int(earned[0]) if earned else 0

    async def create_promo(self, code: str, credits: int, max_uses: int) -> None:
        normalized = code.strip().upper()
        if not normalized or credits <= 0 or max_uses <= 0:
            raise ValueError("Promo qiymatlari noto'g'ri")
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO promo_codes (code, credits, max_uses, uses, active)
                VALUES (?, ?, ?, 0, 1)
                ON CONFLICT(code) DO UPDATE SET
                    credits = excluded.credits,
                    max_uses = excluded.max_uses,
                    active = 1
                """,
                (normalized, credits, max_uses),
            )

    async def redeem_promo(self, user_id: int, code: str) -> tuple[bool, str, int]:
        normalized = code.strip().upper()
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            promo = db.execute(
                """
                SELECT credits, max_uses, uses, active
                FROM promo_codes WHERE code = ?
                """
                + (" FOR UPDATE" if self.postgres else ""),
                (normalized,),
            ).fetchone()
            if not promo or not bool(promo[3]):
                return False, "Promo kod topilmadi", 0
            if int(promo[2]) >= int(promo[1]):
                return False, "Promo kod limiti tugagan", 0
            if db.execute(
                "SELECT 1 FROM promo_redemptions WHERE code = ? AND user_id = ?",
                (normalized, user_id),
            ).fetchone():
                return False, "Bu promo kodni oldin ishlatgansiz", 0
            credits = int(promo[0])
            db.execute(
                "INSERT OR IGNORE INTO users (user_id, balance) VALUES (?, 0)",
                (user_id,),
            )
            db.execute(
                "INSERT INTO promo_redemptions (code, user_id) VALUES (?, ?)",
                (normalized, user_id),
            )
            db.execute(
                "UPDATE promo_codes SET uses = uses + 1 WHERE code = ?",
                (normalized,),
            )
            db.execute(
                "UPDATE users SET balance = balance + ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE user_id = ?",
                (credits, user_id),
            )
            db.execute(
                """
                INSERT INTO transactions (user_id, amount, kind, description)
                VALUES (?, ?, 'promo', ?)
                """,
                (user_id, credits, f"Promo kod: {normalized}"),
            )
            balance = db.execute(
                "SELECT balance FROM users WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            return True, "Promo kod qabul qilindi", int(balance[0])

    async def create_public_file(
        self,
        user_id: int,
        *,
        path: str,
        filename: str,
        mime_type: str,
        ttl_seconds: int,
    ) -> str:
        token = secrets.token_urlsafe(24)
        with self._connect() as db:
            db.execute(
                """
                INSERT INTO public_files
                    (token, user_id, path, filename, mime_type, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    token,
                    user_id,
                    path,
                    filename,
                    mime_type,
                    int(time.time()) + ttl_seconds,
                ),
            )
        return token

    async def get_public_file(self, token: str) -> tuple[str, str, str] | None:
        with self._connect() as db:
            row = db.execute(
                """
                SELECT path, filename, mime_type
                FROM public_files
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

    async def admin_stats(self) -> dict[str, int]:
        now = int(time.time())
        today = date.today().isoformat()
        with self._connect() as db:
            queries = {
                "users": "SELECT COUNT(*) FROM users",
                "downloads": "SELECT COUNT(*) FROM downloads",
                "payments": (
                    "SELECT COUNT(*) FROM star_payments WHERE status = 'confirmed'"
                ),
                "errors": "SELECT COUNT(*) FROM error_logs",
                "premium": (
                    "SELECT COUNT(*) FROM ("
                    "SELECT user_id FROM subscriptions "
                    f"WHERE status = 'active' AND expires_at > {now} "
                    "UNION "
                    "SELECT user_id FROM tariff_memberships "
                    f"WHERE plan_code = 'premium' AND expires_at > {now}"
                    ") AS active_premium"
                ),
                "today_downloads": (
                    "SELECT COALESCE(SUM(count), 0) FROM daily_usage "
                    f"WHERE usage_date = '{today}'"
                ),
            }
            result: dict[str, int] = {}
            for key, query in queries.items():
                row = db.execute(query).fetchone()
                result[key] = int(row[0]) if row else 0
            return result

    async def admin_users(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT user_id, username, full_name, balance, language, created_at
                FROM users ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "user_id": int(row[0]),
                    "username": str(row[1] or ""),
                    "full_name": str(row[2] or ""),
                    "balance": int(row[3]),
                    "language": str(row[4]),
                    "created_at": str(row[5]),
                }
                for row in rows
            ]

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

    async def admin_payments(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                """
                SELECT user_id, stars, credits, status, external_id, created_at
                FROM star_payments ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    "user_id": int(row[0]),
                    "stars": int(row[1]),
                    "credits": int(row[2]),
                    "status": str(row[3]),
                    "external_id": str(row[4]),
                    "created_at": str(row[5]),
                }
                for row in rows
            ]
