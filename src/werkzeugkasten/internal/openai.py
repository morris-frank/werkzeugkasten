from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from openai import OpenAI
from openai.types.responses import Response

from ..service.models import QueryResponse, QueryUsage
from .env import E, E_bool, E_req


def _mock_text(prompt_text: str) -> str:
    if "Return exactly these sections:" in prompt_text:
        body = prompt_text.split("Document content:", 1)[-1].strip()
        preview = body[:280] + ("..." if len(body) > 280 else "")
        return "\n".join(
            [
                "# Summary",
                "",
                "- Mock summary.",
                "",
                "# Key details",
                "",
                f"- {preview or 'No content.'}",
                "",
                "# Open questions",
                "",
                "- None.",
            ]
        )

    if '"updates": {' in prompt_text:
        key_match = re.search(r"Object type: .*?\n[^\n:]+:\s*(.+)\n", prompt_text, re.DOTALL)
        key = key_match.group(1).strip() if key_match else ""
        missing_match = re.search(r"Missing fields to fill:\n(.*?)\n\nReturn JSON only", prompt_text, re.DOTALL)
        updates: dict[str, str] = {}
        if missing_match:
            for line in missing_match.group(1).splitlines():
                line = line.strip()
                if not line.startswith("- "):
                    continue
                column = line[2:].split(" [", 1)[0].strip()
                if column:
                    updates[column] = ""
        return json.dumps({"key": key, "updates": updates}, ensure_ascii=False)

    if '"tags": [' in prompt_text and '"assignments": {' in prompt_text:
        return json.dumps({"tags": [], "assignments": {}}, ensure_ascii=False)

    if '"neighbors": {' in prompt_text:
        return json.dumps({"neighbors": {}}, ensure_ascii=False)

    return ""


def _web_search_tool() -> dict[str, Any]:
    tzinfo = datetime.now().astimezone().tzinfo
    timezone = tzinfo.key if hasattr(tzinfo, "key") else str(tzinfo)
    return {
        "type": "web_search",
        "search_context_size": E["web_search_context_size", "medium"],
        "user_location": {
            "type": "approximate",
            "timezone": timezone,
        },
    }


def _reasoning_for_model(model: str, *, decreased_effort: bool = False) -> dict[str, Any] | None:
    normalized = model.strip().lower()
    if normalized.startswith("gpt-5"):
        return {"effort": "medium" if not decreased_effort else "low"}
    return None


def _extract_sources(response: Response) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for output in getattr(response, "output", []) or []:
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


def query(
    prompt_text: str,
    /,
    model: str,
    *,
    use_web_search: bool = False,
    include_web_sources: bool = False,
    decreased_effort: bool = False,
) -> QueryResponse:
    if E_bool["mock"]:
        text = _mock_text(prompt_text)
        return QueryResponse(
            text=text,
            sources=[],
            usage=QueryUsage(
                number_queries=1,
                token_count=len(prompt_text.split()) + len(text.split()),
                input_tokens=len(prompt_text.split()),
                output_tokens=len(text.split()),
            ),
        )

    response = OpenAI(api_key=E_req["openai_api_key"]).responses.create(
        input=prompt_text,
        model=model,
        reasoning=_reasoning_for_model(model, decreased_effort=decreased_effort),
        tools=[_web_search_tool()] if use_web_search else None,
        include=["web_search_call.action.sources"] if include_web_sources else None,
    )

    sources = _extract_sources(response)
    usage = QueryUsage(
        number_queries=1,
        token_count=response.usage.total_tokens,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
    )
    return QueryResponse(text=response.output_text, sources=sources, usage=usage)
