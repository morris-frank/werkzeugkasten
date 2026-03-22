from __future__ import annotations

import csv
import json
import re
import traceback
import urllib.parse
from dataclasses import dataclass, field
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Callable

import requests
from rapidfuzz import fuzz

from .core import (
    choose_output_path,
    esc,
    extract_json_block,
    extract_sources,
    jina_api_key,
    notion_api_token,
    notion_parent_page,
    openai_client,
    research_model,
    response_create_kwargs,
)
from .notion_export import export_dataset_to_notion

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
MERGE_POLICY = "merge"
OVERWRITE_POLICY = "overwrite"
SOURCE_COLUMN = "Sources"
SOURCE_RAW_COLUMN = "Sources[RAW]"
TAG_COLUMN = "Tags"
RECORD_ID_COLUMN = "Record ID"
URL_RE = re.compile(r"https?://[^\s<>)\]]+|www\.[^\s<>)\]]+", re.IGNORECASE)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
REF_RE = re.compile(r"\s*\(Ref\s+\d+\)\s*$", re.IGNORECASE)
NOTION_PAGE_SIZE_LIMIT = 1800
HTML_BREAK_RE = re.compile(r"\s*<br\s*/?>\s*", re.IGNORECASE)


@dataclass(frozen=True)
class ResearchOptions:
    include_sources: bool = False
    include_source_raw: bool = False
    auto_tagging: bool = False
    nearest_neighbour: bool = False
    export_to_notion: bool = False
    output_path: str = ""
    source_column_policy: str = MERGE_POLICY
    source_raw_column_policy: str = MERGE_POLICY
    tag_column_policy: str = MERGE_POLICY
    nearest_column_policy: str = MERGE_POLICY
    record_id_column_policy: str = MERGE_POLICY

    def normalized(self) -> ResearchOptions:
        include_sources = self.include_sources or self.include_source_raw
        auto_tagging = self.auto_tagging or self.nearest_neighbour
        return ResearchOptions(
            include_sources=include_sources,
            include_source_raw=self.include_source_raw,
            auto_tagging=auto_tagging,
            nearest_neighbour=self.nearest_neighbour and auto_tagging,
            export_to_notion=self.export_to_notion,
            output_path=self.output_path.strip(),
            source_column_policy=normalize_policy(self.source_column_policy),
            source_raw_column_policy=normalize_policy(self.source_raw_column_policy),
            tag_column_policy=normalize_policy(self.tag_column_policy),
            nearest_column_policy=normalize_policy(self.nearest_column_policy),
            record_id_column_policy=normalize_policy(self.record_id_column_policy),
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
class SourceFetchIssue:
    row_number: int
    key: str
    url: str
    status_code: int | None
    error_class: str
    message: str


@dataclass
class DatasetShape:
    source_name: str
    detected_format: str
    headers: list[str]
    rows: list[dict[str, str]]
    question_columns: list[str]


@dataclass
class DynamicColumn:
    name: str
    existed: bool
    policy: str


@dataclass
class FetchResult:
    text: str
    status_code: int | None = None
    error_class: str = ""
    message: str = ""

    @property
    def is_error(self) -> bool:
        return bool(self.error_class or self.status_code)


@dataclass
class NormalizationProfile:
    list_like_columns: set[str]
    url_like_columns: set[str]
    long_text_columns: set[str]


class DebugLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def log(self, event: str, **payload: object) -> None:
        record = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "event": event,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")


def debug_log_path_for_output(path: Path) -> Path:
    suffix = "".join(path.suffixes)
    if suffix:
        return path.with_name(f"{path.name}.debug.jsonl")
    return path.with_name(f"{path.name}.debug.jsonl")


def normalize_policy(value: str) -> str:
    return OVERWRITE_POLICY if str(value).strip().lower() == OVERWRITE_POLICY else MERGE_POLICY


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
    *,
    debug_logger: DebugLogger | None = None,
    row_number: int | None = None,
) -> tuple[dict[str, str] | None, str, list[str], str]:
    key = row.get(key_header, "").strip() or "[blank]"
    prompt = build_prompt(key_header, key, row, missing_columns, question_columns)
    if debug_logger is not None:
        debug_logger.log(
            "openai_request",
            row_number=row_number,
            key=key,
            key_header=key_header,
            missing_columns=missing_columns,
            existing_values={column: value for column, value in row.items() if value.strip()},
            prompt=prompt,
        )
    client = openai_client()
    model = research_model()
    response = client.responses.create(
        input=prompt,
        **response_create_kwargs(model, use_web_search=True, include_web_sources=True),
    )
    raw_text = (response.output_text or "").strip()
    sources = normalize_source_urls(extract_sources(response))
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
        if debug_logger is not None:
            debug_logger.log(
                "openai_response_parsed",
                row_number=row_number,
                key=key,
                parsed_updates=normalized,
            )
        return normalized, raw_text, sources, ""
    except (json.JSONDecodeError, ValueError) as exc:
        if debug_logger is not None:
            debug_logger.log(
                "openai_response_parse_failed",
                row_number=row_number,
                key=key,
                error=str(exc),
                output_text=raw_text or "[No text returned]",
            )
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


def find_header_case_insensitive(headers: list[str], preferred: str) -> str | None:
    target = preferred.strip().lower()
    for header in headers:
        if header.strip().lower() == target:
            return header
    return None


def resolve_dynamic_column(headers: list[str], rows: list[dict[str, str]], preferred: str, policy: str) -> DynamicColumn:
    if preferred in headers:
        if policy == OVERWRITE_POLICY:
            for row in rows:
                row[preferred] = ""
        return DynamicColumn(name=preferred, existed=True, policy=policy)
    name = unique_header_name(headers, preferred)
    headers.append(name)
    for row in rows:
        row[name] = ""
    return DynamicColumn(name=name, existed=False, policy=policy)


def should_preserve_existing(value: str, policy: str) -> bool:
    return policy == MERGE_POLICY and bool(value.strip())


def apply_dynamic_value(row: dict[str, str], column: DynamicColumn, value: str) -> None:
    if should_preserve_existing(row.get(column.name, ""), column.policy):
        return
    row[column.name] = value


def fetch_source_raw_text(
    url: str,
    cache: dict[str, FetchResult],
    *,
    debug_logger: DebugLogger | None = None,
    row_number: int | None = None,
    key: str = "",
) -> FetchResult:
    if url in cache:
        if debug_logger is not None:
            debug_logger.log(
                "jina_fetch_cache_hit",
                row_number=row_number,
                key=key,
                source_url=url,
                cached_status_code=cache[url].status_code,
                cached_error_class=cache[url].error_class,
                cached_text_preview=cache[url].text[:500],
            )
        return cache[url]
    request_url = f"https://r.jina.ai/{url}"
    headers = {
        "X-Engine": "direct",
        "X-Retain-Images": "none",
        "X-Md-Link-Style": "referenced",
    }
    api_key = jina_api_key().strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if debug_logger is not None:
        debug_logger.log(
            "jina_request",
            row_number=row_number,
            key=key,
            source_url=url,
            request_url=request_url,
            headers=headers,
            has_authorization=bool(api_key),
        )
    try:
        response = requests.get(request_url, headers=headers, timeout=30)
    except requests.exceptions.Timeout:
        result = FetchResult(
            text=f"[Source fetch failed] {url}\nTimed out.",
            error_class="TimeoutError",
            message="Timed out.",
        )
        if debug_logger is not None:
            debug_logger.log(
                "jina_response_error",
                row_number=row_number,
                key=key,
                source_url=url,
                request_url=request_url,
                headers=headers,
                error_class="TimeoutError",
                message="Timed out.",
            )
    except requests.exceptions.RequestException as exc:
        result = FetchResult(
            text=f"[Source fetch failed] {url}\n{exc}",
            error_class="URLError",
            message=str(exc),
        )
        if debug_logger is not None:
            debug_logger.log(
                "jina_response_error",
                row_number=row_number,
                key=key,
                source_url=url,
                request_url=request_url,
                headers=headers,
                error_class="URLError",
                message=str(exc),
            )
    else:
        if response.status_code >= 400:
            reason = response.reason or ""
            result = FetchResult(
                text=f"[Source fetch failed] {url}\nHTTP {response.status_code}: {reason}",
                status_code=response.status_code,
                error_class="HTTPError",
                message=reason,
            )
            if debug_logger is not None:
                debug_logger.log(
                    "jina_response_error",
                    row_number=row_number,
                    key=key,
                    source_url=url,
                    request_url=request_url,
                    headers=headers,
                    status_code=response.status_code,
                    error_class="HTTPError",
                    message=reason,
                )
        else:
            body = response.text.strip()
            status_code = response.status_code
            result = FetchResult(text=body, status_code=status_code)
            if debug_logger is not None:
                debug_logger.log(
                    "jina_response",
                    row_number=row_number,
                    key=key,
                    source_url=url,
                    request_url=request_url,
                    headers=headers,
                    status_code=status_code,
                    text_length=len(body),
                    text_preview=body[:1000],
                )
    cache[url] = result
    return result


def combine_source_raw_text(
    urls: list[str],
    *,
    key: str,
    row_number: int,
    cache: dict[str, FetchResult],
    issues: list[SourceFetchIssue],
    debug_logger: DebugLogger | None = None,
) -> str:
    parts: list[str] = []
    for url in urls:
        raw_result = fetch_source_raw_text(
            url,
            cache,
            debug_logger=debug_logger,
            row_number=row_number,
            key=key,
        )
        if raw_result.is_error:
            issues.append(
                SourceFetchIssue(
                    row_number=row_number,
                    key=key,
                    url=url,
                    status_code=raw_result.status_code,
                    error_class=raw_result.error_class,
                    message=raw_result.message,
                )
            )
            if debug_logger is not None:
                debug_logger.log(
                    "source_fetch_issue",
                    row_number=row_number,
                    key=key,
                    source_url=url,
                    status_code=raw_result.status_code,
                    error_class=raw_result.error_class,
                    message=raw_result.message,
                )
        parts.append(f"URL: {url}\n{raw_result.text}".strip())
    if debug_logger is not None:
        debug_logger.log(
            "source_raw_combined",
            row_number=row_number,
            key=key,
            source_count=len(urls),
            combined_length=sum(len(part) for part in parts),
        )
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


def run_json_prompt(
    prompt: str,
    *,
    debug_logger: DebugLogger | None = None,
    prompt_kind: str = "json_prompt",
) -> dict[str, object]:
    client = openai_client()
    model = research_model()
    if debug_logger is not None:
        debug_logger.log("openai_aux_request", prompt_kind=prompt_kind, prompt=prompt)
    response = client.responses.create(
        input=prompt,
        **response_create_kwargs(model),
    )
    raw_text = (response.output_text or "").strip()
    if debug_logger is not None:
        debug_logger.log(
            "openai_aux_response",
            prompt_kind=prompt_kind,
            model=model,
            output_text=raw_text,
        )
    try:
        data = json.loads(extract_json_block(raw_text))
        if not isinstance(data, dict):
            raise ValueError("Expected a JSON object.")
        if debug_logger is not None:
            debug_logger.log("openai_aux_response_parsed", prompt_kind=prompt_kind, data=data)
        return data
    except (json.JSONDecodeError, ValueError) as exc:
        if debug_logger is not None:
            debug_logger.log(
                "openai_aux_response_parse_failed",
                prompt_kind=prompt_kind,
                error=str(exc),
                output_text=raw_text,
            )
        raise ValueError(f"Structured validation failed: {exc}") from exc


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
    skipped_rows: list[str],
    source_fetch_issues: list[SourceFetchIssue],
    notion_export_result: dict[str, object] | None,
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
    if notion_export_result:
        lines.extend(
            [
                "",
                "## Notion Export",
                "",
                f"- Database ID: {notion_export_result.get('database_id', '')}",
                f"- Data Source ID: {notion_export_result.get('data_source_id', '')}",
                f"- URL: {notion_export_result.get('database_url', '') or 'not returned'}",
            ]
        )
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
    skipped_rows: list[str],
    source_fetch_issues: list[SourceFetchIssue],
    notion_export_result: dict[str, object] | None,
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
            skipped_rows=skipped_rows,
            source_fetch_issues=source_fetch_issues,
            notion_export_result=notion_export_result,
        ),
        encoding="utf-8",
    )


def normalize_dataset(
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    key_header: str,
    question_columns: list[str],
    source_column: str | None,
    source_raw_column: str | None,
    tag_column: str | None,
    nearest_column: str | None,
) -> NormalizationProfile:
    url_like_columns = detect_url_like_columns(headers, rows, source_column=source_column)
    list_like_columns = detect_list_like_columns(
        headers,
        rows,
        question_columns=question_columns,
        known_columns={column for column in [source_column, tag_column, nearest_column] if column},
    )
    long_text_columns = detect_long_text_columns(headers, rows, source_raw_column=source_raw_column)

    canonical_maps: dict[str, dict[str, str]] = {}
    for header in headers:
        if header == key_header:
            continue
        if header in long_text_columns or header in question_columns or is_locationish_header(header):
            continue
        observed_items: list[str] = []
        for row in rows:
            value = row.get(header, "").strip()
            if not value:
                continue
            items = split_and_clean_items(value, url_mode=header in url_like_columns)
            observed_items.extend(items if header in list_like_columns or header in url_like_columns else items[:1])
        canonical_maps[header] = build_canonical_map(observed_items, url_mode=header in url_like_columns)

    for row in rows:
        for header in headers:
            if header == key_header:
                continue
            value = row.get(header, "").strip()
            if not value:
                continue
            if header in long_text_columns:
                row[header] = value.strip()
                continue
            if is_locationish_header(header):
                row[header] = normalize_location_value(value)
                continue
            if header in url_like_columns:
                items = split_and_clean_items(value, url_mode=True)
                row[header] = ",".join(canonical_maps.get(header, {}).get(item, item) for item in items)
                continue
            if header in list_like_columns:
                items = split_and_clean_items(value, url_mode=False)
                mapped = [canonical_maps.get(header, {}).get(item, item) for item in items]
                row[header] = ",".join(dict.fromkeys(mapped))
                continue
            normalized_scalar = normalize_scalar_value(value)
            row[header] = canonical_maps.get(header, {}).get(normalized_scalar, normalized_scalar)

    return NormalizationProfile(
        list_like_columns=list_like_columns,
        url_like_columns=url_like_columns,
        long_text_columns=long_text_columns,
    )


def detect_url_like_columns(headers: list[str], rows: list[dict[str, str]], *, source_column: str | None) -> set[str]:
    result: set[str] = set()
    if source_column:
        result.add(source_column)
    for header in headers[1:]:
        if is_locationish_header(header):
            continue
        values = [row.get(header, "").strip() for row in rows if row.get(header, "").strip()]
        if not values:
            continue
        sample = values[:25]
        score = sum(1 for value in sample if is_url_only(value))
        if score and score == len(sample):
            result.add(header)
    return result


def detect_list_like_columns(
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    question_columns: list[str],
    known_columns: set[str],
) -> set[str]:
    result = set(known_columns)
    for header in headers[1:]:
        if header in question_columns or is_locationish_header(header):
            continue
        values = [row.get(header, "").strip() for row in rows if row.get(header, "").strip()]
        if not values:
            continue
        delimiter_hits = sum(1 for value in values[:25] if re.search(r"\s*(?:/|\+|,|;)\s*", value))
        if delimiter_hits >= max(2, len(values[:25]) // 3):
            result.add(header)
    return result


def detect_long_text_columns(headers: list[str], rows: list[dict[str, str]], *, source_raw_column: str | None) -> set[str]:
    result: set[str] = set()
    if source_raw_column:
        result.add(source_raw_column)
    for header in headers[1:]:
        values = [row.get(header, "").strip() for row in rows if row.get(header, "").strip()]
        if not values:
            continue
        avg_length = sum(len(value) for value in values[:25]) / len(values[:25])
        multiline = any("\n" in value for value in values[:25])
        if avg_length > 180 or multiline:
            result.add(header)
    return result


def build_canonical_map(values: list[str], *, url_mode: bool) -> dict[str, str]:
    canonical_map: dict[str, str] = {}
    canonicals: list[str] = []
    for value in values:
        candidate = normalize_url_value(value) if url_mode else normalize_scalar_value(value)
        if not candidate:
            continue
        match = best_canonical(candidate, canonicals)
        if match is None:
            canonicals.append(candidate)
            canonical_map[candidate] = candidate
            continue
        canonical_map[candidate] = match
    return canonical_map


def best_canonical(candidate: str, canonicals: list[str]) -> str | None:
    lowered = candidate.lower()
    for canonical in canonicals:
        if canonical.lower() == lowered:
            return canonical
    best_score = 0.0
    best_value: str | None = None
    for canonical in canonicals:
        score = fuzz.ratio(candidate.lower(), canonical.lower())
        if score > best_score:
            best_score = score
            best_value = canonical
    if best_score >= 92:
        return best_value
    return None


def split_and_clean_items(value: str, *, url_mode: bool) -> list[str]:
    if url_mode:
        urls = normalize_source_urls(extract_urls(value))
        return [url for url in dict.fromkeys(urls) if url]
    working = HTML_BREAK_RE.sub(",", value)
    working = replace_markdown_links_with_labels(working)
    working = REF_RE.sub("", working)
    working = re.sub(r"\((?:https?://|www\.)[^)]+\)", "", working)
    working = re.sub(r"\([^)]*\.[^)]*\)", "", working)
    working = re.sub(r"\s*(?:/|\+|;)\s*", ",", working)
    working = re.sub(r"\s*,\s*", ",", working.strip())
    parts = [normalize_scalar_value(part) for part in working.split(",")]
    return [part for part in dict.fromkeys(parts) if part]


def normalize_scalar_value(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    if is_url_only(text):
        urls = extract_urls(text)
        if urls:
            return normalize_url_value(urls[0])
    text = replace_markdown_links_with_labels(text)
    text = REF_RE.sub("", text)
    text = re.sub(r"\((?:https?://|www\.)[^)]+\)", "", text).strip()
    text = re.sub(r"\([^)]*\.[^)]*\)", "", text).strip()
    text = re.sub(r"\s+", " ", text)

    cookbook = {
        "operational": "Operational",
        "recs": "Recommendation",
        "species lists": "Species lists",
        "metrics": "Metrics",
        "shotgun": "Shotgun",
        "env assets": "env assets",
    }
    lowered = text.lower()
    if lowered in cookbook:
        return cookbook[lowered]
    if lowered == "recs+env assets":
        return "Recommendation,env assets"
    if re.fullmatch(r"[A-Z0-9]{2,}", text):
        return text
    if text.islower() and len(text.split()) <= 4:
        return " ".join(word if word.isupper() else word.capitalize() for word in text.split())
    return text


def normalize_location_value(value: str) -> str:
    text = value.strip()
    text = replace_markdown_links_with_labels(text)
    text = re.sub(r"\((?:https?://|www\.)[^)]+\)", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def replace_markdown_links_with_labels(text: str) -> str:
    return MARKDOWN_LINK_RE.sub(lambda match: match.group(1), text)


def extract_urls(text: str) -> list[str]:
    normalized_text = HTML_BREAK_RE.sub(" ", text or "")
    urls = [match.group(0) for match in URL_RE.finditer(normalized_text)]
    urls.extend(match.group(2) for match in MARKDOWN_LINK_RE.finditer(normalized_text))
    normalized = [normalize_url_value(url) for url in urls]
    return [url for url in dict.fromkeys(normalized) if url]


def normalize_source_urls(urls: list[str]) -> list[str]:
    normalized = [normalize_url_value(url) for url in urls if url.strip()]
    return sorted({url for url in normalized if url})


def is_url_only(text: str) -> bool:
    stripped = text.strip()
    urls = extract_urls(stripped)
    if not urls:
        return False
    candidate = stripped
    candidate = MARKDOWN_LINK_RE.sub(lambda match: match.group(2), candidate)
    candidate = re.sub(r"\((?:https?://|www\.)[^)]+\)", "", candidate).strip()
    candidate = re.sub(r"\s+", "", candidate)
    return candidate in {url.replace("https://", "").replace("http://", "") for url in urls} or candidate in urls


def is_locationish_header(header: str) -> bool:
    lowered = header.strip().lower()
    return any(token in lowered for token in ["location", "address", "adress", "city", "country", "region", "state"])


def normalize_url_value(value: str) -> str:
    text = value.strip().strip("[]()")
    if not text:
        return ""
    if text.startswith("www."):
        text = f"https://{text}"
    elif not re.match(r"^[a-z]+://", text, re.IGNORECASE):
        text = f"https://{text}"
    parsed = urllib.parse.urlparse(text)
    host = parsed.netloc.lower()
    path = parsed.path or ""
    query_pairs = urllib.parse.parse_qsl(parsed.query, keep_blank_values=False)
    filtered_query = [
        (key, val)
        for key, val in query_pairs
        if not key.lower().startswith("utm_") and "openai" not in key.lower() and "openai" not in val.lower()
    ]
    query = urllib.parse.urlencode(filtered_query)
    rebuilt = urllib.parse.urlunparse(("https", host, path.rstrip("/"), "", query, ""))
    return rebuilt.rstrip("/") if rebuilt.endswith("/") and path in {"", "/"} else rebuilt


def generate_record_id(key: str, row_index: int) -> str:
    safe = re.sub(r"[^a-z0-9]+", "-", key.strip().lower()).strip("-")
    if not safe:
        safe = f"row-{row_index}"
    return f"{safe}-{row_index}"


def source_urls_from_row(row: dict[str, str], source_column_name: str | None) -> list[str]:
    if not source_column_name:
        return []
    return normalize_source_urls(extract_urls(row.get(source_column_name, "")))


def merge_source_lists(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for url in group:
            if url and url not in merged:
                merged.append(url)
    return merged


def run_research_dataset(
    dataset: DatasetShape,
    *,
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    options: ResearchOptions | None = None,
) -> dict[str, object]:
    options = (options or ResearchOptions()).normalized()
    if options.export_to_notion:
        if not notion_api_token().strip():
            raise ValueError("Set a Notion API Token in Settings before exporting to Notion.")
        if not notion_parent_page().strip():
            raise ValueError("Set a Notion Parent Page ID or URL in Settings before exporting to Notion.")

    headers = list(dataset.headers)
    rows = [dict(row) for row in dataset.rows]
    question_columns = [column for column in dataset.question_columns if column in headers[1:]]
    attribute_columns = [header for header in headers[1:] if header not in question_columns]
    key_header = headers[0]
    object_type = object_type_from_header(key_header)

    source_column: DynamicColumn | None = None
    source_raw_column: DynamicColumn | None = None
    tag_column: DynamicColumn | None = None
    nearest_column: DynamicColumn | None = None
    record_id_column: DynamicColumn | None = None

    existing_source_header = find_header_case_insensitive(headers, SOURCE_COLUMN)
    existing_source_raw_header = find_header_case_insensitive(headers, SOURCE_RAW_COLUMN)

    if options.include_sources:
        source_column = resolve_dynamic_column(headers, rows, SOURCE_COLUMN, options.source_column_policy)
        if source_column.name not in attribute_columns:
            attribute_columns.append(source_column.name)
    elif existing_source_header is not None:
        source_column = DynamicColumn(name=existing_source_header, existed=True, policy=MERGE_POLICY)
    if options.include_source_raw:
        source_raw_column = resolve_dynamic_column(headers, rows, SOURCE_RAW_COLUMN, options.source_raw_column_policy)
        if source_raw_column.name not in attribute_columns:
            attribute_columns.append(source_raw_column.name)
    elif existing_source_raw_header is not None:
        source_raw_column = DynamicColumn(name=existing_source_raw_header, existed=True, policy=MERGE_POLICY)

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

    debug_logger.log(
        "dataset_started",
        source_name=dataset.source_name,
        detected_format=dataset.detected_format,
        output_path=str(output_path),
        debug_log_path=str(debug_log_path),
        headers=headers,
        row_count=len(rows),
        question_columns=question_columns,
        attribute_columns=attribute_columns,
        options={
            "include_sources": options.include_sources,
            "include_source_raw": options.include_source_raw,
            "auto_tagging": options.auto_tagging,
            "nearest_neighbour": options.nearest_neighbour,
            "export_to_notion": options.export_to_notion,
            "output_path": options.output_path,
            "source_column_policy": options.source_column_policy,
            "source_raw_column_policy": options.source_raw_column_policy,
            "tag_column_policy": options.tag_column_policy,
            "nearest_column_policy": options.nearest_column_policy,
            "record_id_column_policy": options.record_id_column_policy,
        },
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
        processed_rows,
        failures,
        skipped_rows,
        source_fetch_issues,
        notion_export_result,
    )
    debug_logger.log("markdown_written", path=str(output_path), processed_rows=processed_rows)

    question_set = set(question_columns)
    excluded_research_columns = {column.name for column in [source_column, source_raw_column] if column is not None}
    if options.auto_tagging:
        excluded_research_columns.add(TAG_COLUMN)
    if options.nearest_neighbour:
        excluded_research_columns.add(f"Closest {object_type.title()}")
    if options.export_to_notion:
        excluded_research_columns.add(RECORD_ID_COLUMN)
    research_columns = [header for header in dataset.headers[1:] if header not in excluded_research_columns]
    debug_logger.log(
        "research_columns_resolved",
        research_columns=research_columns,
        excluded_research_columns=sorted(excluded_research_columns),
        source_column=source_column.name if source_column else "",
        source_raw_column=source_raw_column.name if source_raw_column else "",
    )
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

        effective_sources = merge_source_lists(existing_sources, sources)
        if source_column is not None and effective_sources:
            if not should_preserve_existing(row.get(source_column.name, ""), source_column.policy):
                row[source_column.name] = ", ".join(effective_sources)
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
    assert unique_header_name(["Name", "Sources"], "Sources") == "Sources 2"
    assert split_and_clean_items("water/air/soil", url_mode=False) == ["Water", "Air", "Soil"]
    assert split_and_clean_items("shotgun+16S/18S+LR", url_mode=False) == ["Shotgun", "16S", "18S", "LR"]
    assert normalize_url_value("[mywebsite.com](http://mywebsite.com)".replace("[", "").replace("]", "")) == "https://mywebsite.com"
