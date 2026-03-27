from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

from .env import cache_location


class LocalCache:
    def __init__(self):
        with sqlite3.connect(cache_location) as conn:
            conn.execute(f"CREATE TABLE IF NOT EXISTS content (k TEXT PRIMARY KEY, v TEXT)")

    def __getitem__(self, k: Any, /) -> str | None:
        if not (key := self._cache_key(k)) is None:
            with sqlite3.connect(cache_location) as conn:
                result = conn.execute(f"SELECT v FROM content WHERE k = ?", (key,)).fetchone()
                if result is None:
                    return None
                else:
                    return result[0]

    def __setitem__(self, k: Any, v: str, /):
        if not (key := self._cache_key(k)) is None:
            with sqlite3.connect(cache_location) as conn:
                conn.execute(f"INSERT OR REPLACE INTO content (k, v) VALUES (?, ?)", (key, v))

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
