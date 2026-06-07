import base64

import pytest

from app.services.ai import AIResult, AIService, AIServiceError


def _service() -> AIService:
    return AIService(
        provider="gemini",
        openai_api_key=None,
        openai_model="openai-text",
        openai_image_model="openai-image",
        gemini_api_key="gemini-key",
        gemini_model="gemini-text",
        gemini_image_model="gemini-image",
    )


def test_gemini_text_and_sources_are_parsed() -> None:
    text, sources = _service()._parse_gemini_text(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Javob matni"}],
                    },
                    "groundingMetadata": {
                        "groundingChunks": [
                            {
                                "web": {
                                    "uri": "https://example.com/a",
                                    "title": "Example",
                                }
                            }
                        ]
                    },
                }
            ]
        }
    )

    assert text == "Javob matni"
    assert sources == [{"url": "https://example.com/a", "title": "Example"}]


def test_gemini_image_is_parsed_from_inline_data() -> None:
    image = _service()._parse_gemini_image(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": base64.b64encode(b"image").decode(),
                                }
                            }
                        ]
                    }
                }
            ]
        }
    )

    assert image == b"image"


def test_gemini_quota_error_is_user_friendly() -> None:
    error = _service()._gemini_error(
        {
            "error": {
                "message": (
                    "You exceeded your current quota, please check your plan "
                    "and billing details."
                )
            }
        }
    )

    assert error.quota_exceeded is True
    assert "Gemini API kvotasi tugagan" in str(error)


@pytest.mark.asyncio
async def test_auto_provider_falls_back_to_openai_when_gemini_fails(
    monkeypatch,
) -> None:
    service = AIService(
        provider="auto",
        openai_api_key="openai-key",
        openai_model="openai-text",
        openai_image_model="openai-image",
        gemini_api_key="gemini-key",
        gemini_model="gemini-text",
        gemini_image_model="gemini-image",
    )

    async def broken_gemini(**_kwargs):
        raise AIServiceError("quota", quota_exceeded=True)

    async def openai_result(**_kwargs):
        return AIResult(text="OpenAI fallback")

    monkeypatch.setattr(service, "_respond_gemini", broken_gemini)
    monkeypatch.setattr(service, "_respond_openai", openai_result)

    result = await service.respond(
        user_input="salom",
        instructions="",
    )

    assert result.text == "OpenAI fallback"
