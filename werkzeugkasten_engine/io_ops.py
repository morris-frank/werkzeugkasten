from __future__ import annotations

import csv
import mimetypes
import re
import traceback
import urllib.parse
from dataclasses import dataclass
from io import StringIO
from pathlib import Path
from typing import Any, Callable

import markitdown
import requests
from markitdown import MarkItDown

from .core import jina_api_key
from .field_types import is_location_header
from .openai_ops import openai_client, summary_model

HTML_BREAK_RE = re.compile(r"\s*<br\s*/?>\s*", re.IGNORECASE)
URL_RE = re.compile(r"https?://[^\s<>,)\]]+|www\.[^\s<>,)\]]+", re.IGNORECASE)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
REF_RE = re.compile(r"\s*\(Ref\s+\d+\)\s*$", re.IGNORECASE)
DOCUMENT_SUFFIXES = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".rtf",
    ".odt",
    ".ods",
    ".odp",
    ".epub",
}

__all__ = [
    "FetchResult",
    "HTML_BREAK_RE",
    "MARKDOWN_LINK_RE",
    "REF_RE",
    "URL_RE",
    "combine_source_raw_text",
    "convert_to_markdown",
    "download_source_document",
    "extract_urls",
    "fetch_source_raw_text",
    "get_stream_info",
    "group_urls_by_domain",
    "guess_table_format",
    "inferred_download_suffix",
    "is_locationish_header",
    "is_markdown_separator",
    "is_probably_document_url",
    "is_url_only",
    "normalize_headers",
    "normalize_location_value",
    "normalize_rows",
    "normalize_scalar_value",
    "normalize_source_cell_value",
    "normalize_source_urls",
    "normalize_url_value",
    "parse_csv_table",
    "parse_markdown_table",
    "parse_table",
    "replace_markdown_links_with_labels",
    "row_context_payload",
    "rows_as_dicts",
    "split_and_clean_items",
]


@dataclass
class FetchResult:
    text: str
    status_code: int | None = None
    error_class: str = ""
    message: str = ""

    @property
    def is_error(self) -> bool:
        return bool(self.error_class or self.status_code)


def get_stream_info(path: Path) -> markitdown.StreamInfo | None:
    if path.suffix.lower() in {".txt", ".text", ".md", ".markdown", ".json", ".jsonl"}:
        return markitdown.StreamInfo(charset="utf-8")
    return None


def convert_to_markdown(path: Path) -> str:
    md = MarkItDown(
        enable_builtins=True,
        enable_plugins=True,
        llm_client=openai_client(),
        model=summary_model(),
    )
    result = md.convert(str(path), stream_info=get_stream_info(path))
    text = getattr(result, "text_content", None) or str(result)
    return text.strip()


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


def inferred_download_suffix(url: str, content_type: str = "") -> str:
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix in DOCUMENT_SUFFIXES:
        return suffix
    guessed = mimetypes.guess_extension(content_type.split(";", 1)[0].strip()) if content_type else None
    return (guessed or "").lower()


def is_probably_document_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    return suffix in DOCUMENT_SUFFIXES


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


def extract_urls(text: str) -> list[str]:
    normalized_text = HTML_BREAK_RE.sub(" ", text or "")
    urls = [match.group(0) for match in URL_RE.finditer(normalized_text)]
    urls.extend(match.group(2) for match in MARKDOWN_LINK_RE.finditer(normalized_text))
    normalized = [normalize_url_value(url) for url in urls]
    return [url for url in dict.fromkeys(normalized) if url]


def normalize_source_urls(urls: list[str]) -> list[str]:
    normalized = [normalize_url_value(url) for url in urls if url.strip()]
    return sorted({url for url in normalized if url})


def normalize_source_cell_value(value: str) -> str:
    return ", ".join(normalize_source_urls(extract_urls(value)))


def replace_markdown_links_with_labels(text: str) -> str:
    return MARKDOWN_LINK_RE.sub(lambda match: match.group(1), text)


def is_url_only(text: str) -> bool:
    stripped = text.strip()
    urls = extract_urls(stripped)
    if not urls:
        return False
    candidate = stripped
    candidate = MARKDOWN_LINK_RE.sub(lambda match: match.group(2), candidate)
    candidate = re.sub(r"\((?:https?://|www\.)[^)]+\)", "", candidate).strip()
    candidate = re.sub(r"\s+", "", candidate)
    bare_urls = {url.replace("https://", "").replace("http://", "") for url in urls}
    return candidate in bare_urls or candidate in urls


def is_locationish_header(header: str) -> bool:
    return is_location_header(header)


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


def group_urls_by_domain(urls: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for url in normalize_source_urls(urls):
        domain = urllib.parse.urlparse(url).netloc or "unknown"
        grouped.setdefault(domain, []).append(url)
    return {domain: sorted(values) for domain, values in sorted(grouped.items())}


def inferred_row_context_payload(
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


def row_context_payload(
    rows: list[dict[str, str]],
    *,
    key_header: str,
    headers: list[str],
    excluded_columns: set[str],
) -> list[dict[str, object]]:
    return inferred_row_context_payload(rows, key_header=key_header, headers=headers, excluded_columns=excluded_columns)


def download_source_document(url: str, *, destination_factory: Callable[[str, str], Path]) -> Path:
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    suffix = inferred_download_suffix(url, response.headers.get("Content-Type", ""))
    destination = destination_factory(url, suffix)
    destination.write_bytes(response.content)
    return destination


def fetch_source_raw_text(
    url: str,
    cache: dict[str, FetchResult],
    *,
    document_downloader: Callable[[str], Path],
    debug_logger: Any | None = None,
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

    if is_probably_document_url(url):
        if debug_logger is not None:
            debug_logger.log("document_source_detected", row_number=row_number, key=key, source_url=url)
        try:
            downloaded_path = document_downloader(url)
            markdown = convert_to_markdown(downloaded_path)
            result = FetchResult(
                text="\n".join(
                    [
                        f"[Document content from downloaded file] {downloaded_path}",
                        "",
                        markdown,
                    ]
                ).strip()
            )
            if debug_logger is not None:
                debug_logger.log(
                    "document_source_loaded",
                    row_number=row_number,
                    key=key,
                    source_url=url,
                    downloaded_path=str(downloaded_path),
                    text_preview=result.text[:1000],
                )
            cache[url] = result
            return result
        except requests.exceptions.RequestException as exc:
            result = FetchResult(
                text=f"[Source fetch failed] {url}\n{exc}",
                error_class="DownloadError",
                message=str(exc),
            )
            if debug_logger is not None:
                debug_logger.log(
                    "document_source_download_failed",
                    row_number=row_number,
                    key=key,
                    source_url=url,
                    error_class="DownloadError",
                    message=str(exc),
                )
            cache[url] = result
            return result
        except Exception as exc:
            result = FetchResult(
                text=f"[Source fetch failed] {url}\n{exc}",
                error_class="DocumentLoadError",
                message=str(exc),
            )
            if debug_logger is not None:
                debug_logger.log(
                    "document_source_load_failed",
                    row_number=row_number,
                    key=key,
                    source_url=url,
                    error_class="DocumentLoadError",
                    message=str(exc),
                    traceback=traceback.format_exc(),
                )
            cache[url] = result
            return result

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
        safe_headers = {key_name: ("Bearer [REDACTED]" if key_name == "Authorization" else value) for key_name, value in headers.items()}
        debug_logger.log(
            "jina_request",
            row_number=row_number,
            key=key,
            source_url=url,
            request_url=request_url,
            headers=safe_headers,
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
                    status_code=response.status_code,
                    error_class="HTTPError",
                    message=reason,
                )
        else:
            body = response.text.strip()
            result = FetchResult(text=body, status_code=response.status_code)
            if debug_logger is not None:
                debug_logger.log(
                    "jina_response",
                    row_number=row_number,
                    key=key,
                    source_url=url,
                    request_url=request_url,
                    status_code=response.status_code,
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
    issues: list[Any],
    fetcher: Callable[..., FetchResult],
    summarizer: Callable[..., dict[str, Any]],
    debug_logger: Any | None = None,
) -> str:
    parts: list[str] = []
    for domain, domain_urls in group_urls_by_domain(urls).items():
        if any(is_probably_document_url(url) for url in domain_urls):
            try:
                summary_result = summarizer(
                    title=f"{domain} sources for {key}",
                    urls=domain_urls,
                )
                summary_text = str(summary_result.get("summary_markdown", "")).strip()
                if summary_text:
                    for url in domain_urls:
                        parts.append(f"URL: {url}\n{summary_text}".strip())
                if debug_logger is not None:
                    debug_logger.log(
                        "domain_summary_completed",
                        row_number=row_number,
                        key=key,
                        domain=domain,
                        source_urls=domain_urls,
                        summary_preview=summary_text[:1000],
                    )
                continue
            except Exception as exc:
                if debug_logger is not None:
                    debug_logger.log(
                        "domain_summary_failed",
                        row_number=row_number,
                        key=key,
                        domain=domain,
                        source_urls=domain_urls,
                        error=str(exc),
                        traceback=traceback.format_exc(),
                    )
        for url in domain_urls:
            raw_result = fetcher(
                url,
                cache,
                debug_logger=debug_logger,
                row_number=row_number,
                key=key,
            )
            if raw_result.is_error:
                issues.append(
                    {
                        "row_number": row_number,
                        "key": key,
                        "url": url,
                        "status_code": raw_result.status_code,
                        "error_class": raw_result.error_class,
                        "message": raw_result.message,
                    }
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
