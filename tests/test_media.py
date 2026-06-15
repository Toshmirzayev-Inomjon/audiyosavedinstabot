from pathlib import Path

import pytest

from app.services.media import MediaService


class RecordingMediaService(MediaService):
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    async def _run(self, *command: str, **_kwargs) -> None:
        self.commands.append(command)


@pytest.mark.asyncio
async def test_video_note_rectangle_has_no_visual_effects(tmp_path: Path) -> None:
    service = RecordingMediaService()

    await service.to_rectangle(
        tmp_path / "source.mp4",
        tmp_path / "rectangle.mp4",
        from_video_note=True,
    )

    command = service.commands[0]
    video_filter = command[command.index("-vf") + 1]
    assert video_filter == (
        "scale=720:720:force_original_aspect_ratio=decrease,setsar=1"
    )
    assert "-filter_complex" not in command
    assert "boxblur" not in " ".join(command)
    assert "overlay" not in " ".join(command)


@pytest.mark.asyncio
async def test_to_wav_uses_speech_friendly_audio_format(tmp_path: Path) -> None:
    service = RecordingMediaService()

    await service.to_wav(tmp_path / "voice.ogg", tmp_path / "voice.wav")

    command = service.commands[0]
    assert command[command.index("-ac") + 1] == "1"
    assert command[command.index("-ar") + 1] == "16000"
    assert command[command.index("-codec:a") + 1] == "pcm_s16le"
