import json

import pytest

from app.services.speech import SpeechRecognitionError, SpeechRecognitionService


def test_extract_text_from_huggingface_response() -> None:
    body = json.dumps({"text": "  oq   libos  "}).encode()

    assert SpeechRecognitionService._extract_text(body) == "oq libos"


def test_extract_text_rejects_empty_result() -> None:
    body = json.dumps({"text": " "}).encode()

    with pytest.raises(SpeechRecognitionError):
        SpeechRecognitionService._extract_text(body)


@pytest.mark.asyncio
async def test_transcribe_requires_token(tmp_path) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    service = SpeechRecognitionService(api_token=None, model="openai/whisper-small")

    with pytest.raises(SpeechRecognitionError):
        await service.transcribe(audio)
