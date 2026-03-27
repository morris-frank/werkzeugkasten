from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from openai import OpenAI

from werkzeugkasten_engine.internal.value import as_json


def _current_timezone() -> str:
    tzinfo = datetime.now().astimezone().tzinfo
    return tzinfo.key if hasattr(tzinfo, "key") else str(tzinfo)


def _web_search_tool() -> dict[str, Any]:
    return {
        "type": "web_search",
        "search_context_size": "medium",
        "user_location": {
            "type": "approximate",
            "timezone": _current_timezone(),
        },
    }


def _openai_client(api_key: str | None = None) -> OpenAI:
    resolved_key = api_key or os.environ.get("OPENAI_API_KEY")
    if not resolved_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=resolved_key)


def _reasoning_for_model(model: str) -> dict[str, Any] | None:
    normalized = model.strip().lower()
    if normalized.startswith("gpt-5"):
        return {"effort": "medium"}
    return None



def prompt(
    prompt_text: str,
    /
        model: str,
    *,
    use_web_search: bool = False,
    include_web_sources: bool = False,
):
    kwargs: dict[str, Any] = {"model": model}
    reasoning = _reasoning_for_model(model)

    if reasoning is not None:
        kwargs["reasoning"] = reasoning
    if use_web_search:
        kwargs["tools"] = [_web_search_tool()]
    if include_web_sources:
        kwargs["include"] = ["web_search_call.action.sources"]


    response = _openai_client().responses.create(
        prompt_text,
        **kwargs
    )

    data = as_json(response.output_text)


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
