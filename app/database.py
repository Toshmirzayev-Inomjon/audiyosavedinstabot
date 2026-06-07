from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

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
"""


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


class Database:
    def __init__(self, path: Path, initial_balance: int = 0) -> None:
        self.path = path
        self.initial_balance = initial_balance

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

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
                "SELECT balance FROM users WHERE user_id = ?",
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
            next_id = db.execute(
                "SELECT COALESCE(MAX(id), 0) + 1 FROM user_accounts"
            ).fetchone()[0]
            account_number = f"VIRT-{user_id}-{int(next_id):06d}"
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
            exists = db.execute(
                "SELECT 1 FROM star_payments WHERE external_id = ?",
                (external_id,),
            ).fetchone()
            if exists:
                return False
            db.execute(
                """
                INSERT INTO star_payments
                    (user_id, stars, credits, status, external_id)
                VALUES (?, ?, ?, 'pending', ?)
                """,
                (user_id, stars, credits, external_id),
            )
            return True

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
                """,
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
