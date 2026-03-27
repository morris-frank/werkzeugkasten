class Table:
    def __init__(self, headers):
        self.headers = headers


def _prompt_research(
    key_header: str,
    key: str,
    row: dict[str, str],
    missing_columns: list[str],
    question_columns: set[str],
) -> str:
    object_type = object_type_from_header(key_header)
    known_values = [f"- {column}: {row[column]}" for column in row if column != key_header and row[column].strip()]
    missing_lines: list[str] = []
    for column in missing_columns:
        if column in question_columns:
            missing_lines.append(f"- {column} [question]: {prompt_make_explicit_question(column, key, object_type)}")
        else:
            missing_lines.append(f"- {column} [attribute]: fill with a short tag or very short value only")
    known_section = "\n".join(known_values) if known_values else "- none"
    missing_section = "\n".join(missing_lines)
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


def research_row(
    row: dict[str, str],
    key_header: str,
    missing_columns: list[str],
    question_columns: set[str],
    *,
    row_number: int | None = None,
) -> tuple[dict[str, str] | None, str, list[str], str]:
    key = row.get(key_header, "").strip() or "[blank]"
    prompt = _prompt_research(key_header, key, row, missing_columns, question_columns)
    client = openai_client()
    model = research_model()
    response = client.responses.create(
        input=prompt,
        **response_create_kwargs(model, use_web_search=True, include_web_sources=True),
    )
    raw_text = (response.output_text or "").strip()
    sources = io_ops.normalize_source_urls(extract_web_search_sources(response))
    if debug_logger is not None:
        debug_logger.log(
            "openai_response",
            row_number=row_number,
            key=key,
            model=model,
            output_text=raw_text,
            sources=sources,
        )
    try:
        data = json.loads(extract_json_block(raw_text))
        if data.get("key") != key:
            raise ValueError("Response key does not match request.")
        updates = data.get("updates")
        if not isinstance(updates, dict):
            raise ValueError("Response updates is missing.")
        normalized = {str(column): str(value or "").strip() for column, value in updates.items()}
        return normalized, raw_text, sources, ""
    except (json.JSONDecodeError, ValueError) as exc:
        return None, raw_text or "[No text returned]", sources, f"Structured validation failed: {exc}"
