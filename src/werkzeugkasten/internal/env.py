import os
import re
from pathlib import Path

_PREFIX = "WERKZEUGKASTEN_"
_UUID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def _environ(*ks: str, default: str | None = None, raise_on_missing: bool = False) -> str | None:
    expanded = [_PREFIX + k for k in ks] + list(ks)
    if (value := next((os.environ[e].strip() for e in expanded if e in os.environ), default)) is None:
        if raise_on_missing:
            raise RuntimeError(f"Environment variable {expanded[0]} is not set.")
    return value


def uuid(value: str) -> str | None:
    if not value:
        return None
    if match := _UUID_RE.search(value or ""):
        raw = match.group(1).replace("-", "").lower()
        return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    raise ValueError(f"Invalid UUID: {value}")


def boolean(value: str) -> bool:
    return value.lower() in {"1", "true", "yes", "on"}


cache_location = lambda: Path(_environ("cache_location", default="~/.cache/werkzeugkasten/content_cache.sqlite3")).resolve()
jina_api_key = lambda: _environ("jina_api_key", "JINA_API_TOKEN")
lookup_model = lambda: _environ("lookup_model", default="gpt-5.4")
mock_enabled = lambda: boolean(_environ("mock", default=""))
n_threads = lambda: int(_environ("n_threads", default="8"))
notion_api_token = lambda: _environ("notion_api_token", "NOTION_TOKEN")
notion_parent_page = lambda: uuid(_environ("notion_parent_page"))
open_meteo_api_key = lambda: _environ("open_meteo_api_key")
openai_api_key = lambda: _environ("openai_api_key", raise_on_missing=True) or ""
primary_language = lambda: _environ("primary_language", default="German")
research_model = lambda: _environ("research_model", default="gpt-5.4")
summary_model = lambda: _environ("summary_model", default="gpt-5.4")
url_timeout = lambda: int(_environ("url_timeout", default="10"))
