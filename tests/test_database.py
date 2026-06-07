from pathlib import Path

import pytest

from app.database import Database


@pytest.mark.asyncio
async def test_balance_and_profile_survive_reinitialize(tmp_path: Path) -> None:
    path = tmp_path / "persistent.sqlite3"
    database = Database(path, initial_balance=1_000)
    await database.initialize()
    await database.ensure_user(10, "user", "Test User")
    await database.add_balance(10, 2_000, "credit")
    await database.upsert_profile(
        10,
        first_name="Test",
        last_name="User",
        phone="+998901234567",
    )

    reopened = Database(path, initial_balance=9_999)
    await reopened.initialize()
    await reopened.ensure_user(10, "updated", "Updated Name")

    assert await reopened.get_balance(10) == 3_000
    profile = await reopened.get_profile(10)
    assert profile is not None
    assert profile.first_name == "Test"
    assert profile.last_name == "User"
    assert profile.phone == "+998901234567"


@pytest.mark.asyncio
async def test_balance_charge_refund_and_idempotent_credit(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.sqlite3", initial_balance=1_000)
    await database.initialize()
    await database.ensure_user(10, "user", "Test User")

    assert await database.get_balance(10) == 1_000

    result = await database.charge(10, 400, "circle")
    assert result.success is True
    assert result.balance == 600

    insufficient = await database.charge(10, 700, "circle")
    assert insufficient.success is False
    assert insufficient.balance == 600

    added, balance = await database.add_balance(
        10,
        400,
        "refund",
        kind="refund",
        external_id="payment-1",
    )
    assert added is True
    assert balance == 1_000

    added_again, balance_again = await database.add_balance(
        10,
        400,
        "duplicate",
        external_id="payment-1",
    )
    assert added_again is False
    assert balance_again == 1_000


@pytest.mark.asyncio
async def test_admin_credit_creates_missing_user(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    await database.initialize()

    added, balance = await database.add_balance(99, 5_000, "admin")

    assert added is True
    assert balance == 5_000
    assert await database.get_balance(99) == 5_000


@pytest.mark.asyncio
async def test_pending_star_payment_confirm_adds_balance_once(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    await database.initialize()
    await database.ensure_user(10, "user", "Test User")

    created = await database.create_pending_star_payment(
        10,
        stars=5,
        credits=5_000,
        external_id="stars-payment-1",
    )
    assert created is True
    duplicate = await database.create_pending_star_payment(
        10,
        stars=5,
        credits=5_000,
        external_id="stars-payment-1",
    )
    assert duplicate is False

    confirmed, balance = await database.confirm_star_payment(
        "stars-payment-1",
        "Stars payment",
    )
    assert confirmed is True
    assert balance == 5_000

    confirmed_again, balance_again = await database.confirm_star_payment(
        "stars-payment-1",
        "Stars payment",
    )
    assert confirmed_again is False
    assert balance_again == 5_000


@pytest.mark.asyncio
async def test_free_and_paid_tariffs_are_persistent_and_idempotent(
    tmp_path: Path,
) -> None:
    database = Database(tmp_path / "test.sqlite3", initial_balance=75_000)
    await database.initialize()
    await database.ensure_user(10, "user", "Test User")

    free = await database.activate_free_tariff(10, period_seconds=2_592_000)
    assert free.success is True
    assert free.expires_at is not None
    active = await database.get_active_tariff(10)
    assert active is not None
    assert active.plan_code == "free"
    assert await database.tariff_daily_limit(
        10,
        free_limit=3,
        standard_limit=15,
    ) == 3

    second_free = await database.activate_free_tariff(10, period_seconds=2_592_000)
    assert second_free.success is False
    assert second_free.reason == "active"

    standard = await database.purchase_tariff(
        10,
        plan_code="standard",
        price=25_000,
        period_seconds=2_592_000,
    )
    assert standard.success is True
    assert standard.balance == 50_000
    assert await database.tariff_daily_limit(
        10,
        free_limit=3,
        standard_limit=15,
    ) == 15

    duplicate = await database.purchase_tariff(
        10,
        plan_code="standard",
        price=25_000,
        period_seconds=2_592_000,
    )
    assert duplicate.success is False
    assert duplicate.reason == "already_active"
    assert duplicate.balance == 50_000

    premium = await database.purchase_tariff(
        10,
        plan_code="premium",
        price=50_000,
        period_seconds=2_592_000,
    )
    assert premium.success is True
    assert premium.balance == 0
    assert await database.is_premium(10)
    assert await database.tariff_daily_limit(
        10,
        free_limit=3,
        standard_limit=15,
    ) == -1
    downgrade = await database.purchase_tariff(
        10,
        plan_code="standard",
        price=25_000,
        period_seconds=2_592_000,
    )
    assert downgrade.success is False
    assert downgrade.reason == "higher_active"
    assert downgrade.balance == 0

    reopened = Database(tmp_path / "test.sqlite3")
    await reopened.initialize()
    persisted = await reopened.get_active_tariff(10)
    assert persisted is not None
    assert persisted.plan_code == "premium"
    assert await reopened.get_balance(10) == 0


@pytest.mark.asyncio
async def test_referral_promo_premium_limit_and_history(tmp_path: Path) -> None:
    database = Database(tmp_path / "test.sqlite3")
    await database.initialize()
    await database.ensure_user(10, "inviter", "Inviter")
    await database.ensure_user(20, "invitee", "Invitee")

    assert await database.apply_referral(
        20,
        10,
        inviter_reward=5_000,
        invitee_reward=2_000,
    )
    assert not await database.apply_referral(
        20,
        10,
        inviter_reward=5_000,
        invitee_reward=2_000,
    )
    assert await database.get_balance(10) == 5_000
    assert await database.get_balance(20) == 2_000

    await database.create_promo("HELLO", 3_000, 1)
    redeemed, _message, balance = await database.redeem_promo(20, "hello")
    assert redeemed is True
    assert balance == 5_000
    duplicate, _message, _balance = await database.redeem_promo(20, "HELLO")
    assert duplicate is False

    allowed, remaining = await database.reserve_daily_use(20, 1)
    assert allowed is True
    assert remaining == 0
    allowed_again, _ = await database.reserve_daily_use(20, 1)
    assert allowed_again is False
    await database.release_daily_use(20)

    expires_at = await database.activate_premium(
        20,
        stars=100,
        charge_id="premium-1",
        period_seconds=60,
    )
    assert expires_at > 0
    assert await database.is_premium(20)
    duplicate_expiry = await database.activate_premium(
        20,
        stars=100,
        charge_id="premium-1",
        period_seconds=60,
    )
    assert duplicate_expiry == expires_at
    premium_allowed, premium_remaining = await database.reserve_daily_use(20, 1)
    assert premium_allowed is True
    assert premium_remaining == -1

    download_id = await database.create_download(
        20,
        source_url="https://youtu.be/test",
        media_type="video",
        quality="720",
    )
    await database.finish_download(
        download_id,
        status="completed",
        telegram_file_id="file-id",
        title="Test video",
    )
    history = await database.recent_downloads(20)
    assert history[0].telegram_file_id == "file-id"
    assert history[0].title == "Test video"
