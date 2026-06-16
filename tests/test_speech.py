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


def test_extract_song_query_from_audd_response() -> None:
    body = json.dumps(
        {"status": "success", "result": {"artist": "Saman", "title": "BURGUT 2"}}
    ).encode()

    assert SpeechRecognitionService._extract_song_query(body) == "Saman BURGUT 2"


def test_extract_song_query_rejects_no_result() -> None:
    body = json.dumps({"status": "success", "result": None}).encode()

    with pytest.raises(SpeechRecognitionError):
        SpeechRecognitionService._extract_song_query(body)


@pytest.mark.asyncio
async def test_transcribe_requires_token(tmp_path) -> None:
    audio = tmp_path / "voice.wav"
    audio.write_bytes(b"audio")
    service = SpeechRecognitionService(api_token=None, model="openai/whisper-small")

    with pytest.raises(SpeechRecognitionError):
        await service.transcribe(audio)


@pytest.mark.asyncio
async def test_identify_song_requires_music_token(tmp_path) -> None:
    audio = tmp_path / "voice.ogg"
    audio.write_bytes(b"audio")
    service = SpeechRecognitionService(
        api_token="hf_token",
        model="openai/whisper-small",
        music_api_token=None,
    )

    assert service.music_recognition_configured is False
    with pytest.raises(SpeechRecognitionError):
        await service.identify_song(audio)
