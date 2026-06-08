import base64

import pytest

from app.services.ai import AIService


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


def _local_service() -> AIService:
    return AIService(
        provider="local",
        openai_api_key=None,
        openai_model="openai-text",
        openai_image_model="openai-image",
        gemini_api_key=None,
        gemini_model="gemini-text",
        gemini_image_model="gemini-image",
    )


@pytest.mark.asyncio
async def test_local_provider_answers_without_api_key() -> None:
    service = _local_service()

    result = await service.respond(
        user_input="salom bot",
        instructions="Foydali javob bering",
    )

    assert service.active_provider == "local"
    assert service.configured is True
    assert "Lokal AI rejimi" in result.text


@pytest.mark.asyncio
async def test_local_provider_handles_planned_service_without_api_key() -> None:
    result = await _local_service().respond(
        user_input="+500000 oylik, -25000 ovqat, -12000 transport",
        instructions=(
            "Service slug: expense_tracker\n"
            "Service name: Expense Tracker\n"
            "Service description: Daromad va xarajatlar daftari."
        ),
    )

    assert "Expense tracker natijasi" in result.text
    assert "Daromad" in result.text


@pytest.mark.asyncio
async def test_local_web_search_returns_local_guidance() -> None:
    result = await _local_service().respond(
        user_input="Samarqand",
        instructions=(
            "Service slug: live_weather\n"
            "Service name: Live Weather\n"
            "Service description: Joriy ob-havo."
        ),
        web_search=True,
    )

    assert "Ob-havo lokal rejimi" in result.text
    assert "Jonli internet qidiruvi o'rniga" in result.text


@pytest.mark.asyncio
async def test_local_provider_generates_image_without_api_key() -> None:
    image = await _local_service().generate_image(
        prompt="Bot uchun chiroyli logo",
        instructions="Oddiy rasm yarating",
    )

    assert image.startswith(b"\x89PNG")


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
async def test_auto_provider_uses_local_even_when_external_keys_exist() -> None:
    service = AIService(
        provider="auto",
        openai_api_key="openai-key",
        openai_model="openai-text",
        openai_image_model="openai-image",
        gemini_api_key="gemini-key",
        gemini_model="gemini-text",
        gemini_image_model="gemini-image",
    )

    result = await service.respond(
        user_input="salom",
        instructions="",
    )

    assert service.active_provider == "local"
    assert "Lokal AI rejimi" in result.text
