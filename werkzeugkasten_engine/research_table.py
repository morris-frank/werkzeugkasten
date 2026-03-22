from __future__ import annotations

import csv
import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Callable

from .core import (
    choose_output_path,
    esc,
    extract_json_block,
    extract_sources,
    jina_api_key,
    openai_client,
    research_model,
    response_create_kwargs,
)

ProgressCallback = Callable[[int, int, str], None]

QUESTION_WORDS = {
    "who",
    "what",
    "when",
    "where",
    "why",
    "how",
    "which",
    "is",
    "are",
    "do",
    "does",
    "did",
    "can",
    "could",
    "should",
    "would",
    "will",
}


@dataclass(frozen=True)
class ResearchOptions:
    include_sources: bool = False
    include_source_raw: bool = False
    auto_tagging: bool = False
    nearest_neighbour: bool = False

    def normalized(self) -> ResearchOptions:
        include_sources = self.include_sources or self.include_source_raw
        auto_tagging = self.auto_tagging or self.nearest_neighbour
        return ResearchOptions(
            include_sources=include_sources,
            include_source_raw=self.include_source_raw,
            auto_tagging=auto_tagging,
            nearest_neighbour=self.nearest_neighbour and auto_tagging,
        )


@dataclass
class Failure:
    row_number: int | None
    key: str
    columns: list[str]
    raw_text: str = ""
    sources: list[str] = field(default_factory=list)
    error: str = ""


@dataclass
class DatasetShape:
    source_name: str
    detected_format: str
    headers: list[str]
    rows: list[dict[str, str]]
    question_columns: list[str]


def guess_table_format(raw: str) -> str:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) >= 2 and "|" in lines[0]:
        second = lines[1].replace("|", " ").strip()
        if re.fullmatch(r"[:\-\s]+", second):
            return "markdown"
    if any("|" in line for line in lines[:3]):
        return "markdown"
    return "csv"


def normalize_headers(headers: list[str]) -> list[str]:
    normalized: list[str] = []
    used: dict[str, int] = {}
    for index, header in enumerate(headers, start=1):
        name = header.strip() or f"column_{index}"
        if name not in used:
            used[name] = 1
            normalized.append(name)
            continue
        used[name] += 1
        normalized.append(f"{name} {used[name]}")
    return normalized


def normalize_rows(headers: list[str], rows: list[list[str]]) -> list[list[str]]:
    width = len(headers)
    return [row[:width] + [""] * max(0, width - len(row)) for row in rows]


def is_markdown_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell.strip()) for cell in cells)


def parse_markdown_table(raw: str) -> tuple[list[str], list[list[str]]]:
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    rows = [[cell.strip() for cell in line.strip("|").split("|")] for line in lines if "|" in line]
    if len(rows) < 2:
        raise ValueError("Could not parse a markdown table.")
    headers = normalize_headers(rows[0])
    data_rows = rows[1:]
    if data_rows and is_markdown_separator(data_rows[0]):
        data_rows = data_rows[1:]
    return headers, normalize_rows(headers, data_rows)


def parse_csv_table(raw: str) -> tuple[list[str], list[list[str]]]:
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(StringIO(raw), dialect)
    rows = [[cell.strip() for cell in row] for row in reader if any(cell.strip() for cell in row)]
    if len(rows) < 2:
        raise ValueError("Could not parse a CSV table.")
    headers = normalize_headers(rows[0])
    return headers, normalize_rows(headers, rows[1:])


def rows_as_dicts(headers: list[str], rows: list[list[str]]) -> list[dict[str, str]]:
    return [dict(zip(headers, row)) for row in rows]


def is_question_header(header: str) -> bool:
    text = header.strip().lower()
    if not text:
        return False
    if "?" in text:
        return True
    return text.split()[0] in QUESTION_WORDS


def object_type_from_header(header: str) -> str:
    text = re.sub(r"[_-]+", " ", header.strip().lower())
    text = re.sub(r"\s+", " ", text).strip()
    if text.endswith(" name") and len(text.split()) > 1:
        text = text[:-5].strip()
    if text in {"name", "title"}:
        return "object"
    return text or "object"


def make_explicit_question(column: str, key: str, object_type: str) -> str:
    text = column.strip()
    if not text:
        return f"What is this for the {object_type} {key}?"
    if "?" in text:
        return text
    if text.split()[0].lower() in QUESTION_WORDS:
        return text if text.endswith("?") else f"{text}?"
    return f"What is the {text} of the {object_type} {key}?"


def parse_table(raw: str) -> tuple[str, list[str], list[dict[str, str]]]:
    detected_format = guess_table_format(raw)
    if detected_format == "markdown":
        headers, raw_rows = parse_markdown_table(raw)
    else:
        headers, raw_rows = parse_csv_table(raw)
    if len(headers) < 2:
        raise ValueError("Need at least two columns.")
    if not raw_rows:
        raise ValueError("No data rows found.")
    return detected_format, headers, rows_as_dicts(headers, raw_rows)


def question_columns_from_headers(headers: list[str]) -> list[str]:
    return [header for header in headers[1:] if is_question_header(header)]


def inspect_table(raw: str, source_name: str = "pasted-table") -> dict[str, object]:
    detected_format, headers, rows = parse_table(raw)
    question_columns = question_columns_from_headers(headers)
    attribute_columns = [header for header in headers[1:] if header not in question_columns]
    return {
        "source_name": source_name,
        "detected_format": detected_format,
        "headers": headers,
        "key_header": headers[0],
        "row_count": len(rows),
        "question_columns": question_columns,
        "attribute_columns": attribute_columns,
        "example_key": rows[0].get(headers[0], "").strip() or "[blank]",
        "object_type": object_type_from_header(headers[0]),
    }


def make_dataset_shape(
    *,
    source_name: str,
    detected_format: str,
    headers: list[str],
    rows: list[dict[str, str]],
    question_columns: list[str] | None = None,
) -> DatasetShape:
    normalized_headers = normalize_headers(headers)
    normalized_rows: list[dict[str, str]] = []
    for row in rows:
        normalized_row = {header: (row.get(header, "") or "").strip() for header in normalized_headers}
        normalized_rows.append(normalized_row)

    if len(normalized_headers) < 2:
        raise ValueError("Need at least two columns.")
    if not normalized_rows:
        raise ValueError("No data rows found.")

    resolved_question_columns = [
        column for column in (question_columns or []) if column in normalized_headers[1:]
    ] or question_columns_from_headers(normalized_headers)
    return DatasetShape(
        source_name=source_name,
        detected_format=detected_format,
        headers=normalized_headers,
        rows=normalized_rows,
        question_columns=resolved_question_columns,
    )


def build_prompt(
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
            missing_lines.append(f"- {column} [question]: {make_explicit_question(column, key, object_type)}")
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
) -> tuple[dict[str, str] | None, str, list[str], str]:
    key = row.get(key_header, "").strip() or "[blank]"
    client = openai_client()
    model = research_model()
    response = client.responses.create(
        input=build_prompt(key_header, key, row, missing_columns, question_columns),
        **response_create_kwargs(model, use_web_search=True, include_web_sources=True),
    )
    raw_text = (response.output_text or "").strip()
    sources = extract_sources(response)
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


def merge_updates(row: dict[str, str], missing_columns: list[str], updates: dict[str, str]) -> None:
    allowed = set(missing_columns)
    for column, value in updates.items():
        if column in allowed and value:
            row[column] = value


def render_markdown_table(headers: list[str], rows: list[dict[str, str]]) -> list[str]:
    lines = [
        "| " + " | ".join(esc(header) for header in headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(esc(row.get(header, "")) for header in headers) + " |")
    return lines


def build_output_label(source_name: str, headers: list[str]) -> str:
    if source_name != "pasted-table":
        return Path(source_name).stem
    return "-".join(headers[:3]) or "table-research"


def recommended_tag_bounds(count: int) -> tuple[int, int]:
    minimum = max(3, min(8, count // 8 + 2))
    maximum = max(minimum, min(15, count // 5 + 1))
    return minimum, maximum


def unique_header_name(headers: list[str], preferred: str) -> str:
    candidate = preferred.strip() or "Column"
    if candidate not in headers:
        return candidate
    suffix = 2
    while f"{candidate} {suffix}" in headers:
        suffix += 1
    return f"{candidate} {suffix}"


def add_dynamic_column(headers: list[str], rows: list[dict[str, str]], preferred: str) -> str:
    name = unique_header_name(headers, preferred)
    headers.append(name)
    for row in rows:
        row[name] = ""
    return name


def fetch_source_raw_text(url: str, cache: dict[str, str]) -> str:
    if url in cache:
        return cache[url]

    request = urllib.request.Request(
        f"https://r.jina.ai/{url}",
        headers={
            "X-Engine": "direct",
            "X-Retain-Images": "none",
        },
    )
    key = jina_api_key().strip()
    if key:
        request.add_header("Authorization", f"Bearer {key}")

    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            text = response.read().decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as exc:
        text = f"[Source fetch failed] {url}\nHTTP {exc.code}: {exc.reason}"
    except urllib.error.URLError as exc:
        text = f"[Source fetch failed] {url}\n{exc.reason}"
    except TimeoutError:
        text = f"[Source fetch failed] {url}\nTimed out."

    cache[url] = text
    return text


def combine_source_raw_text(urls: list[str], cache: dict[str, str]) -> str:
    parts: list[str] = []
    for url in urls:
        raw_text = fetch_source_raw_text(url, cache)
        parts.append(f"URL: {url}\n{raw_text}".strip())
    return "\n\n".join(parts).strip()


def row_context_payload(
    rows: list[dict[str, str]],
    *,
    key_header: str,
    headers: list[str],
    excluded_columns: set[str],
) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    visible_headers = [header for header in headers if header not in excluded_columns]
    for index, row in enumerate(rows, start=1):
        values = {header: row.get(header, "").strip() for header in visible_headers if row.get(header, "").strip()}
        payload.append(
            {
                "row_id": f"row-{index}",
                "key": row.get(key_header, "").strip() or f"Row {index}",
                "values": values,
            }
        )
    return payload


def run_json_prompt(prompt: str) -> dict[str, object]:
    client = openai_client()
    model = research_model()
    response = client.responses.create(
        input=prompt,
        **response_create_kwargs(model),
    )
    raw_text = (response.output_text or "").strip()
    try:
        data = json.loads(extract_json_block(raw_text))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"Structured validation failed: {exc}") from exc


def apply_auto_tags(
    rows: list[dict[str, str]],
    *,
    key_header: str,
    headers: list[str],
    object_type: str,
    tag_column: str,
    excluded_columns: set[str],
) -> None:
    minimum_tags, maximum_tags = recommended_tag_bounds(len(rows))
    row_payload = row_context_payload(rows, key_header=key_header, headers=headers, excluded_columns=excluded_columns)
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
    data = run_json_prompt(prompt)
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
        row[tag_column] = ", ".join(dict.fromkeys(normalized))


def apply_nearest_neighbours(
    rows: list[dict[str, str]],
    *,
    key_header: str,
    headers: list[str],
    object_type: str,
    nearest_column: str,
    excluded_columns: set[str],
) -> None:
    row_payload = row_context_payload(rows, key_header=key_header, headers=headers, excluded_columns=excluded_columns)
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
    data = run_json_prompt(prompt)
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
        rows[int(row_id.split("-")[1]) - 1][nearest_column] = ", ".join(matches)


def render_markdown(
    source_name: str,
    detected_format: str,
    headers: list[str],
    rows: list[dict[str, str]],
    question_columns: list[str],
    attribute_columns: list[str],
    started_at: datetime,
    processed_rows: int,
    failures: list[Failure],
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
                lines.extend(f"- {url}" for url in failure.sources[:5])
            lines.append("")
    else:
        lines.extend(["None.", ""])

    return "\n".join(lines).rstrip() + "\n"


def write_output(
    path: Path,
    source_name: str,
    detected_format: str,
    headers: list[str],
    rows: list[dict[str, str]],
    question_columns: list[str],
    attribute_columns: list[str],
    started_at: datetime,
    processed_rows: int,
    failures: list[Failure],
) -> None:
    path.write_text(
        render_markdown(
            source_name=source_name,
            detected_format=detected_format,
            headers=headers,
            rows=rows,
            question_columns=question_columns,
            attribute_columns=attribute_columns,
            started_at=started_at,
            processed_rows=processed_rows,
            failures=failures,
        ),
        encoding="utf-8",
    )


def run_research_dataset(
    dataset: DatasetShape,
    *,
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    options: ResearchOptions | None = None,
) -> dict[str, object]:
    options = (options or ResearchOptions()).normalized()
    headers = list(dataset.headers)
    rows = [dict(row) for row in dataset.rows]
    question_columns = [column for column in dataset.question_columns if column in headers[1:]]
    attribute_columns = [header for header in headers[1:] if header not in question_columns]
    key_header = headers[0]
    object_type = object_type_from_header(key_header)

    source_column: str | None = None
    source_raw_column: str | None = None
    tag_column: str | None = None
    nearest_column: str | None = None

    if options.include_sources:
        source_column = add_dynamic_column(headers, rows, "Sources")
        attribute_columns.append(source_column)
    if options.include_source_raw:
        source_raw_column = add_dynamic_column(headers, rows, "Sources[RAW]")
        attribute_columns.append(source_raw_column)

    started_at = datetime.now().astimezone()
    output_path = choose_output_path(started_at, build_output_label(dataset.source_name, headers), output_dir)
    failures: list[Failure] = []
    processed_rows = 0
    source_raw_cache: dict[str, str] = {}

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
    )

    question_set = set(question_columns)
    for index, row in enumerate(rows, start=1):
        key = row.get(key_header, "").strip() or f"Row {index}"
        if progress:
            progress(index - 1, len(rows), key)
        research_columns = [
            header for header in headers[1:] if header not in {source_column, source_raw_column, tag_column, nearest_column}
        ]
        missing_columns = [header for header in research_columns if not row.get(header, "").strip()]
        sources: list[str] = []
        if missing_columns:
            try:
                updates, raw_text, sources, error = research_row(row, key_header, missing_columns, question_set)
                if updates is not None:
                    merge_updates(row, missing_columns, updates)
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

        if source_column is not None:
            row[source_column] = "\n".join(sources)
        if source_raw_column is not None and sources:
            row[source_raw_column] = combine_source_raw_text(sources, source_raw_cache)

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
        )
        if progress:
            progress(index, len(rows), key)

    excluded_columns = {column for column in [source_raw_column] if column}

    if options.auto_tagging:
        tag_column = add_dynamic_column(headers, rows, "Tags")
        attribute_columns.append(tag_column)
        try:
            apply_auto_tags(
                rows,
                key_header=key_header,
                headers=headers,
                object_type=object_type,
                tag_column=tag_column,
                excluded_columns=excluded_columns,
            )
        except Exception as exc:
            failures.append(
                Failure(
                    row_number=None,
                    key="Auto Tagging",
                    columns=[tag_column],
                    raw_text=f"[Auto tagging failed] {exc}",
                    error=str(exc),
                )
            )

    if options.nearest_neighbour and tag_column is not None:
        nearest_column = add_dynamic_column(headers, rows, f"Closest {object_type.title()}")
        attribute_columns.append(nearest_column)
        try:
            apply_nearest_neighbours(
                rows,
                key_header=key_header,
                headers=headers,
                object_type=object_type,
                nearest_column=nearest_column,
                excluded_columns=excluded_columns,
            )
        except Exception as exc:
            failures.append(
                Failure(
                    row_number=None,
                    key="Nearest Neighbour",
                    columns=[nearest_column],
                    raw_text=f"[Nearest-neighbour analysis failed] {exc}",
                    error=str(exc),
                )
            )

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
    )

    return {
        "output_path": str(output_path),
        "detected_format": dataset.detected_format,
        "row_count": len(rows),
        "headers": headers,
        "question_columns": question_columns,
        "attribute_columns": attribute_columns,
    }


def run_research_table(
    raw: str,
    source_name: str = "pasted-table",
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    options: ResearchOptions | None = None,
) -> dict[str, object]:
    detected_format, headers, rows = parse_table(raw)
    dataset = make_dataset_shape(
        source_name=source_name,
        detected_format=detected_format,
        headers=headers,
        rows=rows,
    )
    return run_research_dataset(dataset, output_dir=output_dir, progress=progress, options=options)


def run_self_tests() -> None:
    assert guess_table_format("| a | b |\n| --- | --- |\n| x | y |") == "markdown"
    assert guess_table_format("a,b\nx,y") == "csv"
    headers, rows = parse_markdown_table("| name | country |\n| --- | --- |\n| Company A | DE |")
    assert headers == ["name", "country"]
    assert rows == [["Company A", "DE"]]
    headers, rows = parse_csv_table("name,country\nCompany A,DE\n")
    assert headers == ["name", "country"]
    assert rows == [["Company A", "DE"]]
    assert is_question_header("What do they do?")
    assert not is_question_header("legal form")
    assert object_type_from_header("company") == "company"
    assert object_type_from_header("company name") == "company"
    assert object_type_from_header("research_concept") == "research concept"
    assert make_explicit_question("legal form", "OpenAI", "company") == "What is the legal form of the company OpenAI?"
    headers = ["Name", "Sources", "Tags"]
    assert unique_header_name(headers, "Sources") == "Sources 2"
