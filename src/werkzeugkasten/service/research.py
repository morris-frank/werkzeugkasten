from __future__ import annotations

from datetime import datetime
from pathlib import Path
from statistics import mean

import pandas as pd

from ..internal import choose_output_path
from ..internal.env import E_req
from ..internal.openai import query
from ..internal.table import Policy, Table
from ..internal.value import as_list, maybe_question
from .lookup import lookup_object
from .models import InspectTableResponse, QueryUsage, ResearchTableResponse


def _research_response_to_markdown(researchResponse: ResearchTableResponse) -> str:
    lines = [
        "# Web Research",
        "",
        f"Looked up {len(researchResponse.table)} `{researchResponse.object_type}`s: ",
        "",
        f"- Usage: {researchResponse.usage.token_count} tokens",
        f"- Number of queries: {researchResponse.usage.number_queries}",
        f"- Mean number of fields researched: {researchResponse.mean_count_fields_researched}",
        f"- Researched fields: {', '.join(researchResponse.researched_fields)}",
        f"- Sources: {', '.join(researchResponse.sources)}",
        f"- Generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}",
        "",
        "## Researched columns",
        "",
        "### Questions",
        "",
    ]
    lines.extend([f"- {column}" for column in researchResponse.question_columns] or ["_none_"])
    lines.extend(["", "### Attributes", ""])
    lines.extend([f"- {column}" for column in researchResponse.attribute_columns] or ["_none_"])
    lines.extend(["", "## Final table", ""])
    lines.extend(str(researchResponse.table))
    return "\n".join(lines).rstrip() + "\n"


def _number_of_tags(count: int) -> tuple[int, int]:
    minimum = max(3, min(8, count // 8 + 2))
    maximum = max(minimum, min(15, count // 5 + 1))
    return minimum, maximum


def _apply_auto_tags(
    table: Table,
    *,
    column_name: str,
) -> QueryUsage:
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
    queryResponse = query(prompt, model=E_req["research_model"])
    queryJSON = queryResponse.as_json
    tags = queryJSON.get("tags")
    assignments = queryJSON.get("assignments")
    if not isinstance(tags, list) or not isinstance(assignments, dict):
        return
    allowed_tags = {str(tag).strip() for tag in tags if str(tag).strip()}
    for object in table.objects:
        values = assignments.get(f"row-{object}", [])
        if not isinstance(values, list):
            continue
        normalized = [str(tag).strip() for tag in values if str(tag).strip() in allowed_tags]
        table[object, column_name] = ", ".join(dict.fromkeys(normalized))
    return queryResponse.usage


def _apply_nearest_neighbours(
    table: Table,
    *,
    column_name: str,
) -> QueryUsage:
    if len(table) < 2:
        return QueryUsage()
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

    return answer.usage


def inspect_table(
    table: Table | str,
) -> InspectTableResponse:
    table = Table(table)
    questions = [column for column in table.columns if maybe_question(column)]
    return InspectTableResponse(
        format=table.format,
        object_type=table.object_type,
        example_object=next(iter(table)).get(table.object_type, ""),
        row_count=len(table),
        columns=list(table.columns),
        question_columns=questions,
        attribute_columns=[column for column in table.columns if not column in questions],
    )


def research_table(
    table: Table | str,
    /,
    *,
    include_sources: bool = False,
    include_sources_summary: bool = False,
    auto_tagging: bool = False,
    nearest_neighbour: bool = False,
    output_path: str | Path | None = None,
    source_column_policy: Policy = Policy.MERGE,
    source_summary_column_policy: Policy = Policy.MERGE,
    tag_column_policy: Policy = Policy.MERGE,
    nearest_column_policy: Policy = Policy.MERGE,
) -> ResearchTableResponse:
    table = Table(table)
    started_at = datetime.now().astimezone()

    destination = choose_output_path(
        started_at,
        f"{table.object_type}-research",
        explicit_path=output_path,
    )

    if include_sources:
        table.add_column(E_req["source_column"], policy=source_column_policy)
    if include_sources_summary:
        table.add_column(E_req["source_summary_column"], policy=source_summary_column_policy)

    researched_fields: set[str] = set()
    count_fields_researched: list[int] = []
    usage = QueryUsage()
    sources: list[str] = []
    for row in table:
        # TODO: handle non-named tables
        object_name = row.get(table.object_type)
        if not object_name:
            continue
        lookup_response = lookup_object(
            row,
            object_type=table.object_type,
            object_name=object_name,
            include_sources=include_sources,
            include_sources_summary=include_sources_summary,
        )
        researched_fields.update(lookup_response.researched_fields)
        count_fields_researched.append(lookup_response.count_fields_researched)
        usage += lookup_response.usage
        sources.extend(lookup_response.sources)
        table[row[table.object_type]] = lookup_response.data

    if auto_tagging:
        table.add_column(E_req["tags_column"], policy=tag_column_policy)
        usage += _apply_auto_tags(
            table,
            column_name=E_req["tags_column"],
        )
    if nearest_neighbour:
        nearest_column = f"Closest {table.object_type.title()}"
        table.add_column(nearest_column, policy=nearest_column_policy)
        usage += _apply_nearest_neighbours(
            table,
            column_name=nearest_column,
        )

    question_columns = [column for column in table.columns if maybe_question(column)]
    researchResponse = ResearchTableResponse(
        table=str(table.to_json()),
        format=table.format,
        output_path=destination.as_posix(),
        object_type=table.object_type,
        example_object=next(iter(table)).get(table.object_type, ""),
        row_count=len(table),
        columns=list(table.columns),
        question_columns=question_columns,
        attribute_columns=[column for column in table.columns if not column in question_columns],
        includes_sources=include_sources,
        includes_sources_summary=include_sources_summary,
        includes_auto_tags=auto_tagging,
        includes_nearest_neighbours=nearest_neighbour,
        mean_count_fields_researched=mean(count_fields_researched) if count_fields_researched else 0,
        researched_fields=list(researched_fields),
        sources=sources,
        usage=usage,
    )

    destination.write_text(
        _research_response_to_markdown(researchResponse),
        encoding="utf-8",
    )
    return researchResponse


def research_list(
    items: list[str] | str,
    question: str,
    output_path: str | Path | None = None,
    include_sources: bool = False,
    include_sources_summary: bool = False,
    source_column_policy: Policy = Policy.MERGE,
    source_summary_column_policy: Policy = Policy.MERGE,
) -> ResearchTableResponse:

    items = as_list(items)
    question = str(question).strip()

    table = pd.DataFrame({question: ""}, index=items)
    return research_table(
        table,
        include_sources=include_sources,
        include_sources_summary=include_sources_summary,
        output_path=output_path,
        source_column_policy=source_column_policy,
        source_summary_column_policy=source_summary_column_policy,
    )
