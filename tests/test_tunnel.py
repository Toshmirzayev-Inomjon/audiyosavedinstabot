import asyncio

import pytest

from app.tunnel import _wait_for_url


class FakeProcess:
    def __init__(self, lines: list[bytes]) -> None:
        self.stdout = asyncio.StreamReader()
        for line in lines:
            self.stdout.feed_data(line)
        self.stdout.feed_eof()
        self.returncode = None


@pytest.mark.asyncio
async def test_wait_for_quick_tunnel_url() -> None:
    process = FakeProcess(
        [
            b"2026-06-07 INF Requesting new quick Tunnel\n",
            b"2026-06-07 INF https://sample-name.trycloudflare.com\n",
        ]
    )

    assert await _wait_for_url(process) == "https://sample-name.trycloudflare.com"
