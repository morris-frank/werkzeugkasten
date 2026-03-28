import io
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Union

import requests

_DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "werkzeugkasten"
_MAX_SLUG_LENGTH = 48

Source = Union[str, requests.Response, Path, BinaryIO]


def sources_to_urls(sources: list[Source]) -> list[str]:
    return list(sorted(set(source_to_url(source) for source in sources)))


def source_to_url(source: Source) -> str:
    if isinstance(source, str):
        return source
    if isinstance(source, requests.Response):
        return source.url
    if isinstance(source, Path):
        return source.as_posix()
    return source.name


def text_to_source(text: str) -> Source:
    return io.BytesIO(text.encode("utf-8"))


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug[:_MAX_SLUG_LENGTH].rstrip("-")
    return slug or "research"


def choose_output_path(
    started_at: datetime,
    label: str,
    explicit_path: str | Path | None = None,
) -> Path:
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate
    destination = _DEFAULT_OUTPUT_DIR.expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    base_name = f"{started_at.strftime('%Y-%m-%d_%H-%M')}-{_slugify(label)}"
    candidate = destination / f"{base_name}.md"
    suffix = 2
    while candidate.exists():
        candidate = destination / f"{base_name}-{suffix}.md"
        suffix += 1
    return candidate


def read_json_stdin() -> dict[str, Any]:
    payload = sys_stdin_text()
    if not payload.strip():
        raise ValueError("Expected JSON payload on stdin.")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    return data


def sys_stdin_text() -> str:
    import sys

    return sys.stdin.read()
