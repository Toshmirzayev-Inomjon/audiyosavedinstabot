from pathlib import Path

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendVideoNote

from app.handlers import _send_video_note_or_fallback


class VoiceForbiddenMessage:
    def __init__(self) -> None:
        self.fallback_sent = False

    async def answer_video_note(self, *_args, **_kwargs) -> None:
        raise TelegramBadRequest(
            method=SendVideoNote(chat_id=1, video_note="file"),
            message="Bad Request: VOICE_MESSAGES_FORBIDDEN",
        )

    async def answer_video(self, *_args, **_kwargs) -> None:
        self.fallback_sent = True


@pytest.mark.asyncio
async def test_video_note_forbidden_falls_back_to_regular_video(
    tmp_path: Path,
) -> None:
    output = tmp_path / "circle.mp4"
    output.write_bytes(b"video")
    message = VoiceForbiddenMessage()

    sent_as_note = await _send_video_note_or_fallback(
        message,
        output,
        duration=3,
    )

    assert sent_as_note is False
    assert message.fallback_sent is True
