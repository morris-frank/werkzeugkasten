from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from openai import OpenAI

DEFAULT_OUTPUT_DIR = Path.home() / "Desktop"
DEFAULT_INTERPRETER_PATH = "/Users/mfr/mamba/envs/basic/bin/python"
MAX_SLUG_LENGTH = 48
RESEARCH_MODEL_ENV = "WERKZEUGKASTEN_RESEARCH_MODEL"
SUMMARY_MODEL_ENV = "WERKZEUGKASTEN_SUMMARY_MODEL"
JINA_API_KEY_ENV = "WERKZEUGKASTEN_JINA_API_KEY"
DEFAULT_RESEARCH_MODEL = "gpt-5.4"
DEFAULT_SUMMARY_MODEL = "gpt-5.4"


def current_timezone() -> str:
    tzinfo = datetime.now().astimezone().tzinfo
    return tzinfo.key if hasattr(tzinfo, "key") else str(tzinfo)


def web_search_tool() -> dict[str, Any]:
    return {
        "type": "web_search",
        "search_context_size": "medium",
        "user_location": {
            "type": "approximate",
            "timezone": current_timezone(),
        },
    }


def openai_client(api_key: str | None = None) -> OpenAI:
    resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not resolved_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=resolved_key)


def research_model() -> str:
    return os.environ.get(RESEARCH_MODEL_ENV, DEFAULT_RESEARCH_MODEL)


def summary_model() -> str:
    return os.environ.get(SUMMARY_MODEL_ENV, DEFAULT_SUMMARY_MODEL)


def jina_api_key() -> str:
    return os.environ.get(JINA_API_KEY_ENV, "") or os.environ.get("JINA_API_KEY", "") or os.environ.get("JINA_API_TOKEN", "")


def reasoning_for_model(model: str) -> dict[str, Any] | None:
    normalized = model.strip().lower()
    if normalized.startswith("gpt-5"):
        return {"effort": "medium"}
    return None


def response_create_kwargs(
    model: str,
    *,
    use_web_search: bool = False,
    include_web_sources: bool = False,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model}
    reasoning = reasoning_for_model(model)
    if reasoning is not None:
        kwargs["reasoning"] = reasoning
    if use_web_search:
        kwargs["tools"] = [web_search_tool()]
    if include_web_sources:
        kwargs["include"] = ["web_search_call.action.sources"]
    return kwargs


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    slug = slug[:MAX_SLUG_LENGTH].rstrip("-")
    return slug or "research"


def choose_output_path(started_at: datetime, label: str, output_dir: Path | None = None) -> Path:
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
    return text.replace("|", "\\|").replace("\n", "<br>").strip()


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


def extract_sources(response: Any) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for output in getattr(response, "output", []):
        if getattr(output, "type", None) != "web_search_call":
            continue
        action = getattr(output, "action", None)
        for source in getattr(action, "sources", None) or []:
            url = getattr(source, "url", "").strip()
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


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
