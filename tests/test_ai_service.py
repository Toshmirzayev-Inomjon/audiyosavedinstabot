import base64

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
