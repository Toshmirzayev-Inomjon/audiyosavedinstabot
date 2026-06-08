from __future__ import annotations

from pathlib import Path

import aiohttp


class RecognitionError(RuntimeError):
    pass


async def recognize_with_audd(file_path: Path, api_key: str | None) -> dict[str, str]:
    if not api_key:
        raise RecognitionError("Qo'shiq aniqlash uchun AUDD_API_KEY sozlanmagan")
    data = aiohttp.FormData()
    data.add_field("api_token", api_key)
    data.add_field("file", file_path.read_bytes(), filename=file_path.name)
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.post("https://api.audd.io/", data=data) as response:
            payload = await response.json(content_type=None)
    result = payload.get("result") if isinstance(payload, dict) else None
    if not isinstance(result, dict):
        raise RecognitionError("Qo'shiq aniqlanmadi")
    return {
        "artist": str(result.get("artist") or ""),
        "title": str(result.get("title") or ""),
        "album": str(result.get("album") or ""),
    }
