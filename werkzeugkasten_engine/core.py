from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_OUTPUT_DIR = Path.home() / "Desktop"
DEFAULT_INTERPRETER_PATH = "/Users/mfr/mamba/envs/basic/bin/python"
MAX_SLUG_LENGTH = 48
RESEARCH_MODEL_ENV = "WERKZEUGKASTEN_RESEARCH_MODEL"
SUMMARY_MODEL_ENV = "WERKZEUGKASTEN_SUMMARY_MODEL"
SUMMARY_MIRROR_LANGUAGES_ENV = "WERKZEUGKASTEN_SUMMARY_MIRROR_LANGUAGES"
JINA_API_KEY_ENV = "WERKZEUGKASTEN_JINA_API_KEY"
NOTION_API_TOKEN_ENV = "WERKZEUGKASTEN_NOTION_API_TOKEN"
NOTION_PARENT_PAGE_ENV = "WERKZEUGKASTEN_NOTION_PARENT_PAGE"
OPEN_METEO_API_KEY_ENV = "WERKZEUGKASTEN_OPEN_METEO_API_KEY"
DEFAULT_RESEARCH_MODEL = "gpt-5.4"
DEFAULT_SUMMARY_MODEL = "gpt-5.4"
DEFAULT_SUMMARY_MIRROR_LANGUAGES = "English,German"
LATEST_NOTION_VERSION = "2026-03-11"


def jina_api_key() -> str:
    return os.environ.get(JINA_API_KEY_ENV, "") or os.environ.get("JINA_API_KEY", "") or os.environ.get("JINA_API_TOKEN", "")


def notion_api_token() -> str:
    return os.environ.get(NOTION_API_TOKEN_ENV, "") or os.environ.get("NOTION_API_TOKEN", "") or os.environ.get("NOTION_TOKEN", "")


def notion_parent_page() -> str:
    return os.environ.get(NOTION_PARENT_PAGE_ENV, "") or os.environ.get("NOTION_PARENT_PAGE", "")


def open_meteo_api_key() -> str:
    return os.environ.get(OPEN_METEO_API_KEY_ENV, "") or os.environ.get("OPEN_METEO_API_KEY", "")


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug[:MAX_SLUG_LENGTH].rstrip("-")
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
    destination = (output_dir or DEFAULT_OUTPUT_DIR).expanduser()
    destination.mkdir(parents=True, exist_ok=True)
    base_name = f"{started_at.strftime('%Y-%m-%d_%H-%M')}-{slugify(label)}"
    candidate = destination / f"{base_name}.md"
    suffix = 2
    while candidate.exists():
        candidate = destination / f"{base_name}-{suffix}.md"
        suffix += 1
    return candidate


def esc(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", ", ").strip()


def extract_json_block(text: str) -> str:
    candidate = text.strip()
    if candidate.startswith("```"):
        lines = candidate.splitlines()
        if len(lines) >= 3:
            candidate = "\n".join(lines[1:-1]).strip()
    if candidate.startswith("{") and candidate.endswith("}"):
        return candidate
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and start < end:
        return candidate[start : end + 1]
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


from .openai_ops import (  # noqa: E402
    current_timezone,
    extract_web_search_sources as extract_sources,
    openai_client,
    reasoning_for_model,
    research_model,
    response_create_kwargs,
    summary_mirror_languages,
    summary_model,
    web_search_tool,
)
