from __future__ import annotations

import asyncio
import sqlite3
import threading
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from .env import E_path


class __Cache:
    def __init__(self) -> None:
        self._init_lock = threading.Lock()
        self._ready = threading.Event()

    def _sync_init(self) -> None:
        E_path["cache_location"].parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(E_path["cache_location"]) as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS content (k TEXT PRIMARY KEY, v TEXT)")

    def _wait_ready(self) -> None:
        if self._ready.is_set():
            return
        with self._init_lock:
            if self._ready.is_set():
                return
            self._sync_init()
            self._ready.set()

    async def initialize(self) -> None:
        await asyncio.to_thread(self._wait_ready)

    def __getitem__(self, k: Any, /) -> str | None:
        self._wait_ready()
        if not (key := self._cache_key(k)) is None:
            with sqlite3.connect(E_path["cache_location"]) as conn:
                result = conn.execute("SELECT v FROM content WHERE k = ?", (key,)).fetchone()
                if result is None:
                    return None
                else:
                    return result[0]

    def __setitem__(self, k: Any, v: str, /) -> None:
        self._wait_ready()
        if not (key := self._cache_key(k)) is None:
            with sqlite3.connect(E_path["cache_location"]) as conn:
                conn.execute("INSERT OR REPLACE INTO content (k, v) VALUES (?, ?)", (key, v))

    def _cache_key(self, k: Any, /) -> str | None:
        key: str | None = None
        if isinstance(k, Path):
            key = str(k.resolve())
        elif isinstance(k, str):
            k = k.strip()
            if k.startswith("file:"):
                key = str(Path.from_uri(k).resolve())
            elif (parts := urlsplit(k)).scheme in {"http", "https"}:
                key = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))
            else:
                key = str(Path(unquote(k)).expanduser().resolve())
        return key


cache = __Cache()
