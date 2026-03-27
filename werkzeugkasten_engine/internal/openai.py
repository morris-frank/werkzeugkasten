from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from openai import OpenAI, Response

from werkzeugkasten_engine.internal.value import as_json


@dataclass(True)
class QueryAnswer:
    text: str
    response: Response

    def from_response(self, response: Response) -> QueryAnswer:
        return QueryAnswer(text=(response.output_text or "").strip(), response=response)

    @property
    def json(self) -> dict[str, Any]:
        return as_json(self.text)

    @property
    def sources(self) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for output in getattr(self.response, "output", []) or []:
            if getattr(output, "type", None) != "web_search_call":
                continue
            action = getattr(output, "action", None)
            if action is None and isinstance(output, dict):
                action = output.get("action")
            sources = getattr(action, "sources", None)
            if sources is None and isinstance(action, dict):
                sources = action.get("sources")
            for source in sources or []:
                url = getattr(source, "url", None)
                if url is None and isinstance(source, dict):
                    url = source.get("url")
                url = str(url or "").strip()
                if url and url not in seen:
                    seen.add(url)
                    urls.append(url)
        return urls


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
    resolved_key = (api_key or os.environ.get("OPENAI_API_KEY", "")).strip()
    if not resolved_key:
        raise RuntimeError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=resolved_key)


def _reasoning_for_model(model: str, *, decreased_effort: bool = False) -> dict[str, Any] | None:
    normalized = model.strip().lower()
    if normalized.startswith("gpt-5"):
        return {"effort": "medium" if not decreased_effort else "low"}
    return None


def query(
    prompt_text: str,
    /,
    model: str,
    *,
    use_web_search: bool = False,
    include_web_sources: bool = False,
    decreased_effort: bool = False,
) -> QueryAnswer:
    response = _openai_client().responses.create(
        input=prompt_text,
        model=model,
        reasoning=_reasoning_for_model(model, decreased_effort=decreased_effort),
        tools=[_web_search_tool()] if use_web_search else None,
        include=["web_search_call.action.sources"] if include_web_sources else None,
    )
    return QueryAnswer.from_response(response)
