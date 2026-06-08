from __future__ import annotations

import time
from dataclasses import dataclass, field


def render_progress_bar(percent: float, *, width: int = 12) -> str:
    value = max(0, min(100, int(percent)))
    filled = round(width * value / 100)
    return "█" * filled + "░" * (width - filled)


def progress_text(percent: float, stage: str = "Yuklanmoqda") -> str:
    value = max(0, min(100, int(percent)))
    return f"📥 {stage}: [{render_progress_bar(value)}] {value}%"


@dataclass(slots=True)
class ThrottledProgress:
    interval_seconds: int = 3
    last_sent_at: float = field(default=0.0)
    last_percent: int = field(default=-1)

    def should_send(self, percent: float) -> bool:
        now = time.monotonic()
        value = int(percent)
        if value >= 100 or value == 0:
            self.last_sent_at = now
            self.last_percent = value
            return True
        if value == self.last_percent:
            return False
        if now - self.last_sent_at < self.interval_seconds:
            return False
        self.last_sent_at = now
        self.last_percent = value
        return True
