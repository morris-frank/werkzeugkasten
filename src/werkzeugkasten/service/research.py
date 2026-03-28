from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from ..internal import choose_output_path
from ..internal.env import E_req
from ..internal.openai import query
from ..internal.table import Policy, Table
from ..internal.value import maybe_question
from .lookup import lookup_row
from .summarize import summarize


@dataclass(frozen=True)
class ResearchRowResult:
    row: dict[str, str]
    failure: str | None = None


@dataclass(frozen=True)
class ResearchResult:
    _table: Table
    output_path: str
    format: str
    headers: list[str]
    row_count: int
    question_columns: list[str]
    attribute_columns: list[str]
    example_key: str
    object_type: str

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}

    def to_markdown(self) -> str:
        lines = [
            "# Research",
            "",
            f"- Generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
            f"- Source: {self._table.origin}",
            f"- Detected format: {self._table.format}",
            f"- Rows: {len(self._table)}",
            "",
            "## Detected Columns",
            "",
            "Questions:",
        ]
        lines.extend([f"- {column}" for column in self.question_columns] or ["- none"])
        lines.extend(["", "Attributes:"])
        lines.extend([f"- {column}" for column in self.attribute_columns] or ["- none"])
        lines.extend(["", "## Merged Table", ""])
        lines.extend(str(self._table))
        lines.extend(["", "## Failures", ""])
        # lines.extend([f"- {failure}" for failure in self.failures] or ["- none"])
        return "\n".join(lines).rstrip() + "\n"


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
    prompt = f"""You are categorizing {table.object_type} rows, which were prefilled with metadata.

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
{table.to_json(without={E_req["source_column"], E_req["source_summary_column"]})}
"""
    answer = query(prompt, model=E_req["research_model"])
    tags = answer.json.get("tags")
    assignments = answer.json.get("assignments")
    if not isinstance(tags, list) or not isinstance(assignments, dict):
        return
    allowed_tags = {str(tag).strip() for tag in tags if str(tag).strip()}
    for object in table.objects:
        values = assignments.get(f"row-{object}", [])
        if not isinstance(values, list):
            continue
        normalized = [str(tag).strip() for tag in values if str(tag).strip() in allowed_tags]
        table[object, column_name] = ", ".join(dict.fromkeys(normalized))


def _apply_nearest_neighbours(
    table: Table,
    *,
    column_name: str,
) -> None:
    if len(table) < 2:
        return
    prompt = f"""You are comparing {table.object_type} rows, which were prefilled with metadata.

For each {table.object_type}, identify the 1 to 3 most similar other {table.object_type}s based on the row summary.
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
{table.to_json(without={E_req["source_column"], E_req["source_summary_column"]})}
"""
    answer = query(prompt, model=E_req["research_model"])
    neighbours = answer.json.get("neighbors")
    if not isinstance(neighbours, dict):
        return
    for label in table.objects:
        raw_matches = neighbours.get(label, [])
        if not isinstance(raw_matches, list):
            continue
        matches: list[str] = []
        for match in raw_matches:
            match_id = str(match)
            if match_id == label or match_id not in table.objects:
                continue
            candidate = table[match_id].get(table.object_type, "").strip() or f"Row {match_id}"
            if candidate != label and candidate not in matches:
                matches.append(candidate)
            if len(matches) == 3:
                break
        table[label, column_name] = ", ".join(matches)


def _research_row(
    row: dict[str, str],
    research_columns: list[str],
    questions: list[str],
    include_sources: bool,
    summarize_sources: bool,
    object_type: str,
):
    missing_columns = [column for column in research_columns if not row.get(column, "").strip()]
    if not missing_columns:
        return ResearchRowResult(row=row)
    answer = lookup_row(
        row,
        object_type,
        missing_columns,
        questions,
    )
    if error := answer.get("error"):
        return ResearchRowResult(row=row, failure=f"{row[object_type]}: {error or 'No response.'}")
    for column in missing_columns:
        row[column] = answer["data"].get(column, row.get(column, ""))

    if include_sources:
        row[E_req["source_column"]] = ", ".join(answer["sources"])
    if summarize_sources:
        row[E_req["source_summary_column"]] = summarize(answer["sources"])
    return ResearchRowResult(row=row)


def _questions_attributes(columns: Iterable[str], /) -> tuple[list[str], list[str]]:
    questions: list[str] = []
    attributes: list[str] = []
    for column in columns:
        (questions if maybe_question(column) else attributes).append(column)
    return questions, attributes


def inspect_table(
    table: Table | str,
) -> dict[str, Any]:
    table = Table(table)
    questions, attributes = _questions_attributes(table.columns)

    return ResearchResult(
        _table=table,
        output_path="",
        format=table.format,
        headers=list(table.columns),
        row_count=len(table),
        question_columns=questions,
        attribute_columns=attributes,
        example_key=next(iter(table)).get(table.object_type, ""),
        object_type=table.object_type,
    ).as_dict()


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
    source_column_policy: Policy = Policy.MERGE,
    source_raw_column_policy: Policy = Policy.MERGE,
    tag_column_policy: Policy = Policy.MERGE,
    nearest_column_policy: Policy = Policy.MERGE,
) -> dict[str, Any]:
    table = Table(table)
    questions, attributes = _questions_attributes(table.columns)

    research_columns = questions + attributes

    started_at = datetime.now().astimezone()

    destination = choose_output_path(
        started_at,
        f"{table.object_type}-research",
        output_dir,
        explicit_path=output_path,
    )
    failures: list[str] = []

    if include_sources:
        table.add_column(E_req["source_column"], policy=source_column_policy)
    if summarize_sources:
        table.add_column(E_req["source_summary_column"], policy=source_raw_column_policy)

    for row in table:
        result = _research_row(row, research_columns, questions, include_sources, summarize_sources, table.object_type)
        if result.failure:
            failures.append(result.failure)
        if result.row:
            table[result.row[table.object_type]] = result.row

    if auto_tagging:
        table.add_column(E_req["tags_column"], policy=tag_column_policy)
        _apply_auto_tags(
            table,
            column_name=E_req["tags_column"],
        )
    if nearest_neighbour:
        nearest_column = f"Closest {table.object_type.title()}"
        table.add_column(nearest_column, policy=nearest_column_policy)
        _apply_nearest_neighbours(
            table,
            column_name=nearest_column,
        )

    result = ResearchResult(
        _table=table,
        output_path=destination.as_posix(),
        format=table.format,
        headers=list(table.columns),
        row_count=len(table),
        question_columns=questions,
        attribute_columns=attributes,
        example_key=next(iter(table)).get(table.object_type, ""),
        object_type=table.object_type,
    )

    destination.write_text(
        result.to_markdown(),
        encoding="utf-8",
    )
    return result.as_dict()
