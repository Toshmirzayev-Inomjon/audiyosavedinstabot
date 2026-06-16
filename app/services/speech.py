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
        music_api_token: str | None = None,
        timeout_seconds: int = 90,
    ) -> None:
        self.api_token = api_token
        self.model = model
        self.music_api_token = music_api_token
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_token and self.model)

    @property
    def music_recognition_configured(self) -> bool:
        return bool(self.music_api_token)

    async def transcribe(self, audio_path: Path) -> str:
        if not self.configured:
            raise SpeechRecognitionError(
                "Ovoz orqali qidirish uchun HUGGINGFACE_API_TOKEN kerak"
            )
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            raise SpeechRecognitionError("Ovozli xabar fayli topilmadi")

        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": mimetypes.guess_type(audio_path.name)[0]
            or "application/octet-stream",
        }
        payload = await asyncio.to_thread(audio_path.read_bytes)
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        last_error: SpeechRecognitionError | None = None
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for url in self._model_urls(self.model):
                for attempt in range(3):
                    try:
                        async with session.post(url, headers=headers, data=payload) as response:
                            body = await response.read()
                            if 200 <= response.status < 300:
                                return self._extract_text(body)
                            error = self._decode_error(body)
                            last_error = SpeechRecognitionError(
                                f"Hugging Face ASR xatosi ({response.status}): {error}"
                            )
                            if response.status in {429, 503} and attempt < 2:
                                await asyncio.sleep(self._retry_delay(error))
                                continue
                            break
                    except aiohttp.ClientError as exc:
                        last_error = SpeechRecognitionError(
                            f"ASR serveriga ulanishda xato ({url}): {exc}"
                        )
                        break
                    except TimeoutError:
                        last_error = SpeechRecognitionError(
                            "ASR serveri juda sekin javob berdi. "
                            "Birozdan keyin qayta urinib ko'ring."
                        )
                        break
        if last_error:
            raise last_error
        raise SpeechRecognitionError("Hugging Face ASR javob bermadi")

    async def identify_song(self, audio_path: Path) -> str:
        if not self.music_api_token:
            raise SpeechRecognitionError(
                "Musiqani ovozdan tanish uchun AUDD_API_TOKEN kerak"
            )
        if not audio_path.is_file() or audio_path.stat().st_size == 0:
            raise SpeechRecognitionError("Ovozli xabar fayli topilmadi")

        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        form = aiohttp.FormData()
        form.add_field("api_token", self.music_api_token)
        form.add_field("return", "apple_music,spotify")
        form.add_field(
            "file",
            await asyncio.to_thread(audio_path.read_bytes),
            filename=audio_path.name,
            content_type=mimetypes.guess_type(audio_path.name)[0]
            or "application/octet-stream",
        )
        async with aiohttp.ClientSession(timeout=timeout) as session:
            try:
                async with session.post("https://api.audd.io/", data=form) as response:
                    body = await response.read()
            except TimeoutError as exc:
                raise SpeechRecognitionError(
                    "AudD serveri juda sekin javob berdi. Birozdan keyin qayta urinib ko'ring."
                ) from exc
            except aiohttp.ClientError as exc:
                raise SpeechRecognitionError(f"AudD serveriga ulanishda xato: {exc}") from exc
        if response.status < 200 or response.status >= 300:
            raise SpeechRecognitionError(
                f"AudD xatosi ({response.status}): {self._decode_error(body)}"
            )
        return self._extract_song_query(body)

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

    @staticmethod
    def _model_urls(model: str) -> tuple[str, str]:
        encoded = quote(model, safe="/")
        return (
            f"https://router.huggingface.co/hf-inference/models/{encoded}",
            f"https://api-inference.huggingface.co/models/{encoded}",
        )

    @staticmethod
    def _extract_song_query(body: bytes) -> str:
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SpeechRecognitionError("AudD javobi JSON formatida emas") from exc
        if not isinstance(data, dict):
            raise SpeechRecognitionError("AudD javobi noto'g'ri")
        if data.get("status") != "success":
            error = data.get("error") or data.get("message") or "AudD qo'shiqni tanimadi"
            raise SpeechRecognitionError(str(error))
        result = data.get("result")
        if not isinstance(result, dict):
            raise SpeechRecognitionError("Qo'shiq ovozdan topilmadi")
        artist = str(result.get("artist") or "").strip()
        title = str(result.get("title") or "").strip()
        query = " ".join(item for item in (artist, title) if item)
        if len(query) < 2:
            raise SpeechRecognitionError("Qo'shiq ovozdan topilmadi")
        return query
