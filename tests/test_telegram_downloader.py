import pytest

from app.services.telegram_downloader import (
    TelegramDownloadError,
    is_telegram_url,
    parse_telegram_url,
)


def test_parse_public_telegram_link() -> None:
    assert parse_telegram_url("https://t.me/example_channel/123") == (
        "example_channel",
        123,
    )
    assert is_telegram_url("https://t.me/s/example_channel/123")


def test_parse_private_telegram_link() -> None:
    assert parse_telegram_url("https://t.me/c/1234567890/42") == (
        -1001234567890,
        42,
    )


def test_reject_invalid_telegram_link() -> None:
    with pytest.raises(TelegramDownloadError):
        parse_telegram_url("https://t.me/example_channel")

