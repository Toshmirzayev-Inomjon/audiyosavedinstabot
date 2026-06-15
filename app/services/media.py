from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path


class MediaConversionError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class MediaInfo:
    duration: float
    width: int
    height: int


class MediaService:
    @staticmethod
    def available() -> bool:
        return bool(shutil.which("ffmpeg") and shutil.which("ffprobe"))

    @staticmethod
    def require_ffmpeg() -> None:
        if not MediaService.available():
            raise MediaConversionError(
                "Serverda ffmpeg topilmadi. Docker orqali ishga tushiring yoki ffmpeg o'rnating."
            )

    async def probe(self, source: Path) -> MediaInfo:
        self.require_ffmpeg()
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration:stream=width,height",
            "-of",
            "json",
            str(source),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise MediaConversionError(
                f"Media tekshirilmadi: {stderr.decode(errors='replace')[-300:]}"
            )
        data = json.loads(stdout)
        video_stream = next(
            (
                stream
                for stream in data.get("streams", [])
                if stream.get("width") and stream.get("height")
            ),
            {},
        )
        return MediaInfo(
            duration=float(data.get("format", {}).get("duration") or 0),
            width=int(video_stream.get("width") or 0),
            height=int(video_stream.get("height") or 0),
        )

    async def to_mp3(
        self,
        source: Path,
        destination: Path,
        *,
        cancel_event: asyncio.Event | None = None,
    ) -> Path:
        await self._run(
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-codec:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(destination),
            cancel_event=cancel_event,
        )
        return destination

    async def to_circle(self, source: Path, destination: Path) -> Path:
        await self._run(
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-t",
            "60",
            "-vf",
            r"crop=min(iw\,ih):min(iw\,ih),scale=640:640,setsar=1",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "24",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(destination),
        )
        return destination

    async def to_rectangle(
        self,
        source: Path,
        destination: Path,
        *,
        from_video_note: bool = False,
    ) -> Path:
        del from_video_note
        await self._run(
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vf",
            "scale=720:720:force_original_aspect_ratio=decrease,setsar=1",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            "23",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(destination),
        )
        return destination

    async def _run(
        self,
        *command: str,
        cancel_event: asyncio.Event | None = None,
    ) -> None:
        self.require_ffmpeg()
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        if process.stderr is None:
            raise MediaConversionError("ffmpeg stderr oqimi ochilmadi")
        stderr_task = asyncio.create_task(process.stderr.read())
        while process.returncode is None:
            try:
                await asyncio.wait_for(process.wait(), timeout=0.4)
            except TimeoutError:
                if cancel_event and cancel_event.is_set():
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=3)
                    except TimeoutError:
                        process.kill()
                        await process.wait()
                    await stderr_task
                    raise MediaConversionError(
                        "Konvertatsiya bekor qilindi"
                    ) from None
        stderr = await stderr_task
        if process.returncode != 0:
            detail = stderr.decode(errors="replace")[-800:]
            raise MediaConversionError(f"Konvertatsiya bajarilmadi: {detail}")
