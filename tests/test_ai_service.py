import base64
import json

import pytest

from app.services.ai import MusicGenerationError, MusicGenerationService


def test_music_prompt_validation() -> None:
    assert MusicGenerationService.normalize_prompt("  uzbekcha   pop  qo'shiq  ") == (
        "uzbekcha pop qo'shiq"
    )
    with pytest.raises(MusicGenerationError):
        MusicGenerationService.normalize_prompt("qisqa")


@pytest.mark.asyncio
async def test_music_generation_requires_token(tmp_path) -> None:
    service = MusicGenerationService(api_token=None, model="facebook/musicgen-small")

    with pytest.raises(MusicGenerationError):
        await service.generate("quvnoq uzbekcha pop qo'shiq", tmp_path)


@pytest.mark.asyncio
async def test_save_audio_response_from_bytes(tmp_path) -> None:
    output = await MusicGenerationService._save_response(
        b"audio-bytes",
        tmp_path,
        content_type="audio/wav",
    )

    assert output.name == "ai-music.wav"
    assert output.read_bytes() == b"audio-bytes"


@pytest.mark.asyncio
async def test_save_audio_response_from_base64_json(tmp_path) -> None:
    body = json.dumps(
        {
            "audio": base64.b64encode(b"audio-bytes").decode(),
            "mime_type": "audio/mpeg",
        }
    ).encode()

    output = await MusicGenerationService._save_response(
        body,
        tmp_path,
        content_type="application/json",
    )

    assert output.name == "ai-music.mp3"
    assert output.read_bytes() == b"audio-bytes"
