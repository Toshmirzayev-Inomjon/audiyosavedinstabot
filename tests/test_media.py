from pathlib import Path

import pytest

from app.services.media import MediaService


class RecordingMediaService(MediaService):
    def __init__(self) -> None:
        self.commands: list[tuple[str, ...]] = []

    async def _run(self, *command: str) -> None:
        self.commands.append(command)


@pytest.mark.asyncio
async def test_video_note_rectangle_uses_center_crop(tmp_path: Path) -> None:
    service = RecordingMediaService()

    await service.to_rectangle(
        tmp_path / "source.mp4",
        tmp_path / "rectangle.mp4",
        from_video_note=True,
    )

    command = service.commands[0]
    filter_graph = command[command.index("-filter_complex") + 1]
    assert "crop=min(iw\\,ih):min(iw\\,ih),crop=iw*0.82:ih*0.82" in filter_graph

