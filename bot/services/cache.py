from __future__ import annotations

import hashlib
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from bot.database.models import MediaCache, utcnow

TRACKING_PARAMS = {
    "fbclid",
    "gclid",
    "igsh",
    "si",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


@dataclass(frozen=True, slots=True)
class CacheIdentity:
    normalized_url: str
    media_type: str
    quality: str

    @property
    def key(self) -> str:
        raw = f"{self.normalized_url}|{self.media_type}|{self.quality}"
        return hashlib.sha256(raw.encode()).hexdigest()


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
    ]
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/"),
            "",
            urlencode(query, doseq=True),
            "",
        )
    )


async def get_cached_media(
    session: AsyncSession,
    identity: CacheIdentity,
) -> MediaCache | None:
    row = await session.scalar(select(MediaCache).where(MediaCache.cache_key == identity.key))
    if row:
        await session.execute(
            update(MediaCache)
            .where(MediaCache.cache_key == identity.key)
            .values(last_used_at=utcnow())
        )
    return row


async def save_cached_media(
    session: AsyncSession,
    *,
    identity: CacheIdentity,
    platform: str,
    telegram_file_id: str,
    title: str = "",
    artist: str = "",
    duration: int | None = None,
) -> MediaCache:
    item = MediaCache(
        cache_key=identity.key,
        normalized_url=identity.normalized_url,
        platform=platform,
        media_type=identity.media_type,
        quality=identity.quality,
        telegram_file_id=telegram_file_id,
        title=title,
        artist=artist,
        duration=duration,
    )
    session.add(item)
    return item
