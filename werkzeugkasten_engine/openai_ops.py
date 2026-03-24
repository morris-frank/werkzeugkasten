from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from openai import OpenAI

from .core import DEFAULT_RESEARCH_MODEL, DEFAULT_SUMMARY_MODEL, DEFAULT_SUMMARY_MIRROR_LANGUAGES
from .core import RESEARCH_MODEL_ENV, SUMMARY_MIRROR_LANGUAGES_ENV, SUMMARY_MODEL_ENV

__all__ = [
    "current_timezone",
    "extract_web_search_sources",
    "openai_client",
    "reasoning_for_model",
    "research_model",
    "response_create_kwargs",
    "summary_mirror_languages",
    "summary_model",
    "web_search_tool",
]


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


def summary_mirror_languages() -> list[str]:
    raw = os.environ.get(SUMMARY_MIRROR_LANGUAGES_ENV, DEFAULT_SUMMARY_MIRROR_LANGUAGES)
    parts = [part.strip() for part in raw.split(",")]
    languages = [part for part in parts if part]
    if languages:
        return languages
    return [part.strip() for part in DEFAULT_SUMMARY_MIRROR_LANGUAGES.split(",") if part.strip()]


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


def extract_web_search_sources(response: Any) -> list[str]:
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
