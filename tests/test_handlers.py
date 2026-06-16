from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendVideoNote

from app.handlers import _input_file, _resolve_source, _send_video_note_or_fallback


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


class VoiceMessage:
    def __init__(self) -> None:
        self.voice = type(
            "Voice",
            (),
            {"file_id": "voice-file-id", "file_size": 100, "duration": 3},
        )()
        self.video_note = None
        self.video = None
        self.audio = None
        self.document = None


class EmptyMessage:
    text = None


class FakeDownloader:
    def __init__(self) -> None:
        self.url = ""
        self.audio_url = ""

    async def download(self, url: str, directory: Path, **_kwargs) -> Path:
        self.url = url
        output = directory / "source.mp4"
        output.write_bytes(b"video")
        return output

    async def download_audio_or_song(self, url: str, directory: Path, **_kwargs) -> Path:
        self.audio_url = url
        output = directory / "source.mp3"
        output.write_bytes(b"audio")
        return output


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


def test_input_file_accepts_voice_messages() -> None:
    media, filename = _input_file(VoiceMessage(), allow_audio=True)

    assert media.file_id == "voice-file-id"
    assert filename == "voice.ogg"


@pytest.mark.asyncio
async def test_resolve_source_uses_text_override_for_saved_url(tmp_path: Path) -> None:
    downloader = FakeDownloader()
    services = SimpleNamespace(downloader=downloader, telegram=None, settings=None)

    result = await _resolve_source(
        EmptyMessage(),
        bot=None,
        services=services,
        directory=tmp_path,
        text_override="https://youtu.be/abc123",
    )

    assert result.name == "source.mp4"
    assert downloader.url == "https://youtu.be/abc123"


@pytest.mark.asyncio
async def test_resolve_source_uses_full_song_download_for_audio_url(tmp_path: Path) -> None:
    downloader = FakeDownloader()
    services = SimpleNamespace(downloader=downloader, telegram=None, settings=None)

    result = await _resolve_source(
        EmptyMessage(),
        bot=None,
        services=services,
        directory=tmp_path,
        prefer_audio=True,
        text_override="https://www.instagram.com/reel/abc123/",
    )

    assert result.name == "source.mp3"
    assert downloader.audio_url == "https://www.instagram.com/reel/abc123/"
