import asyncio

import pytest

from app.main import run_polling_forever


class FakeBot:
    async def set_my_commands(self, *_args, **_kwargs) -> None:
        return None

    async def set_my_short_description(self, *_args, **_kwargs) -> None:
        return None

    async def set_my_description(self, *_args, **_kwargs) -> None:
        return None

    async def set_chat_menu_button(self, *_args, **_kwargs) -> None:
        return None

    async def delete_webhook(self, *_args, **_kwargs) -> None:
        raise RuntimeError("temporary telegram error")


class FakeDispatcher:
    async def start_polling(self, *_args, **_kwargs) -> None:
        return None


@pytest.mark.asyncio
async def test_polling_loop_retries_instead_of_exiting(monkeypatch) -> None:
    sleeps: list[int] = []

    async def fake_sleep(seconds: int) -> None:
        sleeps.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await run_polling_forever(
            bot=FakeBot(),
            dispatcher=FakeDispatcher(),
            webapp_public_url=None,
        )

    assert sleeps == [30]
