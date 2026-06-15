from __future__ import annotations

import asyncio
import json
import mimetypes
from pathlib import Path
from typing import Any
from urllib.parse import quote

import aiohttp


class SpeechRecognitionError(RuntimeError):
    pass


class SpeechRecognitionService:
    def __init__(
        self,
        *,
        api_token: str | None,
        model: str,
        timeout_seconds: int = 90,
    ) -> None:
        self.api_token = api_token
        self.model = model
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_token and self.model)

    async def transcribe(self, audio_path: Path) -> str:
        if not self.configured:
            raise SpeechRecognitionError(
                "Ovoz orqali qidirish uchun HUGGINGFACE_API_TOKEN kerak"
            )
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            raise SpeechRecognitionError("Ovozli xabar fayli topilmadi")

        url = (
            "https://api-inference.huggingface.co/models/"
            f"{quote(self.model, safe='/')}"
        )
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": mimetypes.guess_type(audio_path.name)[0]
            or "application/octet-stream",
        }
        payload = await asyncio.to_thread(audio_path.read_bytes)
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for attempt in range(3):
                async with session.post(url, headers=headers, data=payload) as response:
                    body = await response.read()
                    if 200 <= response.status < 300:
                        return self._extract_text(body)
                    error = self._decode_error(body)
                    if response.status in {429, 503} and attempt < 2:
                        await asyncio.sleep(self._retry_delay(error))
                        continue
                    raise SpeechRecognitionError(
                        f"Hugging Face ASR xatosi ({response.status}): {error}"
                    )
        raise SpeechRecognitionError("Hugging Face ASR javob bermadi")

    @staticmethod
    def _extract_text(body: bytes) -> str:
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpeechRecognitionError("ASR javobi JSON formatida emas") from exc
        text = SpeechRecognitionService._text_from_json(data)
        normalized = " ".join(text.split())
        if len(normalized) < 2:
            raise SpeechRecognitionError("Ovozdan qo'shiq nomi aniqlanmadi")
        return normalized

    @staticmethod
    def _text_from_json(data: Any) -> str:
        if isinstance(data, dict):
            value = data.get("text")
            if isinstance(value, str):
                return value
            if isinstance(data.get("error"), str):
                raise SpeechRecognitionError(str(data["error"]))
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    return str(item["text"])
        raise SpeechRecognitionError("ASR javobida matn topilmadi")

    @staticmethod
    def _decode_error(body: bytes) -> str:
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return body.decode("utf-8", errors="replace")[:500]
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, str):
                return error[:500]
        return str(data)[:500]

    @staticmethod
    def _retry_delay(error: str) -> float:
        lowered = error.lower()
        if "loading" in lowered:
            return 8
        if "rate" in lowered or "too many" in lowered:
            return 5
        return 3
