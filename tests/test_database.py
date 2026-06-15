import time
from pathlib import Path

import pytest

from app.database import Database


@pytest.mark.asyncio
async def test_profile_survives_reinitialize(tmp_path: Path) -> None:
    path = tmp_path / "persistent.sqlite3"
    database = Database(path)
    await database.initialize()
    await database.ensure_user(10, "user", "Test User")
    await database.upsert_profile(
        10,
        first_name="Test",
        last_name="User",
        phone="+998901234567",
        avatar_data="data:image/png;base64,abc",
    )
    await database.set_profile_password_hash(10, "hashed-password")

    reopened = Database(path)
    await reopened.initialize()
    await reopened.ensure_user(10, "updated", "Updated Name")

    profile = await reopened.get_profile(10)
    assert profile is not None
    assert profile.first_name == "Test"
    assert profile.last_name == "User"
    assert profile.phone == "+998901234567"
    assert profile.avatar_data == "data:image/png;base64,abc"
    assert profile.password_set is True


@pytest.mark.asyncio
async def test_phone_verification_code(tmp_path: Path) -> None:
    database = Database(tmp_path / "phone.sqlite3")
    await database.initialize()
    await database.ensure_user(10, "user", "Test User")
    await database.store_phone_code(
        10,
        phone="+998901234567",
        code_hash="correct",
        expires_at=int(time.time()) + 60,
    )

    ok, message = await database.verify_phone_code(10, "wrong")
    assert ok is False
    assert message == "Kod noto'g'ri"

    ok, message = await database.verify_phone_code(10, "correct")
    assert ok is True
    assert message == "Telefon tasdiqlandi"
    profile = await database.get_profile(10)
    assert profile is not None
    assert profile.phone_verified is True


@pytest.mark.asyncio
async def test_ai_subscription_and_admin_search(tmp_path: Path) -> None:
    path = tmp_path / "subscriptions.sqlite3"
    database = Database(path)
    await database.initialize()
    await database.ensure_user(10, "musicfan", "Music Fan")
    await database.upsert_profile(
        10,
        first_name="Music",
        last_name="Fan",
        phone="+998901112233",
    )
    expires_at = await database.activate_ai_subscription(
        10,
        days=30,
        admin_id=1,
        note="manual activation",
    )

    assert await database.ai_subscription_until(10) == expires_at
    users = await database.admin_search_users("musicfan")
    assert users[0]["user_id"] == 10
    assert users[0]["ai_subscription_until"] == expires_at
    users_by_phone = await database.admin_search_users("998901112233")
    assert users_by_phone[0]["user_id"] == 10


@pytest.mark.asyncio
async def test_download_history_and_public_file(tmp_path: Path) -> None:
    database = Database(tmp_path / "downloads.sqlite3")
    await database.initialize()
    await database.ensure_user(20, "listener", "Listener")
    download_id = await database.create_download(
        20,
        source_url="artist song",
        media_type="audio",
        quality="mp3",
    )
    await database.finish_download(
        download_id,
        status="completed",
        telegram_file_id="file-id",
        title="Test song",
    )

    history = await database.recent_downloads(20)
    assert history[0].telegram_file_id == "file-id"
    assert history[0].title == "Test song"
    assert (await database.get_download(20, download_id)).id == download_id

    token = await database.create_public_file(
        20,
        path="/tmp/test.mp3",
        filename="test.mp3",
        mime_type="audio/mpeg",
        ttl_seconds=60,
    )
    assert await database.get_public_file(token) == (
        "/tmp/test.mp3",
        "test.mp3",
        "audio/mpeg",
    )


@pytest.mark.asyncio
async def test_language_and_admin_stats(tmp_path: Path) -> None:
    database = Database(tmp_path / "stats.sqlite3")
    await database.initialize()
    await database.ensure_user(10, "user", "User")
    await database.set_language(10, "ru")
    await database.log_error("download", "failed", 10)

    assert await database.get_language(10) == "ru"
    stats = await database.admin_stats()
    assert stats["users"] == 1
    assert stats["errors"] == 1
    assert (await database.admin_users())[0]["user_id"] == 10
    assert (await database.admin_errors())[0]["context"] == "download"
