from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar

T = TypeVar("T")


class JobCancelled(RuntimeError):
    pass


@dataclass(slots=True)
class JobContext:
    cancel_event: asyncio.Event
    queue_position: int

    def check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise JobCancelled("Amal foydalanuvchi tomonidan bekor qilindi")


class JobManager:
    def __init__(self, concurrency: int) -> None:
        self._concurrency = concurrency
        self._semaphore = asyncio.Semaphore(concurrency)
        self._lock = asyncio.Lock()
        self._waiting = 0
        self._active = 0
        self._events: dict[int, asyncio.Event] = {}

    async def run(
        self,
        user_id: int,
        work: Callable[[JobContext], Awaitable[T]],
        *,
        queued: Callable[[int], Awaitable[None]] | None = None,
    ) -> T:
        event = asyncio.Event()
        acquired = False
        async with self._lock:
            previous = self._events.get(user_id)
            if previous:
                previous.set()
            self._events[user_id] = event
            load = self._active + self._waiting
            position = load - self._concurrency + 1 if load >= self._concurrency else 0
            self._waiting += 1
        if position > 0 and queued:
            await queued(position)
        try:
            async with self._semaphore:
                async with self._lock:
                    self._waiting = max(0, self._waiting - 1)
                    self._active += 1
                    acquired = True
                context = JobContext(event, position)
                context.check_cancelled()
                return await work(context)
        finally:
            async with self._lock:
                if acquired and self._active:
                    self._active -= 1
                if self._events.get(user_id) is event:
                    self._events.pop(user_id, None)

    async def cancel(self, user_id: int) -> bool:
        async with self._lock:
            event = self._events.get(user_id)
            if not event:
                return False
            event.set()
            return True

    async def active(self, user_id: int) -> bool:
        async with self._lock:
            return user_id in self._events
