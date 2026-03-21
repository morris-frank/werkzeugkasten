from __future__ import annotations

import csv
import json
import re
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
    openai_client,
    research_model,
    slugify,
    web_search_tool,
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


@dataclass
class Failure:
    row_number: int
    key: str
    columns: list[str]
    raw_text: str = ""
    sources: list[str] = field(default_factory=list)
    error: str = ""


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


def inspect_table(raw: str, source_name: str = "pasted-table") -> dict[str, object]:
    detected_format, headers, rows = parse_table(raw)
    question_columns = [header for header in headers[1:] if is_question_header(header)]
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
    response = client.responses.create(
        model=research_model(),
        include=["web_search_call.action.sources"],
        tools=[web_search_tool()],
        input=build_prompt(key_header, key, row, missing_columns, question_columns),
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
        normalized = {str(column): (value or "").strip() for column, value in updates.items()}
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
            lines.extend([f"### Row {failure.row_number}: {failure.key}", "", "Missing columns:"])
            lines.extend(f"- {column}" for column in failure.columns)
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


def run_research_table(
    raw: str,
    source_name: str = "pasted-table",
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
) -> dict[str, object]:
    detected_format, headers, rows = parse_table(raw)
    question_columns = [header for header in headers[1:] if is_question_header(header)]
    attribute_columns = [header for header in headers[1:] if header not in question_columns]

    started_at = datetime.now().astimezone()
    output_path = choose_output_path(started_at, build_output_label(source_name, headers), output_dir)
    failures: list[Failure] = []
    processed_rows = 0

    write_output(
        output_path,
        source_name,
        detected_format,
        headers,
        rows,
        question_columns,
        attribute_columns,
        started_at,
        processed_rows,
        failures,
    )

    key_header = headers[0]
    question_set = set(question_columns)
    for index, row in enumerate(rows, start=1):
        key = row.get(key_header, "").strip() or f"Row {index}"
        if progress:
            progress(index - 1, len(rows), key)
        missing_columns = [header for header in headers[1:] if not row.get(header, "").strip()]
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
        processed_rows = index
        write_output(
            output_path,
            source_name,
            detected_format,
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

    return {
        "output_path": str(output_path),
        "detected_format": detected_format,
        "row_count": len(rows),
        "headers": headers,
        "question_columns": question_columns,
        "attribute_columns": attribute_columns,
    }


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
    assert slugify("What does this company do?") == "what-does-this-company-do"
