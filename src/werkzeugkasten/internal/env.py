import os
import re
from pathlib import Path

_PREFIX = "WERKZEUGKASTEN_"
_UUID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


def _environ(*keys: list[str], default: str | None = None, raise_on_missing: bool = False) -> str | None:
    expanded = [_PREFIX + k for k in keys] + keys
    if (value := next((os.environ[e].strip() for e in expanded if e in os.environ), default)) is None:
        if raise_on_missing:
            raise RuntimeError(f"Environment variable {next(expanded)} is not set.")
    return value


def uuid(value: str) -> str | None:
    if not value:
        return None
    if match := _UUID_RE.search(value or ""):
        raw = match.group(1).replace("-", "").lower()
        return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"
    raise ValueError(f"Invalid UUID: {value}")


cache_location = Path(_environ("CACHE_LOCATION", default="~/.cache/werkzeugkasten/content_cache.sqlite3")).resolve()
jina_api_key = _environ("JINA_API_KEY", "JINA_API_TOKEN")
lookup_model = _environ("LOOKUP_MODEL", default="gpt-5.4")
n_threads = int(_environ("N_THREADS", default="8"))
notion_api_token = _environ("NOTION_API_TOKEN", "NOTION_TOKEN")
notion_parent_page = uuid(_environ("NOTION_PARENT_PAGE"))
open_meteo_api_key = _environ("OPEN_METEO_API_KEY")
openai_api_key = _environ("OPENAI_API_KEY", raise_on_missing=True)
primary_language = _environ("PRIMARY_LANGUAGE", default="German")
research_model = _environ("RESEARCH_MODEL", default="gpt-5.4")
summary_model = _environ("SUMMARY_MODEL", default="gpt-5.4")
url_timeout = int(_environ("URL_TIMEOUT", default="10"))
