from __future__ import annotations

import json
import os
from dataclasses import dataclass

from ..internal.env import lookup_model
from ..internal.openai import query
from ..internal.value import as_object_type, maybe_question


@dataclass(frozen=True)
class LookupAnswer:
    data: dict[str, str]
    text: str
    sources: list[str]
    error: str | None = None


def _prompt_make_explicit_question(header: str, key: str, object_type: str) -> str:
    return maybe_question(header) or f"What is the {header} of the {object_type} {key}?"


def _prompt_lookup(
    key_header: str,
    key: str,
    row: dict[str, str],
    missing_columns: list[str],
    question_columns: set[str],
) -> str:
    object_type = as_object_type(key_header)
    known_values = [f"- {column}: {value}" for column, value in row.items() if column != key_header and str(value).strip()]
    missing_lines: list[str] = []
    for column in missing_columns:
        if column in question_columns:
            prompt = _prompt_make_explicit_question(column, key, object_type)
            missing_lines.append(f"- {column} [question]: {prompt}")
        else:
            missing_lines.append(f"- {column} [attribute]: fill with a short tag or very short value only")
    known_section = "\n".join(known_values) if known_values else "- none"
    missing_section = "\n".join(missing_lines) if missing_lines else "- none"
    return f"""Research this {object_type} using web search and fill the missing table fields.

Key column: {key_header}
Object type: {object_type}
{key_header}: {key}

Known row values:
{known_section}

Missing fields to fill:
{missing_section}

Return JSON only in this shape:
{{
  "key": "{key}",
  "updates": {{
    "column name": "value"
  }}
}}

Rules:
- Only include columns from the missing fields list.
- For question fields, answer directly in one short factual sentence.
- For attribute fields, return the shortest practical tag or short value.
- If you cannot find a reliable value, use an empty string.
- No markdown code fences.
- No extra keys.
"""


def lookup_row(
    row: dict[str, str],
    key_header: str,
    missing_columns: list[str],
    question_columns: set[str],
) -> LookupAnswer:
    key = row.get(key_header, "").strip() or "[blank]"

    answer = query(_prompt_lookup(key_header, key, row, missing_columns, question_columns), model=lookup_model)

    try:
        data = answer.json
        if data.get("key") != key:
            raise ValueError("Response key does not match request.")
        updates = data.get("updates")
        if not isinstance(updates, dict):
            raise ValueError("Response updates are missing.")
        normalized = {str(column): str(value or "").strip() for column, value in updates.items() if column in missing_columns}
        return LookupAnswer(data=normalized, text=answer.text, sources=answer.sources)
    except (json.JSONDecodeError, ValueError) as exc:
        return LookupAnswer(data={}, text=answer.text, sources=[], error=f"Structured validation failed: {exc}")
