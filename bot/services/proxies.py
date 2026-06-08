from __future__ import annotations

from itertools import cycle
from pathlib import Path
from threading import Lock


class ProxyProvider:
    def __init__(
        self,
        proxies: tuple[str, ...] = (),
        *,
        proxy_file: Path | None = None,
    ) -> None:
        loaded = list(proxies)
        if proxy_file and proxy_file.exists():
            loaded.extend(
                line.strip()
                for line in proxy_file.read_text().splitlines()
                if line.strip() and not line.startswith("#")
            )
        self._items = tuple(dict.fromkeys(loaded))
        self._cycle = cycle(self._items) if self._items else None
        self._lock = Lock()

    @property
    def enabled(self) -> bool:
        return bool(self._items)

    def next_proxy(self) -> str | None:
        if not self._cycle:
            return None
        with self._lock:
            return next(self._cycle)
