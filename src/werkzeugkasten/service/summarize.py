from __future__ import annotations

import io
import tempfile
from pathlib import Path
from typing import Any

from ..internal import Source
from ..internal.content import get_content
from ..internal.env import primary_language, summary_model
from ..internal.openai import query

MAX_SUMMARY_INPUT = 120_000
DOWNLOADED_SOURCE_DIR = Path(tempfile.gettempdir()) / "werkzeugkasten-source-downloads"


def _prompt_languages_instruction() -> str:
    if primary_language == "English":
        return f"Always produce the summary in English. Translate to English if necessary."
    return f"If the text is in {primary_language}, produce the summary in that same language. Otherwise, produce the summary in English."


def _prompt_summarize(content: str, /, filename: str | None = None, timestamp: str | None = None) -> str:
    prompt_languages_instruction = _prompt_languages_instruction()

    input_heading = "# Input" if bool(filename or timestamp) else ""
    filename = f"Filename: {filename}" if filename else ""
    timestamp = f"Timestamp: {timestamp}" if timestamp else ""

    return f"""Summarise this file in Markdown.
{prompt_languages_instruction}
For all other languages, produce the summary in English.

Return exactly these sections:

# Summary
Very brief bullet point summary of the file. Never more than necessary. If there is only one important thing, just say that. Follow the MECE (Mutually Exclusive, Collectively Exhaustive) Framework.

# Key details
Important facts, decisions, names, dates, methods, or structure. If there are any contrasting opinions, make those explicit. Follow the MECE Framework.

# Open questions
Anything unclear, missing, or worth checking.

{input_heading}
{filename}
{timestamp}

Document content:
{content}
"""


def _truncate_for_upload(prompt: str, limit: int = MAX_SUMMARY_INPUT) -> str:
    if len(prompt) <= limit:
        return prompt
    return prompt[:limit] + "\n\n[Truncated before upload]"


def _text_to_source(text: str) -> io.BytesIO:
    return io.BytesIO(text.encode("utf-8"))


def summarize(sources: list[Source] | str, /) -> dict[str, Any]:
    if isinstance(sources, str):
        sources = [_text_to_source(sources)]
    content = get_content(sources)
    safe_content = _truncate_for_upload(content)
    summary = query(
        _prompt_summarize(safe_content),
        model=summary_model,
    )
    return {
        "summary": summary.text,
        "content": content,
        "token_count": summary.response.usage.total_tokens,
        "input_tokens": summary.response.usage.input_tokens,
        "output_tokens": summary.response.usage.output_tokens,
        "sources": summary.response.tool_choice.to_json() if summary.response.tool_choice else None,
    }
