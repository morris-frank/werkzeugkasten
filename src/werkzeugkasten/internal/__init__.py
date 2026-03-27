import io
import json
import re
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, BinaryIO, Union

import requests

from .content import get_content

_DEFAULT_OUTPUT_DIR = Path.home() / "Desktop" / "werkzeugkasten"
_MAX_SLUG_LENGTH = 48

Source = Union[str, requests.Response, Path, BinaryIO]


def text_to_source(text: str) -> Source:
    return io.BytesIO(text.encode("utf-8"))


def group_sources_by_domain(sources: list[Source], /) -> tuple[dict[str, list[Source]], list[Source]]:
    grouped: dict[str, list[Source]] = {}
    ungrouped: list[Source] = []
    for source in sources:
        domain = urllib.parse.urlparse(source).netloc
        if domain:
            grouped.setdefault(domain, []).append(source)
        else:
            ungrouped.append(source)
    return grouped, ungrouped


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug[:_MAX_SLUG_LENGTH].rstrip("-")
    return slug or "research"


def choose_output_path(
    started_at: datetime,
    label: str,
    output_dir: Path | None = None,
    explicit_path: str | Path | None = None,
) -> Path:
    if explicit_path:
        candidate = Path(explicit_path).expanduser()
        candidate.parent.mkdir(parents=True, exist_ok=True)
        return candidate
    destination = (output_dir or _DEFAULT_OUTPUT_DIR).expanduser()
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
