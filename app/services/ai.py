from __future__ import annotations

import base64
from dataclasses import dataclass
from urllib.parse import quote

import aiohttp


class AIServiceError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        quota_exceeded: bool = False,
    ) -> None:
        super().__init__(message)
        self.quota_exceeded = quota_exceeded


@dataclass(frozen=True, slots=True)
class AIResult:
    text: str
    sources: tuple[dict[str, str], ...] = ()


class AIService:
    def __init__(
        self,
        *,
        provider: str,
        openai_api_key: str | None,
        openai_model: str,
        openai_image_model: str,
        gemini_api_key: str | None,
        gemini_model: str,
        gemini_image_model: str,
    ) -> None:
        self.provider = provider
        self.openai_api_key = openai_api_key
        self.openai_model = openai_model
        self.openai_image_model = openai_image_model
        self.gemini_api_key = gemini_api_key
        self.gemini_model = gemini_model
        self.gemini_image_model = gemini_image_model

    @property
    def active_provider(self) -> str:
        if self.provider == "auto":
            if self.gemini_api_key:
                return "gemini"
            if self.openai_api_key:
                return "openai"
            return "none"
        return self.provider

    @property
    def configured(self) -> bool:
        if self.active_provider == "gemini":
            return bool(self.gemini_api_key)
        if self.active_provider == "openai":
            return bool(self.openai_api_key)
        return False

    def _openai_headers(self) -> dict[str, str]:
        if not self.openai_api_key:
            raise AIServiceError("OPENAI_API_KEY serverda sozlanmagan")
        return {
            "Authorization": f"Bearer {self.openai_api_key}",
            "Content-Type": "application/json",
        }

    def _gemini_headers(self) -> dict[str, str]:
        if not self.gemini_api_key:
            raise AIServiceError("GEMINI_API_KEY serverda sozlanmagan")
        return {
            "X-goog-api-key": self.gemini_api_key,
            "Content-Type": "application/json",
        }

    def _gemini_url(self, model: str) -> str:
        model_name = model if model.startswith("models/") else f"models/{model}"
        return (
            "https://generativelanguage.googleapis.com/v1beta/"
            f"{quote(model_name, safe='/')}:generateContent"
        )

    @property
    def _can_fallback_to_openai(self) -> bool:
        return self.provider == "auto" and bool(self.openai_api_key)

    async def respond(
        self,
        *,
        user_input: str,
        instructions: str,
        web_search: bool = False,
        domains: tuple[str, ...] = (),
    ) -> AIResult:
        if self.active_provider == "gemini":
            try:
                return await self._respond_gemini(
                    user_input=user_input,
                    instructions=instructions,
                    web_search=web_search,
                    domains=domains,
                )
            except AIServiceError:
                if not self._can_fallback_to_openai:
                    raise
                return await self._respond_openai(
                    user_input=user_input,
                    instructions=instructions,
                    web_search=web_search,
                    domains=domains,
                )
        if self.active_provider == "openai":
            return await self._respond_openai(
                user_input=user_input,
                instructions=instructions,
                web_search=web_search,
                domains=domains,
            )
        raise AIServiceError("AI API kaliti serverda sozlanmagan")

    async def _respond_openai(
        self,
        *,
        user_input: str,
        instructions: str,
        web_search: bool,
        domains: tuple[str, ...],
    ) -> AIResult:
        payload: dict[str, object] = {
            "model": self.openai_model,
            "instructions": (
                "You are a service inside a Telegram Mini App. "
                "Answer in the user's language, be concise and accurate. "
                "Never claim a real-time fact without a source. "
                + instructions
            ),
            "input": user_input,
            "max_output_tokens": 1600,
        }
        if web_search:
            tool: dict[str, object] = {"type": "web_search"}
            if domains:
                tool["filters"] = {"allowed_domains": list(domains)}
            payload["tools"] = [tool]
            payload["include"] = ["web_search_call.action.sources"]

        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://api.openai.com/v1/responses",
                headers=self._openai_headers(),
                json=payload,
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    message = (
                        data.get("error", {}).get("message")
                        if isinstance(data, dict)
                        else None
                    )
                    raise AIServiceError(message or "AI provayder xatosi")

        text = str(data.get("output_text", "")).strip()
        sources: list[dict[str, str]] = []
        for output in data.get("output", []):
            if not isinstance(output, dict):
                continue
            for content in output.get("content", []):
                if not isinstance(content, dict):
                    continue
                if not text and content.get("type") == "output_text":
                    text = str(content.get("text", "")).strip()
                for annotation in content.get("annotations", []):
                    if not isinstance(annotation, dict):
                        continue
                    url = annotation.get("url")
                    if url and not any(item["url"] == url for item in sources):
                        sources.append(
                            {
                                "url": str(url),
                                "title": str(annotation.get("title") or url),
                            }
                        )
            action = output.get("action")
            if isinstance(action, dict):
                for source in action.get("sources", []):
                    if not isinstance(source, dict) or not source.get("url"):
                        continue
                    url = str(source["url"])
                    if not any(item["url"] == url for item in sources):
                        sources.append(
                            {
                                "url": url,
                                "title": str(source.get("title") or url),
                            }
                        )
        if not text:
            raise AIServiceError("AI bo'sh javob qaytardi")
        return AIResult(text=text, sources=tuple(sources[:8]))

    async def _respond_gemini(
        self,
        *,
        user_input: str,
        instructions: str,
        web_search: bool,
        domains: tuple[str, ...],
    ) -> AIResult:
        system_text = (
            "You are a service inside a Telegram Mini App. "
            "Answer in the user's language, be concise and accurate. "
            "Never claim a real-time fact without a source. "
            + instructions
        )
        if web_search and domains:
            system_text += (
                "\nWhen using Google Search grounding, focus on and cite these "
                f"allowed domains where possible: {', '.join(domains)}."
            )
        payload: dict[str, object] = {
            "systemInstruction": {"parts": [{"text": system_text}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": user_input}],
                }
            ],
            "generationConfig": {"maxOutputTokens": 1600},
        }
        if web_search:
            payload["tools"] = [{"googleSearch": {}}]

        timeout = aiohttp.ClientTimeout(total=90)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self._gemini_url(self.gemini_model),
                headers=self._gemini_headers(),
                json=payload,
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise self._gemini_error(data)
        text, sources = self._parse_gemini_text(data)
        if not text:
            raise AIServiceError("Gemini bo'sh javob qaytardi")
        return AIResult(text=text, sources=tuple(sources[:8]))

    def _gemini_error(self, data: object) -> AIServiceError:
        message = "Gemini provayder xatosi"
        if isinstance(data, dict):
            error = data.get("error")
            if isinstance(error, dict) and error.get("message"):
                message = str(error["message"])
        lowered = message.lower()
        quota_exceeded = any(
            item in lowered
            for item in (
                "quota",
                "rate limit",
                "resource_exhausted",
                "billing",
            )
        )
        if quota_exceeded:
            message = (
                "Gemini API kvotasi tugagan yoki billing yoqilmagan. "
                "Google AI Studio'da billing/limitni tekshiring yoki "
                "Railway Variables'ga OPENAI_API_KEY qo'shing."
            )
        return AIServiceError(message, quota_exceeded=quota_exceeded)

    def _parse_gemini_text(
        self,
        data: object,
    ) -> tuple[str, list[dict[str, str]]]:
        if not isinstance(data, dict):
            return "", []
        parts: list[str] = []
        sources: list[dict[str, str]] = []
        for candidate in data.get("candidates", []):
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if isinstance(content, dict):
                for part in content.get("parts", []):
                    if isinstance(part, dict) and part.get("text"):
                        parts.append(str(part["text"]).strip())
            metadata = candidate.get("groundingMetadata")
            if not isinstance(metadata, dict):
                metadata = candidate.get("grounding_metadata")
            if not isinstance(metadata, dict):
                continue
            chunks = metadata.get("groundingChunks")
            if not isinstance(chunks, list):
                chunks = metadata.get("grounding_chunks", [])
            for chunk in chunks:
                if not isinstance(chunk, dict):
                    continue
                web = chunk.get("web")
                if not isinstance(web, dict):
                    continue
                url = web.get("uri") or web.get("url")
                if not url or any(item["url"] == str(url) for item in sources):
                    continue
                sources.append(
                    {
                        "url": str(url),
                        "title": str(web.get("title") or url),
                    }
                )
        return "\n".join(part for part in parts if part).strip(), sources

    async def generate_image(
        self,
        *,
        prompt: str,
        instructions: str,
    ) -> bytes:
        if self.active_provider == "gemini":
            try:
                return await self._generate_gemini_image(
                    prompt=prompt,
                    instructions=instructions,
                )
            except AIServiceError:
                if not self._can_fallback_to_openai:
                    raise
                return await self._generate_openai_image(
                    prompt=prompt,
                    instructions=instructions,
                )
        if self.active_provider == "openai":
            return await self._generate_openai_image(
                prompt=prompt,
                instructions=instructions,
            )
        raise AIServiceError("AI API kaliti serverda sozlanmagan")

    async def _generate_openai_image(
        self,
        *,
        prompt: str,
        instructions: str,
    ) -> bytes:
        payload = {
            "model": self.openai_image_model,
            "prompt": f"{instructions}\n\nUser request: {prompt}",
            "size": "1024x1024",
        }
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://api.openai.com/v1/images/generations",
                headers=self._openai_headers(),
                json=payload,
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    message = (
                        data.get("error", {}).get("message")
                        if isinstance(data, dict)
                        else None
                    )
                    raise AIServiceError(message or "AI rasm yaratish xatosi")
            items = data.get("data", []) if isinstance(data, dict) else []
            if not items:
                raise AIServiceError("AI rasm qaytarmadi")
            item = items[0]
            encoded = item.get("b64_json") if isinstance(item, dict) else None
            if encoded:
                return base64.b64decode(encoded)
            url = item.get("url") if isinstance(item, dict) else None
            if not url:
                raise AIServiceError("AI rasm formati noma'lum")
            async with session.get(str(url)) as image_response:
                if image_response.status >= 400:
                    raise AIServiceError("AI rasmini yuklab bo'lmadi")
                return await image_response.read()

    async def _generate_gemini_image(
        self,
        *,
        prompt: str,
        instructions: str,
    ) -> bytes:
        payload: dict[str, object] = {
            "contents": [
                {
                    "parts": [
                        {"text": f"{instructions}\n\nUser request: {prompt}"}
                    ]
                }
            ],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                self._gemini_url(self.gemini_image_model),
                headers=self._gemini_headers(),
                json=payload,
            ) as response:
                data = await response.json(content_type=None)
                if response.status >= 400:
                    raise self._gemini_error(data)
        image = self._parse_gemini_image(data)
        if not image:
            raise AIServiceError("Gemini rasm qaytarmadi")
        return image

    def _parse_gemini_image(self, data: object) -> bytes | None:
        if not isinstance(data, dict):
            return None
        for candidate in data.get("candidates", []):
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            for part in content.get("parts", []):
                if not isinstance(part, dict):
                    continue
                inline_data = part.get("inlineData") or part.get("inline_data")
                if not isinstance(inline_data, dict):
                    continue
                encoded = inline_data.get("data")
                if encoded:
                    return base64.b64decode(str(encoded))
        return None
