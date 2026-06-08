from __future__ import annotations

import asyncio
import shutil
from pathlib import Path


class FFmpegError(RuntimeError):
    pass


def ensure_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise FFmpegError("Serverda ffmpeg topilmadi")


async def run_ffmpeg(*args: str) -> None:
    ensure_ffmpeg()
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    if process.returncode:
        raise FFmpegError(stderr.decode(errors="replace")[-1000:])


async def extract_mp3(source: Path, output: Path) -> Path:
    await run_ffmpeg("-i", str(source), "-vn", "-b:a", "192k", str(output))
    return output


async def cut_audio(source: Path, output: Path, start: str, duration: str) -> Path:
    await run_ffmpeg(
        "-ss",
        start,
        "-t",
        duration,
        "-i",
        str(source),
        "-c:a",
        "libmp3lame",
        str(output),
    )
    return output


async def mute_video(source: Path, output: Path) -> Path:
    await run_ffmpeg("-i", str(source), "-an", "-c:v", "copy", str(output))
    return output


async def reverse_video(source: Path, output: Path) -> Path:
    await run_ffmpeg("-i", str(source), "-vf", "reverse", "-af", "areverse", str(output))
    return output


async def video_to_gif(source: Path, output: Path) -> Path:
    await run_ffmpeg("-i", str(source), "-vf", "fps=12,scale=480:-1:flags=lanczos", str(output))
    return output
