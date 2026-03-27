from __future__ import annotations

import json
import os
from codecs import lookup
from datetime import datetime
from pathlib import Path

from werkzeugkasten_engine.actions.lookup import lookup_row
from werkzeugkasten_engine.internal import choose_output_path, split_by
from werkzeugkasten_engine.internal.content import get_content
from werkzeugkasten_engine.internal.logging import DebugLogger, ProgressCallback, debug_log_path_for_output
from werkzeugkasten_engine.internal.openai import query
from werkzeugkasten_engine.internal.table import Policy, Table
from werkzeugkasten_engine.internal.value import as_object_type, as_urls, maybe_question

SOURCE_COLUMN = "Sources"
SOURCE_RAW_COLUMN = "Sources[RAW]"
TAG_COLUMN = "Tags"


def _research_model() -> str:
    return os.environ.get("WERKZEUGKASTEN_RESEARCH_MODEL", "gpt-5.4")


def _table_headers(table: Table) -> list[str]:
    return [table.key_header, *table.columns]


def _inspect_table(table: Table | str, /) -> dict[str, object]:
    table = Table(table)
    questions, attributes = split_by(table.columns, lambda header: maybe_question(header) is not None)
    rows = table.rows()
    return {
        "source_name": table.key_header,
        "detected_format": table.format,
        "headers": _table_headers(table),
        "key_header": table.key_header,
        "row_count": len(rows),
        "question_columns": questions,
        "attribute_columns": attributes,
        "example_key": rows[0][table.key_header] if rows else "",
        "object_type": as_object_type(table.key_header),
    }


def _merge_policy_value(row: dict[str, str], column: str, value: str, *, policy: Policy) -> None:
    if policy == Policy.MERGE and row.get(column, "").strip():
        return
    row[column] = value.strip()


def _render_markdown_table(headers: list[str], rows: list[dict[str, str]]) -> list[str]:
    def escape(value: str) -> str:
        return str(value).replace("\n", "<br>").replace("|", "\\|").strip()

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        values = [escape(row.get(header, "")) for header in headers]
        lines.append("| " + " | ".join(values) + " |")
    return lines


def _row_context_payload(
    rows: list[dict[str, str]],
    *,
    key_header: str,
    headers: list[str],
    excluded_columns: set[str],
) -> list[dict[str, str]]:
    visible_headers = [header for header in headers if header not in excluded_columns]
    payload: list[dict[str, str]] = []
    for index, row in enumerate(rows, start=1):
        entry = {"row_id": f"row-{index}", key_header: row.get(key_header, "")}
        for header in visible_headers:
            if header == key_header:
                continue
            value = row.get(header, "").strip()
            if value:
                entry[header] = value
        payload.append(entry)
    return payload


def _number_of_tags(count: int) -> tuple[int, int]:
    minimum = max(3, min(8, count // 8 + 2))
    maximum = max(minimum, min(15, count // 5 + 1))
    return minimum, maximum


def _apply_auto_tags(
    rows: list[dict[str, str]],
    *,
    key_header: str,
    headers: list[str],
    object_type: str,
    column_name: str,
    policy: Policy,
    excluded_columns: set[str],
) -> None:
    if len(rows) < 2:
        return
    row_payload = _row_context_payload(rows, key_header=key_header, headers=headers, excluded_columns=excluded_columns)
    minimum_tags, maximum_tags = _number_of_tags(len(rows))
    prompt = f"""You are categorizing {object_type} rows, which were prefilled with metadata.

Choose a compact but discriminative set of categorical tags for the sample as a whole.
- Prefer tags that separate the samples meaningfully.
- Use between {minimum_tags} and {maximum_tags} tags total for this dataset.
- Tags should be short category labels, not sentences.

Return JSON only in this shape:
{{
  "tags": ["tag one", "tag two"],
  "assignments": {{
    "row-1": ["tag one"],
    "row-2": ["tag two", "tag three"]
  }}
}}

Rows:
{json.dumps(row_payload, ensure_ascii=False, indent=2)}
"""
    answer = query(prompt, model=_research_model())
    tags = answer.json.get("tags")
    assignments = answer.json.get("assignments")
    if not isinstance(tags, list) or not isinstance(assignments, dict):
        return
    allowed_tags = {str(tag).strip() for tag in tags if str(tag).strip()}
    for index, row in enumerate(rows, start=1):
        values = assignments.get(f"row-{index}", [])
        if not isinstance(values, list):
            continue
        normalized = [str(tag).strip() for tag in values if str(tag).strip() in allowed_tags]
        _merge_policy_value(row, column_name, ", ".join(dict.fromkeys(normalized)), policy=policy)


def _apply_nearest_neighbours(
    rows: list[dict[str, str]],
    *,
    key_header: str,
    headers: list[str],
    object_type: str,
    column_name: str,
    policy: Policy,
    excluded_columns: set[str],
) -> None:
    if len(rows) < 2:
        return
    row_payload = _row_context_payload(rows, key_header=key_header, headers=headers, excluded_columns=excluded_columns)
    prompt = f"""You are comparing {object_type} rows, which were prefilled with metadata.

For each {object_type}, identify the 1 to 3 most similar other {object_type}s based on the row summary.
- Do not include the row itself.
- Prefer the strongest semantic matches.

Return JSON only in this shape:
{{
  "neighbors": {{
    "row-1": ["row-2", "row-5"],
    "row-2": ["row-1"]
  }}
}}

Rows:
{json.dumps(row_payload, ensure_ascii=False, indent=2)}
"""
    answer = query(prompt, model=_research_model())
    neighbours = answer.json.get("neighbors")
    if not isinstance(neighbours, dict):
        return
    labels = {f"row-{index}": row.get(key_header, "").strip() or f"Row {index}" for index, row in enumerate(rows, start=1)}
    for row_id, label in labels.items():
        raw_matches = neighbours.get(row_id, [])
        if not isinstance(raw_matches, list):
            continue
        matches: list[str] = []
        for match in raw_matches:
            match_id = str(match)
            if match_id == row_id or match_id not in labels:
                continue
            candidate = labels[match_id]
            if candidate != label and candidate not in matches:
                matches.append(candidate)
            if len(matches) == 3:
                break
        _merge_policy_value(rows[int(row_id.split("-")[1]) - 1], column_name, ", ".join(matches), policy=policy)


def _render_report(
    *,
    source_name: str,
    detected_format: str,
    headers: list[str],
    rows: list[dict[str, str]],
    question_columns: list[str],
    attribute_columns: list[str],
    failures: list[str],
    started_at: datetime,
) -> str:
    lines = [
        "# AI Research Table",
        "",
        f"- Generated: {started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- Source: {source_name}",
        f"- Detected format: {detected_format}",
        f"- Rows: {len(rows)}",
        "",
        "## Detected Columns",
        "",
        "Questions:",
    ]
    lines.extend([f"- {column}" for column in question_columns] or ["- none"])
    lines.extend(["", "Attributes:"])
    lines.extend([f"- {column}" for column in attribute_columns] or ["- none"])
    lines.extend(["", "## Merged Table", ""])
    lines.extend(_render_markdown_table(headers, rows))
    lines.extend(["", "## Failures", ""])
    lines.extend([f"- {failure}" for failure in failures] or ["- none"])
    return "\n".join(lines).rstrip() + "\n"


def research_table(
    table: Table | str,
    /,
    *,
    include_sources: bool = False,
    source_column_policy: Policy = Policy.MERGE,
    include_source_raw: bool = False,
    source_raw_column_policy: Policy = Policy.MERGE,
    auto_tagging: bool = False,
    tag_column_policy: Policy = Policy.MERGE,
    nearest_neighbour: bool = False,
    nearest_column_policy: Policy = Policy.MERGE,
    output_dir: Path | None = None,
    output_path: str | Path | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    table = Table(table)
    preview = _inspect_table(table)
    key_header = str(preview["key_header"])
    question_columns = list(preview["question_columns"])
    attribute_columns = list(preview["attribute_columns"])
    research_columns = question_columns + attribute_columns
    rows = table.rows()
    headers = list(preview["headers"])
    started_at = datetime.now().astimezone()
    destination = choose_output_path(
        started_at,
        f"{key_header}-research",
        output_dir,
        explicit_path=output_path,
    )
    debug_logger = DebugLogger(debug_log_path_for_output(destination))
    failures: list[str] = []

    if include_sources and SOURCE_COLUMN not in headers:
        headers.append(SOURCE_COLUMN)
        attribute_columns.append(SOURCE_COLUMN)
    if include_source_raw and SOURCE_RAW_COLUMN not in headers:
        headers.append(SOURCE_RAW_COLUMN)
        attribute_columns.append(SOURCE_RAW_COLUMN)

    for index, row in enumerate(rows, start=1):
        key = row.get(key_header, "").strip() or f"Row {index}"
        if progress is not None:
            progress(index - 1, len(rows), key)
        missing_columns = [column for column in research_columns if not row.get(column, "").strip()]
        if not missing_columns:
            continue
        answer = lookup_row(
            row,
            key_header,
            missing_columns,
            set(question_columns),
            debug_logger=debug_logger,
            row_number=index,
        )
        if answer.data is None:
            failures.append(f"{key}: {answer.error or 'No response.'}")
            continue
        for column in missing_columns:
            _merge_policy_value(row, column, answer.data.get(column, row.get(column, "")), policy=Policy.OVERWRITE)
        if include_sources:
            merged_sources = answer.sources or as_urls(row.get(SOURCE_COLUMN, ""))
            _merge_policy_value(row, SOURCE_COLUMN, ", ".join(merged_sources), policy=source_column_policy)
        if include_source_raw:
            effective_sources = answer.sources or as_urls(row.get(SOURCE_COLUMN, ""))
            if effective_sources:
                raw_body = get_content(effective_sources, as_markdown=False)
                _merge_policy_value(row, SOURCE_RAW_COLUMN, raw_body, policy=source_raw_column_policy)
        if progress is not None:
            progress(index, len(rows), key)

    object_type = str(preview["object_type"])
    excluded_columns = {SOURCE_RAW_COLUMN}
    if auto_tagging:
        if TAG_COLUMN not in headers:
            headers.append(TAG_COLUMN)
            attribute_columns.append(TAG_COLUMN)
        _apply_auto_tags(
            rows,
            key_header=key_header,
            headers=headers,
            object_type=object_type,
            column_name=TAG_COLUMN,
            policy=tag_column_policy,
            excluded_columns=excluded_columns,
            debug_logger=debug_logger,
        )
    if nearest_neighbour:
        nearest_column = f"Closest {object_type.title()}"
        if nearest_column not in headers:
            headers.append(nearest_column)
            attribute_columns.append(nearest_column)
        _apply_nearest_neighbours(
            rows,
            key_header=key_header,
            headers=headers,
            object_type=object_type,
            column_name=nearest_column,
            policy=nearest_column_policy,
            excluded_columns=excluded_columns,
            debug_logger=debug_logger,
        )

    destination.write_text(
        _render_report(
            source_name=str(preview["source_name"]),
            detected_format=str(preview["detected_format"]),
            headers=headers,
            rows=rows,
            question_columns=question_columns,
            attribute_columns=attribute_columns,
            failures=failures,
            started_at=started_at,
        ),
        encoding="utf-8",
    )
    return {
        "output_path": str(destination),
        "detected_format": preview["detected_format"],
        "row_count": preview["row_count"],
        "headers": headers,
        "question_columns": question_columns,
        "attribute_columns": attribute_columns,
    }
