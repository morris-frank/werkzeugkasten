from __future__ import annotations

import os
import sqlite3
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit


def _cache_location() -> Path:
    return os.environ.get("WERKZEUGKASTEN_CACHE_LOCATION", "") or "~/.cache/werkzeugkasten/content_cache.sqlite3"


class Cache(StrEnum):
    CONTENT = "content"


class LocalCache:
    def __init__(self, cache_type: Cache, /):
        self.cache_type = cache_type
        self.db_path = _cache_location()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(f"CREATE TABLE IF NOT EXISTS {self.cache_type} (k TEXT PRIMARY KEY, v TEXT)")

    def __getitem__(self, k: Any, /) -> str | None:
        if not (key := self._cache_key(k)) is None:
            with sqlite3.connect(self.db_path) as conn:
                result = conn.execute(f"SELECT v FROM {self.cache_type} WHERE k = ?", (key,)).fetchone()
                if result is None:
                    return None
                else:
                    return result[0]

    def __setitem__(self, k: Any, v: str, /):
        if not (key := self._cache_key(k)) is None:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(f"INSERT INTO {self.cache_type} (k, v) VALUES (?, ?)", (key, v))

    def _cache_key(self, k: Any, /) -> str | None:
        if isinstance(k, Path):
            key = str(k.resolve())
        if isinstance(k, str):
            k = k.strip()
            if k.startswith("file:"):
                key = str(Path.from_uri(k).resolve())
            parts = urlsplit(k)
            if parts.scheme in {"http", "https"}:
                key = urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))
            key = str(Path(unquote(k)).resolve())
        return key
