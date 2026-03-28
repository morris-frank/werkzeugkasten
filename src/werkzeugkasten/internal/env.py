import os
import re
from pathlib import Path
from typing import Any

_PREFIX = "WERKZEUGKASTEN_"
_UUID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


class E:
    __defaults__ = {
        "cache_location": Path("~/.cache/werkzeugkasten/content_cache.sqlite3").resolve(),
        "mock": False,
        "n_threads": 8,
        "primary_language": "German",
        "lookup_model": "gpt-5.4",
        "research_model": "gpt-5.4",
        "summary_model": "gpt-5.4",
        "source_column": "Sources",
        "source_summary_column": "Source Summary",
        "tags_column": "Tags",
        "notion_request_body_safe_max_bytes": 420_000,
    }

    @classmethod
    def update(cls, kwargs: dict[str, Any]) -> None:
        cls.__defaults__.update(kwargs)

    def __class_getitem__(cls, item: tuple[str, Any] | str) -> str:
        key, default = item if isinstance(item, tuple) else (item, cls.__defaults__.get(item, ""))
        for ckey in map(str.upper, [_PREFIX + key, key]):
            if ckey in os.environ:
                return os.environ[ckey].strip()
        else:
            return str(default)


class E_req:
    def __class_getitem__(cls, key: str, /) -> str:
        if e := E[key]:
            return e
        raise RuntimeError(f"Environment variable {_PREFIX + key.upper()} or {key.upper()} is not set.")


class E_int:
    def __class_getitem__(cls, item: tuple[str, int] | str) -> int:
        return int(E[item])


# TODO: Connect to .value for bool parsing
class E_bool:
    def __class_getitem__(cls, item: tuple[str, bool] | str) -> bool:
        return E[item].lower() in {"1", "true", "yes", "on", "y"}


# TODO: Connect to .value for UUID parsing
class E_uuid:
    def __class_getitem__(cls, item: tuple[str, str] | str) -> str:
        if e := E[item]:
            if match := _UUID_RE.search(e):
                uuid = match.group(1).replace("-", "").lower()
                return f"{uuid[0:8]}-{uuid[8:12]}-{uuid[12:16]}-{uuid[16:20]}-{uuid[20:32]}"
            raise ValueError(f"Invalid UUID: {e}")
        return e


class E_path:
    def __class_getitem__(cls, item: tuple[str, Path] | str) -> Path:
        return Path(E[item])
