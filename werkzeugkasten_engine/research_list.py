from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from .core import (
    choose_output_path,
    esc,
    extract_json_block,
    extract_sources,
    openai_client,
    research_model,
    web_search_tool,
)

ProgressCallback = Callable[[int, int, str], None]


@dataclass
class Result:
    item: str
    answer: str = ""
    raw_text: str = ""
    sources: list[str] = field(default_factory=list)
    error: str = ""


def parse_items(raw: str) -> list[str]:
    items: list[str] = []
    for line in raw.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        cleaned = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", cleaned).strip()
        if not cleaned or not re.search(r"\w", cleaned):
            continue
        items.append(cleaned)
    return items


def build_prompt(item: str, question: str) -> str:
    return f"""Research this item using web search and answer the question.

Item: {item}
Question: {question}

Return JSON only, with exactly these keys:
- item
- question
- answer

Rules:
- Keep answer factual and concise.
- Prefer 1 short paragraph, max 80 words.
- If reliable public information is limited, say that plainly.
- No markdown code fences.
- No extra keys.
"""


def _validated_answer(data: dict[str, object], item: str, question: str) -> str:
    if data.get("item") != item:
        raise ValueError("Response item does not match request.")
    if data.get("question") != question:
        raise ValueError("Response question does not match request.")
    answer = data.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        raise ValueError("Response answer is missing.")
    return answer.strip()


def research_item(item: str, question: str) -> Result:
    client = openai_client()
    response = client.responses.create(
        model=research_model(),
        include=["web_search_call.action.sources"],
        tools=[web_search_tool()],
        input=build_prompt(item, question),
    )
    raw_text = (response.output_text or "").strip()
    sources = extract_sources(response)

    try:
        data = json.loads(extract_json_block(raw_text))
        answer = _validated_answer(data, item, question)
        return Result(item=item, answer=answer, raw_text=raw_text, sources=sources)
    except (json.JSONDecodeError, ValueError) as exc:
        return Result(
            item=item,
            raw_text=raw_text or "[No text returned]",
            sources=sources,
            error=f"Structured validation failed: {exc}",
        )


def render_markdown(question: str, items: list[str], started_at: datetime, results: list[Result]) -> str:
    completed = len(results)
    table_ok = completed > 0 and all(result.answer for result in results)
    lines = [
        "# AI Research",
        "",
        f"- Generated: {started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- Question: {question}",
        f"- Progress: {completed}/{len(items)}",
        "",
        "## Items",
    ]
    lines.extend(f"- {item}" for item in items)
    lines.extend(["", "## Results", ""])

    if table_ok:
        lines.extend(["| Item | Response |", "| --- | --- |"])
        for result in results:
            lines.append(f"| {esc(result.item)} | {esc(result.answer)} |")
    elif results:
        for result in results:
            lines.extend([f"### {result.item}", ""])
            lines.append(result.answer or result.raw_text or result.error or "No response.")
            if result.error:
                lines.extend(["", f"_Note: {result.error}_"])
            if result.sources:
                lines.extend(["", "Sources:"])
                lines.extend(f"- {url}" for url in result.sources[:5])
            lines.append("")
    else:
        lines.extend(["No responses yet.", ""])

    if completed < len(items):
        lines.extend(["## Pending", ""])
        lines.extend(f"- {item}" for item in items[completed:])
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def write_output(path: Path, question: str, items: list[str], started_at: datetime, results: list[Result]) -> None:
    path.write_text(render_markdown(question, items, started_at, results), encoding="utf-8")


def run_research_list(
    items: list[str],
    question: str,
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    normalized_items = [item for item in items if item.strip()]
    if not normalized_items:
        raise ValueError("No valid items found.")
    normalized_question = question.strip()
    if not normalized_question:
        raise ValueError("Question cannot be empty.")

    started_at = datetime.now().astimezone()
    output_path = choose_output_path(started_at, normalized_question, output_dir)
    results: list[Result] = []
    write_output(output_path, normalized_question, normalized_items, started_at, results)

    for index, item in enumerate(normalized_items, start=1):
        if progress:
            progress(index - 1, len(normalized_items), item)
        try:
            result = research_item(item, normalized_question)
        except Exception as exc:
            result = Result(item=item, error=str(exc), raw_text=f"[Request failed] {exc}")
        results.append(result)
        write_output(output_path, normalized_question, normalized_items, started_at, results)
        if progress:
            progress(index, len(normalized_items), item)

    return {
        "output_path": str(output_path),
        "item_count": len(normalized_items),
        "completed_count": len(results),
    }


def run_self_tests() -> None:
    assert parse_items("- Apple\n- Banana\n- Cherry") == ["Apple", "Banana", "Cherry"]
    assert parse_items("1. Apple\n2. Banana\n3. Cherry") == ["Apple", "Banana", "Cherry"]
    assert parse_items("- Apple\n\n-  \n* Banana\n---\n+ Cherry") == ["Apple", "Banana", "Cherry"]
    assert parse_items("  - Acme Inc  \n  2) Beta BV  ") == ["Acme Inc", "Beta BV"]
    assert parse_items("- C++\n- A+\n- AT&T") == ["C++", "A+", "AT&T"]
