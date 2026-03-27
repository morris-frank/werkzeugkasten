from __future__ import annotations

import json
import os
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from werkzeugkasten_engine.internal import split_by
from werkzeugkasten_engine.internal.logging import DebugLogger
from werkzeugkasten_engine.internal.table import Policy, Table
from werkzeugkasten_engine.internal.value import as_object_type, maybe_question

_SOURCE_COLUMN = "Sources"
_SOURCE_RAW_COLUMN = "Sources[RAW]"
_TAG_COLUMN = "Tags"
_RECORD_ID_COLUMN = "Record ID"


def research_model() -> str:
    return os.environ.get(RESEARCH_MODEL_ENV, DEFAULT_RESEARCH_MODEL)


def _prompt_make_explicit_question(header: str, key: str, object_type: str) -> str:
    if question := maybe_question(header):
        return question

    return f"What is the {header} of the {object_type} {key}?"


def _number_of_tags(count: int) -> tuple[int, int]:
    minimum = max(3, min(8, count // 8 + 2))
    maximum = max(minimum, min(15, count // 5 + 1))
    return minimum, maximum


def _prompt_tagging(row: pd.Series, object_type: str) -> str:
    minimum_tags, maximum_tags = _number_of_tags(len(rows))
    prompt = f"""You are categorizing {object_type} rows, which where prefilled with metadata.

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


def inspect_table(table: Table, /) -> dict[str, object]:
    questions, attributes = split_by(table.columns, maybe_question)

    return {
        "source_name": table.origin,
        "detected_format": table.format,
        "headers": table.columns,
        "row_count": len(table),
        "question_columns": questions,
        "attribute_columns": attributes,
        "object_type": as_object_type(table.origin),
    }


# ------------------------------------------------------------


def apply_auto_tags(
    rows: list[dict[str, str]],
    *,
    key_header: str,
    headers: list[str],
    object_type: str,
    tag_column: DynamicColumn,
    excluded_columns: set[str],
    debug_logger: DebugLogger | None = None,
) -> None:

    row_payload = io_ops.row_context_payload(rows, key_header=key_header, headers=headers, excluded_columns=excluded_columns)

    data = run_json_prompt(prompt, debug_logger=debug_logger, prompt_kind="auto_tagging")
    tags = data.get("tags")
    assignments = data.get("assignments")
    if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
        raise ValueError("Tag response is missing a valid `tags` list.")
    if not isinstance(assignments, dict):
        raise ValueError("Tag response is missing `assignments`.")
    allowed_tags = {tag.strip() for tag in tags}
    for index, row in enumerate(rows, start=1):
        values = assignments.get(f"row-{index}", [])
        if not isinstance(values, list):
            continue
        normalized = [tag.strip() for tag in values if isinstance(tag, str) and tag.strip() in allowed_tags]
        apply_dynamic_value(row, tag_column, ", ".join(dict.fromkeys(normalized)))


def apply_nearest_neighbours(
    rows: list[dict[str, str]],
    *,
    key_header: str,
    headers: list[str],
    object_type: str,
    nearest_column: DynamicColumn,
    excluded_columns: set[str],
    debug_logger: DebugLogger | None = None,
) -> None:
    row_payload = io_ops.row_context_payload(rows, key_header=key_header, headers=headers, excluded_columns=excluded_columns)
    prompt = f"""You are comparing {object_type} rows, which where prefilled with metadata.

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
    data = run_json_prompt(prompt, debug_logger=debug_logger, prompt_kind="nearest_neighbour")
    neighbours = data.get("neighbors")
    if not isinstance(neighbours, dict):
        raise ValueError("Nearest-neighbour response is missing `neighbors`.")
    labels = {f"row-{index}": row.get(key_header, "").strip() or f"Row {index}" for index, row in enumerate(rows, start=1)}
    for row_id, row in labels.items():
        raw_matches = neighbours.get(row_id, [])
        if not isinstance(raw_matches, list):
            continue
        matches: list[str] = []
        for match in raw_matches:
            if not isinstance(match, str) or match == row_id or match not in labels:
                continue
            label = labels[match]
            if label not in matches:
                matches.append(label)
            if len(matches) == 3:
                break
        apply_dynamic_value(rows[int(row_id.split("-")[1]) - 1], nearest_column, ", ".join(matches))


def _render_markdown_report(
    source_name: str,
    detected_format: str,
    headers: list[str],
    rows: list[dict[str, str]],
    question_columns: list[str],
    attribute_columns: list[str],
    started_at: datetime,
    processed_rows: int,
    failures: list[Failure],
    skipped_rows: list[str],
    source_fetch_issues: list[SourceFetchIssue],
) -> str:
    key_header = headers[0]
    object_type = object_type_from_header(key_header)
    lines = [
        "# AI Research Table",
        "",
        f"- Generated: {started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"- Source: {source_name}",
        f"- Detected format: {detected_format}",
        f"- Rows: {len(rows)}",
        f"- Requested columns per row: {max(0, len(headers) - 1)}",
        f"- Key column: {key_header}",
        f"- Object type: {object_type}",
        f"- Progress: {processed_rows}/{len(rows)}",
        "",
        "## Detected Columns",
        "",
        "Questions:",
    ]
    lines.extend([f"- {column}" for column in question_columns] or ["- none"])
    lines.extend(["", "Attributes:"])
    lines.extend([f"- {column}" for column in attribute_columns] or ["- none"])
    lines.extend(["", "## Merged Table", ""])
    lines.extend(render_markdown_table(headers, rows))
    lines.extend(["", "## Skipped Rows", ""])
    lines.extend([f"- {row}" for row in skipped_rows] or ["- none"])
    lines.extend(["", "## Source Fetch Issues", ""])
    if source_fetch_issues:
        for issue in source_fetch_issues:
            status = f"HTTP {issue.status_code}" if issue.status_code is not None else issue.error_class
            lines.append(f"- Row {issue.row_number}: {issue.key} | {status} | {issue.url}")
            if issue.message:
                lines.append(f"  - {issue.message}")
    else:
        lines.append("- none")
    if processed_rows < len(rows):
        lines.extend(["", "## Pending Rows", ""])
        for row in rows[processed_rows:]:
            lines.append(f"- {row.get(key_header, '').strip() or '[blank]'}")
    lines.extend(["", "## Failed Responses", ""])
    if failures:
        for failure in failures:
            title = failure.key if failure.row_number is None else f"Row {failure.row_number}: {failure.key}"
            lines.extend([f"### {title}", "", "Columns:"])
            lines.extend(f"- {column}" for column in failure.columns or ["none"])
            lines.extend(["", failure.raw_text or failure.error or "No response."])
            if failure.error:
                lines.extend(["", f"_Note: {failure.error}_"])
            if failure.sources:
                lines.extend(["", "Sources:"])
                lines.extend(f"- {url}" for url in failure.sources[:10])
            lines.append("")
    else:
        lines.extend(["None.", ""])
    return "\n".join(lines).rstrip() + "\n"


def generate_record_id(key: str, row_index: int) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", key.strip().lower()).strip("-")
    if not safe:
        safe = f"row-{row_index}"
    return f"{safe}-{row_index}"


def merge_source_lists(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for url in group:
            if url and url not in merged:
                merged.append(url)
    return merged


def research_table(
    table: Table,
    /,
    *,
    include_sources: bool,
    source_column_policy: Policy,
    include_source_raw: bool,
    source_raw_column_policy: Policy,
):
    if include_sources:
        source_column = resolve_dynamic_column(headers, rows, SOURCE_COLUMN, source_column_policy)
    elif existing_source_header is not None:
        source_column = DynamicColumn(name=existing_source_header, existed=True, policy=Policy.MERGE)
    if include_source_raw:
        source_raw_column = resolve_dynamic_column(headers, rows, SOURCE_RAW_COLUMN, source_raw_column_policy)
    elif existing_source_raw_header is not None:
        source_raw_column = DynamicColumn(name=existing_source_raw_header, existed=True, policy=Policy.MERGE)

    started_at = datetime.now().astimezone()
    output_path = choose_output_path(
        started_at,
        build_output_label(dataset.source_name, headers),
        output_dir,
        explicit_path=options.output_path,
    )
    debug_log_path = debug_log_path_for_output(output_path)
    debug_logger = DebugLogger(debug_log_path)
    failures: list[Failure] = []
    skipped_rows: list[str] = []
    source_fetch_issues: list[SourceFetchIssue] = []
    notion_export_result: dict[str, object] | None = None
    processed_rows = 0
    source_raw_cache: dict[str, FetchResult] = {}

    write_output(
        output_path,
        dataset.source_name,
        dataset.detected_format,
        headers,
        rows,
        question_columns,
        attribute_columns,
        started_at,
        processed_rows,
        failures,
        skipped_rows,
        source_fetch_issues,
        notion_export_result,
    )

    research_columns = [
        header
        for header in dataset.headers[1:]
        if header
        not in {
            SOURCE_COLUMN,
            SOURCE_RAW_COLUMN,
            TAG_COLUMN,
            f"Closest {object_type.title()}",
            RECORD_ID_COLUMN,
        }
    ]

    for index, row in enumerate(rows, start=1):
        key = row.get(key_header, "").strip() or f"Row {index}"
        existing_sources = source_urls_from_row(row, source_column.name if source_column else None)
        debug_logger.log(
            "row_started",
            row_number=index,
            key=key,
            row_snapshot=dict(row),
            existing_sources=existing_sources,
        )
        if progress:
            progress(index - 1, len(rows), key)

        missing_columns = [header for header in research_columns if not row.get(header, "").strip()]
        sources: list[str] = []
        if not missing_columns:
            skipped_rows.append(key)
            debug_logger.log(
                "row_skipped",
                row_number=index,
                key=key,
                reason="no_missing_research_columns",
                research_columns=research_columns,
            )
        else:
            try:
                updates, raw_text, sources, error = research_row(
                    row,
                    key_header,
                    missing_columns,
                    question_set,
                    debug_logger=debug_logger,
                    row_number=index,
                )
                if updates is not None:
                    merge_updates(row, missing_columns, updates)
                    debug_logger.log(
                        "row_merged",
                        row_number=index,
                        key=key,
                        missing_columns=missing_columns,
                        updates=updates,
                        row_snapshot=dict(row),
                        sources=sources,
                    )
                else:
                    failures.append(
                        Failure(
                            row_number=index,
                            key=key,
                            columns=missing_columns,
                            raw_text=raw_text,
                            sources=sources,
                            error=error,
                        )
                    )
                    debug_logger.log(
                        "row_failed_structured_validation",
                        row_number=index,
                        key=key,
                        missing_columns=missing_columns,
                        raw_text=raw_text,
                        error=error,
                        sources=sources,
                    )
            except Exception as exc:
                failures.append(
                    Failure(
                        row_number=index,
                        key=key,
                        columns=missing_columns,
                        raw_text=f"[Request failed] {exc}",
                        error=str(exc),
                    )
                )
                debug_logger.log(
                    "row_request_failed",
                    row_number=index,
                    key=key,
                    missing_columns=missing_columns,
                    error=str(exc),
                    traceback=traceback.format_exc(),
                )

        preserve_existing_sources = bool(
            source_column is not None and should_preserve_existing(row.get(source_column.name, ""), source_column.policy)
        )
        if preserve_existing_sources:
            effective_sources = existing_sources
        elif sources:
            effective_sources = sources
        else:
            effective_sources = existing_sources
        if source_column is not None and effective_sources:
            if preserve_existing_sources:
                row[source_column.name] = io_ops.normalize_source_cell_value(row.get(source_column.name, ""))
            else:
                row[source_column.name] = io_ops.normalize_source_cell_value(", ".join(effective_sources))
            debug_logger.log(
                "row_sources_applied",
                row_number=index,
                key=key,
                target_column=source_column.name,
                sources=effective_sources,
                value=row.get(source_column.name, ""),
            )
        if (
            source_raw_column is not None
            and effective_sources
            and not should_preserve_existing(row.get(source_raw_column.name, ""), source_raw_column.policy)
        ):
            row[source_raw_column.name] = combine_source_raw_text(
                effective_sources,
                key=key,
                row_number=index,
                cache=source_raw_cache,
                issues=source_fetch_issues,
                debug_logger=debug_logger,
            )
            debug_logger.log(
                "row_source_raw_applied",
                row_number=index,
                key=key,
                target_column=source_raw_column.name,
                sources=effective_sources,
                value_length=len(row.get(source_raw_column.name, "")),
            )
        elif source_raw_column is not None and effective_sources:
            debug_logger.log(
                "row_source_raw_skipped",
                row_number=index,
                key=key,
                reason="merge_policy_preserved_existing_value",
                target_column=source_raw_column.name,
                sources=effective_sources,
                existing_length=len(row.get(source_raw_column.name, "")),
            )

        processed_rows = index
        write_output(
            output_path,
            dataset.source_name,
            dataset.detected_format,
            headers,
            rows,
            question_columns,
            attribute_columns,
            started_at,
            processed_rows,
            failures,
            skipped_rows,
            source_fetch_issues,
            notion_export_result,
        )
        debug_logger.log(
            "markdown_written",
            path=str(output_path),
            processed_rows=processed_rows,
            latest_row=index,
            latest_key=key,
        )
        if progress:
            progress(index, len(rows), key)

    excluded_columns = {column.name for column in [source_raw_column] if column}

    if options.auto_tagging:
        tag_column = resolve_dynamic_column(headers, rows, TAG_COLUMN, options.tag_column_policy)
        if tag_column.name not in attribute_columns:
            attribute_columns.append(tag_column.name)
        try:
            apply_auto_tags(
                rows,
                key_header=key_header,
                headers=headers,
                object_type=object_type,
                tag_column=tag_column,
                excluded_columns=excluded_columns,
                debug_logger=debug_logger,
            )
            debug_logger.log("auto_tagging_completed", target_column=tag_column.name)
        except Exception as exc:
            failures.append(
                Failure(
                    row_number=None,
                    key="Auto Tagging",
                    columns=[tag_column.name],
                    raw_text=f"[Auto tagging failed] {exc}",
                    error=str(exc),
                )
            )
            debug_logger.log("auto_tagging_failed", error=str(exc), traceback=traceback.format_exc())

    if options.nearest_neighbour and tag_column is not None:
        nearest_column = resolve_dynamic_column(headers, rows, f"Closest {object_type.title()}", options.nearest_column_policy)
        if nearest_column.name not in attribute_columns:
            attribute_columns.append(nearest_column.name)
        try:
            apply_nearest_neighbours(
                rows,
                key_header=key_header,
                headers=headers,
                object_type=object_type,
                nearest_column=nearest_column,
                excluded_columns=excluded_columns,
                debug_logger=debug_logger,
            )
            debug_logger.log("nearest_neighbour_completed", target_column=nearest_column.name)
        except Exception as exc:
            failures.append(
                Failure(
                    row_number=None,
                    key="Nearest Neighbour",
                    columns=[nearest_column.name],
                    raw_text=f"[Nearest-neighbour analysis failed] {exc}",
                    error=str(exc),
                )
            )
            debug_logger.log("nearest_neighbour_failed", error=str(exc), traceback=traceback.format_exc())

    if options.export_to_notion:
        record_id_column = resolve_dynamic_column(headers, rows, RECORD_ID_COLUMN, options.record_id_column_policy)
        if record_id_column.name not in attribute_columns:
            attribute_columns.append(record_id_column.name)
        for index, row in enumerate(rows, start=1):
            if should_preserve_existing(row.get(record_id_column.name, ""), record_id_column.policy):
                continue
            row[record_id_column.name] = generate_record_id(row.get(key_header, ""), index)

    normalization_profile = normalize_dataset(
        headers,
        rows,
        key_header=key_header,
        question_columns=question_columns,
        source_column=source_column.name if source_column else None,
        source_raw_column=source_raw_column.name if source_raw_column else None,
        tag_column=tag_column.name if tag_column else None,
        nearest_column=nearest_column.name if nearest_column else None,
    )
    debug_logger.log(
        "normalization_completed",
        list_like_columns=sorted(normalization_profile.list_like_columns),
        url_like_columns=sorted(normalization_profile.url_like_columns),
        long_text_columns=sorted(normalization_profile.long_text_columns),
        row_preview=rows[:3],
    )

    if options.export_to_notion:
        try:
            notion_export_result = export_dataset_to_notion(
                title=build_output_label(dataset.source_name, headers),
                headers=headers,
                rows=rows,
                key_header=key_header,
                sources_column=source_column.name if source_column else None,
                source_raw_column=source_raw_column.name if source_raw_column else None,
                tags_column=tag_column.name if tag_column else None,
                nearest_column=nearest_column.name if nearest_column else None,
                record_id_column=record_id_column.name if record_id_column else None,
                list_like_columns=normalization_profile.list_like_columns,
                url_like_columns=normalization_profile.url_like_columns,
                long_text_columns=normalization_profile.long_text_columns,
            )
            debug_logger.log("notion_export_completed", result=notion_export_result)
        except Exception as exc:
            failures.append(
                Failure(
                    row_number=None,
                    key="Notion Export",
                    columns=[],
                    raw_text=f"[Notion export failed] {exc}",
                    error=str(exc),
                )
            )
            debug_logger.log("notion_export_failed", error=str(exc), traceback=traceback.format_exc())

    write_output(
        output_path,
        dataset.source_name,
        dataset.detected_format,
        headers,
        rows,
        question_columns,
        attribute_columns,
        started_at,
        len(rows),
        failures,
        skipped_rows,
        source_fetch_issues,
        notion_export_result,
    )
    debug_logger.log(
        "dataset_completed",
        output_path=str(output_path),
        debug_log_path=str(debug_log_path),
        processed_rows=len(rows),
        skipped_rows=skipped_rows,
        failure_count=len(failures),
        source_fetch_issue_count=len(source_fetch_issues),
        notion_export_result=notion_export_result,
        final_headers=headers,
        final_rows=rows,
    )
    return {
        "output_path": str(output_path),
        "debug_log_path": str(debug_log_path),
        "detected_format": dataset.detected_format,
        "row_count": len(rows),
        "headers": headers,
        "question_columns": question_columns,
        "attribute_columns": attribute_columns,
    }


def run_research_list(
    items: list[str],
    question: str,
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    options: ResearchOptions | None = None,
) -> dict[str, object]:
    pass
