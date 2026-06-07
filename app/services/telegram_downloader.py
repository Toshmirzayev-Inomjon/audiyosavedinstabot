from __future__ import annotations

import re
from pathlib import Path


class TelegramDownloadError(RuntimeError):
    pass


PUBLIC_LINK_RE = re.compile(
    r"^https?://(?:www\.)?(?:t\.me|telegram\.me)/(?:s/)?"
    r"(?P<channel>[A-Za-z][A-Za-z0-9_]{3,})/(?P<message_id>\d+)(?:\?.*)?$"
)
PRIVATE_LINK_RE = re.compile(
    r"^https?://(?:www\.)?(?:t\.me|telegram\.me)/c/"
    r"(?P<channel_id>\d+)/(?P<message_id>\d+)(?:\?.*)?$"
)


def is_telegram_url(url: str) -> bool:
    return bool(PUBLIC_LINK_RE.match(url.strip()) or PRIVATE_LINK_RE.match(url.strip()))


def parse_telegram_url(url: str) -> tuple[str | int, int]:
    value = url.strip()
    public_match = PUBLIC_LINK_RE.match(value)
    if public_match:
        return public_match.group("channel"), int(public_match.group("message_id"))
    private_match = PRIVATE_LINK_RE.match(value)
    if private_match:
        channel_id = int(f"-100{private_match.group('channel_id')}")
        return channel_id, int(private_match.group("message_id"))
    raise TelegramDownloadError("Telegram post havolasi noto'g'ri")


class TelegramDownloadService:
    def __init__(
        self,
        *,
        api_id: int | None,
        api_hash: str | None,
        bot_token: str,
        session_path: Path,
        max_bytes: int,
    ) -> None:
        self.api_id = api_id
        self.api_hash = api_hash
        self.bot_token = bot_token
        self.session_path = session_path
        self.max_bytes = max_bytes
        self._client = None

    @property
    def enabled(self) -> bool:
        return bool(self.api_id and self.api_hash)

    async def start(self) -> None:
        if not self.enabled:
            return
        from telethon import TelegramClient

        self._client = TelegramClient(
            str(self.session_path),
            self.api_id,
            self.api_hash,
        )
        await self._client.start(bot_token=self.bot_token)

    async def stop(self) -> None:
        if self._client:
            await self._client.disconnect()

    async def download(self, url: str, directory: Path) -> Path:
        if not self._client:
            raise TelegramDownloadError(
                "Telegram havolalarini yuklash sozlanmagan. "
                "TELEGRAM_API_ID va TELEGRAM_API_HASH ni kiriting."
            )
        entity_ref, message_id = parse_telegram_url(url)
        try:
            entity = await self._client.get_entity(entity_ref)
            message = await self._client.get_messages(entity, ids=message_id)
            if not message or not message.media:
                raise TelegramDownloadError("Postda yuklanadigan media topilmadi")
            directory.mkdir(parents=True, exist_ok=True)
            downloaded = await self._client.download_media(message, file=str(directory))
        except TelegramDownloadError:
            raise
        except Exception as exc:
            raise TelegramDownloadError(
                "Telegram post yuklanmadi. Bot kanalga kira olishi kerak."
            ) from exc
        if not downloaded:
            raise TelegramDownloadError("Telegram media fayli yuklanmadi")
        result = Path(downloaded)
        if result.stat().st_size > self.max_bytes:
            result.unlink(missing_ok=True)
            raise TelegramDownloadError("Telegram media fayli ruxsat etilgan hajmdan katta")
        return result

