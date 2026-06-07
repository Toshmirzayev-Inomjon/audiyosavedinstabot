from pathlib import Path

import pytest

from app.database import Database


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

