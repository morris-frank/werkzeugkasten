from __future__ import annotations

import json
from typing import Any

from ..internal.env import E_req
from ..internal.openai import query
from ..internal.value import as_object_type, fuzz_equals, is_empty, maybe_question, unwrap_text
from .models import LookupObjectResponse
from .summarize import summarize_sources


def _prompt_lookup(
    props: dict[str, str],
    object_type: str,
    object_name: str,
) -> str:
    known = []
    missing = []
    for k, v in props.items():
        k, v = unwrap_text(k), unwrap_text(v)
        if k == object_type:
            continue
        if is_empty(v):
            if k_as_question := maybe_question(k):
                missing.append(f"- {k_as_question} [question]")
            else:
                missing.append(f"- {k} [attribute] : (What is the {k} of the {object_type} {object_name}?)")
        else:
            known.append(f"- {k} :  {v}")

    known = "\n".join(known) or "- none"
    missing = "\n".join(missing)
    if not missing:
        return ""
    return f"""Research {object_type} {object_name} using web search and fill the missing table fields.

Object type: {object_type}
{object_type}: {object_name}

Known fields:
{known}

Missing fields to fill:
{missing}

Return JSON only in this shape:
{{
  "{object_type}": "{object_name}",
  "updates": {{
    "column name": "value"
  }}
}}

Rules:
- Only include fields from the missing fields list.
- For question fields, answer directly in one short factual sentence.
- For attribute fields, return the shortest practical value or tag.
- If an attribute is a category, return the shortest practical tag.
- If you cannot find a reliable value, use an empty string.
- No markdown code fences.
- No extra fields.
"""


def lookup_object(
    props: dict[str, str],
    object_type: str | None = None,
    object_name: str | None = None,
    include_sources: bool = False,
    include_sources_summary: bool = False,
) -> LookupObjectResponse:
    object_type = as_object_type(object_type)
    object_name = object_name or "[blank]"

    queryResponse = query(
        _prompt_lookup(
            props,
            object_type,
            object_name,
        )
    )
    number_queries = 1
    usage = queryResponse.usage
    error = None

    data = {}
    researched_fields: set[str] = set()
    count_fields_researched = 0
    try:
        data = queryResponse.json
        if not fuzz_equals(data.get(object_type), object_name):
            raise ValueError("Response key does not match request.")
        updates = data.get("updates")
        if not isinstance(updates, dict):
            raise ValueError("Response updates are missing.")
        for k, v in updates.items():
            if k in props and is_empty(props[k]):
                data[k] = str(v)
                researched_fields.add(k)
                count_fields_researched += 1
    except (json.JSONDecodeError, ValueError) as exc:
        error = f"Structured validation failed: {exc}"
        pass

    if include_sources:
        data[E_req["source_column"]] = ", ".join(queryResponse.sources)
        number_queries += 1

    if include_sources_summary:
        summaryResponse = summarize_sources(queryResponse.sources)
        usage += summaryResponse.usage
        data[E_req["source_summary_column"]] = summaryResponse.summary

    return LookupObjectResponse(
        data=data,
        answer=queryResponse.text,
        includes_sources=include_sources,
        includes_sources_summary=include_sources_summary,
        count_fields_researched=count_fields_researched,
        researched_fields=list(researched_fields),
        sources=queryResponse.sources,
        usage=usage,
        error=error,
    )
