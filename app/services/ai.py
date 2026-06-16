from __future__ import annotations

import asyncio
import base64
import binascii
import json
import mimetypes
from pathlib import Path
from urllib.parse import quote

import aiohttp


class MusicGenerationError(RuntimeError):
    pass


class MusicGenerationService:
    def __init__(
        self,
        *,
        api_token: str | None,
        model: str,
        timeout_seconds: int = 300,
    ) -> None:
        self.api_token = api_token
        self.model = model
        self.timeout_seconds = timeout_seconds

    @property
    def configured(self) -> bool:
        return bool(self.api_token and self.model)

    async def generate(self, prompt: str, directory: Path) -> Path:
        prompt = self.normalize_prompt(prompt)
        if not self.configured:
            raise MusicGenerationError(
                "AI qo'shiq yaratish uchun HUGGINGFACE_API_TOKEN kerak"
            )
        directory.mkdir(parents=True, exist_ok=True)

        url = (
            "https://api-inference.huggingface.co/models/"
            f"{quote(self.model, safe='/')}"
        )
        headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "audio/wav, audio/mpeg, audio/flac, application/json",
            "Content-Type": "application/json",
        }
        payload = {
            "inputs": prompt,
            "parameters": {
                # MusicGen models use generated tokens to control approximate length.
                # This keeps output short enough for Telegram and server limits.
                "max_new_tokens": 256,
                "do_sample": True,
                "temperature": 1.0,
            },
            "options": {"wait_for_model": True},
        }
        timeout = aiohttp.ClientTimeout(total=self.timeout_seconds)
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for attempt in range(3):
                    async with session.post(url, headers=headers, json=payload) as response:
                        body = await response.read()
                        content_type = response.headers.get("Content-Type", "")
                        if 200 <= response.status < 300:
                            return await self._save_response(
                                body,
                                directory,
                                content_type=content_type,
                            )
                        error = self._decode_error(body)
                        if response.status in {429, 503} and attempt < 2:
                            await asyncio.sleep(self._retry_delay(error))
                            continue
                        raise MusicGenerationError(
                            f"Hugging Face MusicGen xatosi ({response.status}): {error}"
                        )
        except MusicGenerationError:
            raise
        except TimeoutError as exc:
            raise MusicGenerationError(
                "AI generator juda sekin javob berdi. Birozdan keyin qayta urinib ko'ring."
            ) from exc
        except aiohttp.ClientError as exc:
            raise MusicGenerationError(f"AI serveriga ulanishda xato: {exc}") from exc
        raise MusicGenerationError("Hugging Face MusicGen javob bermadi")

    @staticmethod
    def normalize_prompt(prompt: str) -> str:
        normalized = " ".join(prompt.strip().split())
        if len(normalized) < 10:
            raise MusicGenerationError(
                "AI qo'shiq uchun kamida 10 ta belgi yozing. "
                "Masalan: 'quvnoq uzbekcha pop qo'shiq, dutor va baraban bilan'."
            )
        if len(normalized) > 800:
            raise MusicGenerationError("AI qo'shiq matni 800 belgidan oshmasin")
        return normalized

    @staticmethod
    async def _save_response(
        body: bytes,
        directory: Path,
        *,
        content_type: str,
    ) -> Path:
        if MusicGenerationService._looks_like_json(content_type, body):
            body, content_type = MusicGenerationService._audio_from_json(body)
        if not body:
            raise MusicGenerationError("AI audio bo'sh qaytdi")
        suffix = MusicGenerationService._suffix_for_content_type(content_type)
        output = directory / f"ai-music{suffix}"
        output.write_bytes(body)
        return output

    @staticmethod
    def _looks_like_json(content_type: str, body: bytes) -> bool:
        if "json" in content_type.lower():
            return True
        stripped = body.lstrip()
        return stripped.startswith(b"{") or stripped.startswith(b"[")

    @staticmethod
    def _audio_from_json(body: bytes) -> tuple[bytes, str]:
        try:
            data = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise MusicGenerationError("AI javobi audio formatida emas") from exc

        if isinstance(data, dict):
            if isinstance(data.get("error"), str):
                raise MusicGenerationError(str(data["error"]))
            for key in ("audio", "generated_audio", "data"):
                value = data.get(key)
                if isinstance(value, str):
                    return MusicGenerationService._decode_audio_value(value), str(
                        data.get("mime_type") or "audio/wav"
                    )
            if isinstance(data.get("array"), list):
                raise MusicGenerationError(
                    "AI modeli raw array qaytardi. Server audio fayl formatini qo'llamadi."
                )
        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    for key in ("audio", "generated_audio", "data"):
                        value = item.get(key)
                        if isinstance(value, str):
                            return MusicGenerationService._decode_audio_value(value), str(
                                item.get("mime_type") or "audio/wav"
                            )
        raise MusicGenerationError("AI javobida audio topilmadi")

    @staticmethod
    def _decode_audio_value(value: str) -> bytes:
        raw = value.split(",", maxsplit=1)[1] if value.startswith("data:") else value
        try:
            return base64.b64decode(raw, validate=False)
        except (binascii.Error, ValueError) as exc:
            raise MusicGenerationError("AI javobidagi audio base64 formatida emas") from exc

    @staticmethod
    def _suffix_for_content_type(content_type: str) -> str:
        clean_type = content_type.split(";", maxsplit=1)[0].strip().lower()
        if clean_type in {"audio/mpeg", "audio/mp3"}:
            return ".mp3"
        if clean_type in {"audio/flac", "audio/x-flac"}:
            return ".flac"
        if clean_type in {"audio/wav", "audio/wave", "audio/x-wav"}:
            return ".wav"
        return mimetypes.guess_extension(clean_type) or ".wav"

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
            message = data.get("message")
            if isinstance(message, str):
                return message[:500]
        return str(data)[:500]

    @staticmethod
    def _retry_delay(error: str) -> float:
        lowered = error.lower()
        if "loading" in lowered:
            return 12
        if "rate" in lowered or "quota" in lowered or "too many" in lowered:
            return 8
        return 5
