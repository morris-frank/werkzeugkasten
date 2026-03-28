from __future__ import annotations

import io

from ..internal import Source, sources_to_urls
from ..internal.content import get_content
from ..internal.env import E, E_int
from ..internal.openai import query
from .models import SummarizeSourcesResponse


def _prompt_languages_instruction() -> str:
    if E["primary_language"] == "English":
        return f"Always produce the summary in English. Translate to English if necessary."
    return (
        f"If the text is in {E["primary_language"]}, produce the summary in that same language. Otherwise, produce the summary in English."
    )


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


def _truncate_for_upload(prompt: str, limit: int | None = None) -> str:
    limit = limit or E_int["MAX_SUMMARY_INPUT", 120_000]
    if len(prompt) <= limit:
        return prompt
    return prompt[:limit] + "\n\n[Truncated before upload]"


def _text_to_source(text: str) -> io.BytesIO:
    return io.BytesIO(text.encode("utf-8"))


def summarize_sources(sources: list[Source] | str, /) -> SummarizeSourcesResponse:
    if isinstance(sources, str):
        sources = [_text_to_source(sources)]
    content = get_content(sources)
    safe_content = _truncate_for_upload(content)
    queryResponse = query(
        _prompt_summarize(safe_content),
        model=E["summary_model"],
    )

    return SummarizeSourcesResponse(
        summary=queryResponse.text,
        content=content,
        token_count=queryResponse.response.usage.total_tokens,
        input_tokens=queryResponse.response.usage.input_tokens,
        output_tokens=queryResponse.response.usage.output_tokens,
    )
