from pathlib import Path

import pytest

from app.services.media import MediaService


class RecordingMediaService(MediaService):
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    async def _run(self, *command: str) -> None:
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
