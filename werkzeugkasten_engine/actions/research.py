from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, TypeVar

from werkzeugkasten_engine.actions import summarize
from werkzeugkasten_engine.actions.lookup import lookup_row
from werkzeugkasten_engine.internal import choose_output_path, split_by
from werkzeugkasten_engine.internal.openai import query
from werkzeugkasten_engine.internal.table import Table
from werkzeugkasten_engine.internal.value import maybe_question

SOURCE_COLUMN = "Sources"
SOURCE_SUMMARY_COLUMN = "Sources[RAW]"
TAG_COLUMN = "Tags"

T = TypeVar("T")


@dataclass(frozen=True)
class ResearchResult:
    table: Table
    questions: list[str]
    attributes: list[str]
    failures: list[str]
    started_at: datetime

    def to_markdown(self) -> str:
        lines = [
            "# Research",
            "",
            f"- Generated: {self.started_at.strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"- Source: {self.table.origin}",
            f"- Detected format: {self.table.detected_format}",
            f"- Rows: {len(self.table)}",
            "",
            "## Detected Columns",
            "",
            "Questions:",
        ]
        lines.extend([f"- {column}" for column in self.questions] or ["- none"])
        lines.extend(["", "Attributes:"])
        lines.extend([f"- {column}" for column in self.attributes] or ["- none"])
        lines.extend(["", "## Merged Table", ""])
        lines.extend(str(self.table))
        lines.extend(["", "## Failures", ""])
        lines.extend([f"- {failure}" for failure in self.failures] or ["- none"])
        return "\n".join(lines).rstrip() + "\n"


@dataclass(frozen=True)
class InspectTableResult:
    sourceName: str
    detectedFormat: str
    headers: list[str]
    keyHeader: str
    rowCount: int
    questionColumns: list[str]
    attributeColumns: list[str]
    exampleKey: str
    objectType: str


def _research_model() -> str:
    return os.environ.get("WERKZEUGKASTEN_RESEARCH_MODEL", "gpt-5.4")


def _number_of_tags(count: int) -> tuple[int, int]:
    minimum = max(3, min(8, count // 8 + 2))
    maximum = max(minimum, min(15, count // 5 + 1))
    return minimum, maximum


def _apply_auto_tags(
    table: Table,
    *,
    column_name: str,
) -> None:
    if len(table) < 2:
        return
    minimum_tags, maximum_tags = _number_of_tags(len(table))
    prompt = f"""You are categorizing {table.key_header} rows, which were prefilled with metadata.

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
{table.to_json(without={SOURCE_COLUMN, SOURCE_SUMMARY_COLUMN})}
"""
    answer = query(prompt, model=_research_model())
    tags = answer.json.get("tags")
    assignments = answer.json.get("assignments")
    if not isinstance(tags, list) or not isinstance(assignments, dict):
        return
    allowed_tags = {str(tag).strip() for tag in tags if str(tag).strip()}
    for index, _ in table:
        values = assignments.get(f"row-{index}", [])
        if not isinstance(values, list):
            continue
        normalized = [str(tag).strip() for tag in values if str(tag).strip() in allowed_tags]
        table[index, column_name] = ", ".join(dict.fromkeys(normalized))


def _apply_nearest_neighbours(
    table: Table,
    *,
    column_name: str,
) -> None:
    if len(table) < 2:
        return
    prompt = f"""You are comparing {table.key_header} rows, which were prefilled with metadata.

For each {table.key_header}, identify the 1 to 3 most similar other {table.key_header}s based on the row summary.
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
{table.to_json(without={SOURCE_COLUMN, SOURCE_SUMMARY_COLUMN})}
"""
    answer = query(prompt, model=_research_model())
    neighbours = answer.json.get("neighbors")
    if not isinstance(neighbours, dict):
        return
    labels = {f"row-{index}": row.get(table.key_header, "").strip() or f"Row {index}" for index, row in table}
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
        table[int(row_id.split("-")[1]) - 1, column_name] = ", ".join(matches)


@dataclass(frozen=True)
class ResearchRowResult:
    row: dict[str, str] | None
    failure: str | None = None


def _research_row(
    row: dict[str, str],
    research_columns: list[str],
    questions: list[str],
    include_sources: bool,
    summarize_sources: bool,
    key_header: str,
):
    missing_columns = [column for column in research_columns if not row.get(column, "").strip()]
    if not missing_columns:
        return ResearchRowResult(row=row)
    answer = lookup_row(
        row,
        key_header,
        missing_columns,
        questions,
    )
    if answer.error:
        return ResearchRowResult(failure=f"{row[key_header]}: {answer.error or 'No response.'}")
    for column in missing_columns:
        row[column] = answer.data.get(column, row.get(column, ""))

    if include_sources:
        row[SOURCE_COLUMN] = ", ".join(answer.sources)
    if summarize_sources:
        row[SOURCE_SUMMARY_COLUMN] = summarize(answer.sources)
    return ResearchRowResult(row=row)


def _split_by(items: Iterable[T], pred: Callable[[T], bool]) -> tuple[list[T], list[T]]:
    yes: list[T] = []
    no: list[T] = []
    for x in items:
        (yes if pred(x) else no).append(x)
    return yes, no


def inspect_table(
    table: Table | str,
) -> dict[str, object]:
    table = Table(table)
    questions, attributes = _split_by(table.columns, lambda header: maybe_question(header) is not None)

    return InspectTableResult(
        sourceName=table.origin,
        detectedFormat=table.detected_format,
        headers=list(table.columns),
        keyHeader=table.key_header,
        rowCount=len(table),
        questionColumns=list(questions),
        attributeColumns=list(attributes),
        exampleKey=table.rows()[0].get(table.key_header, ""),
        objectType=table.object_type,
    )


def research_table(
    table: Table | str,
    /,
    *,
    include_sources: bool = False,
    summarize_sources: bool = False,
    auto_tagging: bool = False,
    nearest_neighbour: bool = False,
    output_dir: Path | None = None,
    output_path: str | Path | None = None,
) -> dict[str, object]:
    table = Table(table)
    questions, attributes = _split_by(table.columns, lambda header: maybe_question(header) is not None)

    research_columns = questions + attributes

    started_at = datetime.now().astimezone()

    destination = choose_output_path(
        started_at,
        f"{table.key_header}-research",
        output_dir,
        explicit_path=output_path,
    )
    failures: list[str] = []

    if include_sources:
        table.add_column(SOURCE_COLUMN)
    if summarize_sources:
        table.add_column(SOURCE_SUMMARY_COLUMN)

    for row in table.rows():
        result = _research_row(row, research_columns, questions, include_sources, summarize_sources, table.key_header)
        if result.failure:
            failures.append(result.failure)
        if result.row:
            table.update_row(result.row)

    if auto_tagging:
        table.add_column(TAG_COLUMN)
        _apply_auto_tags(
            table,
            column_name=TAG_COLUMN,
        )
    if nearest_neighbour:
        nearest_column = f"Closest {table.key_header.title()}"
        table.add_column(nearest_column)
        _apply_nearest_neighbours(
            table,
            column_name=nearest_column,
        )

    result = ResearchResult(
        table=table,
        questions=questions,
        attributes=attributes,
        failures=failures,
        started_at=started_at,
    )

    destination.write_text(
        result.to_markdown(),
        encoding="utf-8",
    )
    return result
