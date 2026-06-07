from __future__ import annotations

import base64
from dataclasses import dataclass

import aiohttp


class AIServiceError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AIResult:
    text: str
    sources: tuple[dict[str, str], ...] = ()


class AIService:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str,
        image_model: str,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.image_model = image_model

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise AIServiceError("OPENAI_API_KEY serverda sozlanmagan")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    async def respond(
        self,
        *,
        user_input: str,
        instructions: str,
        web_search: bool = False,
        domains: tuple[str, ...] = (),
    ) -> AIResult:
        payload: dict[str, object] = {
            "model": self.model,
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
                headers=self._headers(),
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

    async def generate_image(
        self,
        *,
        prompt: str,
        instructions: str,
    ) -> bytes:
        payload = {
            "model": self.image_model,
            "prompt": f"{instructions}\n\nUser request: {prompt}",
            "size": "1024x1024",
        }
        timeout = aiohttp.ClientTimeout(total=180)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                "https://api.openai.com/v1/images/generations",
                headers=self._headers(),
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
