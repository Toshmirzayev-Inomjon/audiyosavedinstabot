from pathlib import Path

from app.config import Settings
from app.handlers import custom_credits, parse_payment_payload


def settings(tmp_path: Path) -> Settings:
    return Settings(
        bot_token="123:TEST",
        admin_ids=frozenset(),
        database_path=tmp_path / "bot.sqlite3",
        temp_dir=tmp_path,
        circle_price=5000,
        initial_balance=0,
        max_download_mb=49,
        max_duration_minutes=660,
        cookies_file=None,
        telegram_api_id=None,
        telegram_api_hash=None,
        telegram_session_path=tmp_path / "telegram_bot",
        star_packages=((5, 5000), (25, 25000), (50, 55000)),
        custom_star_min=5,
        star_credit_rate=1000,
        bot_api_base=None,
        bot_api_local=False,
        webapp_public_url=None,
        webapp_host="127.0.0.1",
        webapp_port=8080,
        phone_code_ttl_seconds=300,
    )


def test_package_payment_payload(tmp_path: Path) -> None:
    app_settings = settings(tmp_path)

    assert parse_payment_payload(
        "stars:25:25000",
        currency="XTR",
        total_amount=25,
        settings=app_settings,
    ) == (True, 25, 25000)


def test_custom_payment_payload(tmp_path: Path) -> None:
    app_settings = settings(tmp_path)

    assert custom_credits(7, app_settings) == 7000
    assert parse_payment_payload(
        "stars_custom:7:7000",
        currency="XTR",
        total_amount=7,
        settings=app_settings,
    ) == (True, 7, 7000)


def test_rejects_small_or_tampered_custom_payment(tmp_path: Path) -> None:
    app_settings = settings(tmp_path)

    assert parse_payment_payload(
        "stars_custom:4:4000",
        currency="XTR",
        total_amount=4,
        settings=app_settings,
    )[0] is False
    assert parse_payment_payload(
        "stars_custom:7:999999",
        currency="XTR",
        total_amount=7,
        settings=app_settings,
    )[0] is False
