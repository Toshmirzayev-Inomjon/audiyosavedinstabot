from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import shutil
from dataclasses import dataclass

logger = logging.getLogger(__name__)

_QUICK_TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


@dataclass(slots=True)
class QuickTunnel:
    url: str
    process: asyncio.subprocess.Process
    log_task: asyncio.Task[None]

    async def stop(self) -> None:
        if self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()

        self.log_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.log_task


async def _read_line(process: asyncio.subprocess.Process) -> str:
    if process.stdout is None:
        return ""
    line = await process.stdout.readline()
    return line.decode(errors="replace").strip()


async def _drain_logs(process: asyncio.subprocess.Process) -> None:
    while process.returncode is None:
        line = await _read_line(process)
        if not line:
            if process.returncode is not None:
                return
            await asyncio.sleep(0.1)
            continue
        logger.debug("cloudflared: %s", line)


async def _wait_for_url(process: asyncio.subprocess.Process) -> str:
    while process.returncode is None:
        line = await _read_line(process)
        if not line:
            continue
        logger.debug("cloudflared: %s", line)
        match = _QUICK_TUNNEL_URL.search(line)
        if match:
            return match.group(0)
    raise RuntimeError("cloudflared URL yaratmasdan to'xtadi")


async def start_quick_tunnel(port: int, timeout: float = 30) -> QuickTunnel:
    executable = shutil.which("cloudflared")
    if executable is None:
        raise RuntimeError("cloudflared topilmadi")

    process = await asyncio.create_subprocess_exec(
        executable,
        "tunnel",
        "--no-autoupdate",
        "--url",
        f"http://127.0.0.1:{port}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    try:
        url = await asyncio.wait_for(_wait_for_url(process), timeout=timeout)
    except BaseException:
        if process.returncode is None:
            process.terminate()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=5)
        raise

    logger.info("Temporary WebApp tunnel started: %s", url)
    return QuickTunnel(
        url=url,
        process=process,
        log_task=asyncio.create_task(_drain_logs(process)),
    )
