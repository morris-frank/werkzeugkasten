from __future__ import annotations

import copy
import json
import os
import re
import urllib.parse
from dataclasses import dataclass
from typing import Any

import requests

from .geocoding import geocode_place
from .value import as_urls, is_location_type


def _notion_api_token() -> str:
    return (
        os.environ.get("WERKZEUGKASTEN_NOTION_API_TOKEN", "")
        or os.environ.get("NOTION_API_TOKEN", "")
        or os.environ.get("NOTION_TOKEN", "")
    )


def _notion_parent_page() -> str:
    return os.environ.get("WERKZEUGKASTEN_NOTION_PARENT_PAGE", "") or os.environ.get("NOTION_PARENT_PAGE", "")


NOTION_API_BASE = "https://api.notion.com/v1"
LATEST_NOTION_VERSION = "2026-03-11"
# Notion rejects bodies around ~500KB; stay well under once JSON-escaped UTF-8 is applied.
NOTION_REQUEST_BODY_SAFE_MAX_BYTES = 420_000
NOTION_ABBREVIATION_NOTE = "\n\n_(Abbreviated for Notion export size limit.)_"
UUID_RE = re.compile(r"([0-9a-fA-F]{32}|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})")


@dataclass(frozen=True)
class NotionColumnSpec:
    name: str
    kind: str
    target_name: str | None = None
    property_definition: dict[str, Any] | None = None


def normalize_notion_id(value: str) -> str:
    match = UUID_RE.search(value or "")
    if not match:
        raise ValueError("Notion parent page must be a page URL or UUID.")
    raw = match.group(1).replace("-", "").lower()
    return f"{raw[0:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:32]}"


def notion_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": LATEST_NOTION_VERSION,
        "Content-Type": "application/json",
    }


def notion_request(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    token = _notion_api_token().strip()
    if not token:
        raise ValueError("Set a Notion API Token in Settings to export to Notion.")
    url = f"{NOTION_API_BASE}{path}"
    try:
        response = requests.request(
            method,
            url,
            headers=notion_headers(token),
            json=body,
            timeout=60,
        )
    except requests.exceptions.RequestException as exc:
        raise RuntimeError(f"Notion API request failed: {exc}") from exc
    if response.status_code >= 400:
        payload = response.text.strip()
        if payload:
            try:
                detail = json.loads(payload)
                message = detail.get("message") or payload
            except json.JSONDecodeError:
                message = payload
        else:
            message = response.reason or ""
        raise RuntimeError(f"Notion API {response.status_code}: {message}")
    return response.json()


def page_parent_id() -> str:
    configured = _notion_parent_page().strip()
    if not configured:
        raise ValueError("Set a Notion Parent Page ID or URL in Settings to export to Notion.")
    return normalize_notion_id(configured)


def notion_request_json_byte_length(body: dict[str, Any]) -> int:
    return len(json.dumps(body, ensure_ascii=True).encode("utf-8"))


def truncate_utf8_bytes(text: str, max_bytes: int) -> str:
    if max_bytes <= 0:
        return ""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    truncated = encoded[:max_bytes]
    while truncated and (truncated[-1] & 0b1100_0000) == 0b1000_0000:
        truncated = truncated[:-1]
    return truncated.decode("utf-8", errors="ignore")


def parse_source_raw_ordered(value: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for part in [part.strip() for part in re.split(r"\n(?=URL:\s)", value or "") if part.strip()]:
        lines = part.splitlines()
        if not lines:
            continue
        url = lines[0].replace("URL:", "").strip()
        body = "\n".join(lines[1:]).strip()
        if url:
            pairs.append((url, body))
    return pairs


def format_sources_raw(pairs: list[tuple[str, str]]) -> str:
    return "\n\n".join(f"URL: {url}\n{body}" for url, body in pairs)


def iter_row_child_documents(
    row: dict[str, str],
    long_text_columns: set[str],
    sources_column: str | None,
    source_raw_column: str | None,
) -> list[tuple[str, str]]:
    segments: list[tuple[str, str]] = []
    if sources_column and row.get(sources_column, "").strip():
        source_urls = as_urls(row[sources_column])
        raw_map = parse_source_raw_map(row.get(source_raw_column, "")) if source_raw_column else {}
        for _domain, urls in group_urls_by_domain(source_urls).items():
            for url in urls:
                raw_body = raw_map.get(url, "")
                if raw_body:
                    segments.append((f"raw:{url}", raw_body))
    for column in sorted(long_text_columns):
        value = row.get(column, "").strip()
        if not value:
            continue
        if column == source_raw_column:
            continue
        segments.append((f"col:{column}", value))
    return segments


def apply_segment_texts_to_row(
    base_row: dict[str, str],
    segment_texts: dict[str, str],
    *,
    source_raw_column: str | None,
) -> dict[str, str]:
    row = dict(base_row)
    for key, text in segment_texts.items():
        if key.startswith("col:"):
            row[key[4:]] = text
    if source_raw_column:
        ordered = parse_source_raw_ordered(base_row.get(source_raw_column, ""))
        new_pairs: list[tuple[str, str]] = []
        for url, body in ordered:
            sid = f"raw:{url}"
            if sid in segment_texts:
                new_pairs.append((url, segment_texts[sid]))
            else:
                new_pairs.append((url, body))
        row[source_raw_column] = format_sources_raw(new_pairs)
    return row


def _shrink_property_values_for_request_size(properties: dict[str, Any]) -> dict[str, Any]:
    """Last resort when database properties alone exceed the safe limit (rare)."""

    def halve_rich_text_chunks(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            text_obj = item.get("text")
            if isinstance(text_obj, dict) and "content" in text_obj:
                content = text_obj["content"]
                if isinstance(content, str) and content:
                    new_item = copy.deepcopy(item)
                    new_item["text"]["content"] = truncate_utf8_bytes(content, max(0, len(content.encode("utf-8")) // 2))
                    out.append(new_item)
                else:
                    out.append(copy.deepcopy(item))
            else:
                out.append(copy.deepcopy(item))
        return out

    shrunk: dict[str, Any] = {}
    for name, payload in properties.items():
        if not isinstance(payload, dict):
            shrunk[name] = copy.deepcopy(payload)
            continue
        p = copy.deepcopy(payload)
        if "title" in p and isinstance(p["title"], list):
            p["title"] = halve_rich_text_chunks(p["title"])
        if "rich_text" in p and isinstance(p["rich_text"], list):
            p["rich_text"] = halve_rich_text_chunks(p["rich_text"])
        shrunk[name] = p
    return shrunk


def ensure_notion_safe_create_page_body(
    create_page_body: dict[str, Any],
    row: dict[str, str],
    long_text_columns: set[str],
    sources_column: str | None,
    source_raw_column: str | None,
) -> dict[str, Any]:
    if notion_request_json_byte_length(create_page_body) <= NOTION_REQUEST_BODY_SAFE_MAX_BYTES:
        return create_page_body

    parent = create_page_body.get("parent")
    properties = create_page_body.get("properties") or {}
    base_only: dict[str, Any] = {"parent": parent, "properties": properties}
    for _ in range(96):
        if notion_request_json_byte_length(base_only) <= NOTION_REQUEST_BODY_SAFE_MAX_BYTES:
            break
        prev = notion_request_json_byte_length(base_only)
        properties = _shrink_property_values_for_request_size(properties)
        base_only = {"parent": parent, "properties": properties}
        if notion_request_json_byte_length(base_only) >= prev:
            break

    segments = iter_row_child_documents(row, long_text_columns, sources_column, source_raw_column)
    if not segments:
        out: dict[str, Any] = {"parent": parent, "properties": properties}
        children = render_row_children(row, long_text_columns, sources_column, source_raw_column)
        if children:
            out["children"] = children
        while notion_request_json_byte_length(out) > NOTION_REQUEST_BODY_SAFE_MAX_BYTES and out.get("children"):
            out.pop("children", None)
        return out

    sizes = [len(text.encode("utf-8")) for _, text in segments]

    def build_at_scale(scale: float) -> dict[str, Any]:
        segment_texts: dict[str, str] = {}
        for (seg_id, text), size in zip(segments, sizes):
            if size == 0:
                segment_texts[seg_id] = text
                continue
            limit = int(scale * size)
            if limit >= size:
                segment_texts[seg_id] = text
            else:
                truncated = truncate_utf8_bytes(text, limit)
                if len(truncated.encode("utf-8")) < size:
                    segment_texts[seg_id] = truncated + NOTION_ABBREVIATION_NOTE
                else:
                    segment_texts[seg_id] = text
        adjusted_row = apply_segment_texts_to_row(row, segment_texts, source_raw_column=source_raw_column)
        children = render_row_children(adjusted_row, long_text_columns, sources_column, source_raw_column)
        trial: dict[str, Any] = {"parent": parent, "properties": properties}
        if children:
            trial["children"] = children
        return trial

    low, high = 0.0, 1.0
    best_trial: dict[str, Any] | None = None
    for _ in range(56):
        mid = (low + high) / 2.0
        trial = build_at_scale(mid)
        if notion_request_json_byte_length(trial) <= NOTION_REQUEST_BODY_SAFE_MAX_BYTES:
            best_trial = trial
            low = mid
        else:
            high = mid

    trial = best_trial if best_trial is not None else build_at_scale(0.0)
    scale = low
    while notion_request_json_byte_length(trial) > NOTION_REQUEST_BODY_SAFE_MAX_BYTES and scale > 1e-12:
        scale *= 0.88
        trial = build_at_scale(scale)
    return trial


def rich_text_array(text: str, *, max_chars: int = 1800) -> list[dict[str, Any]]:
    if not text:
        return []
    chunks = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
    return [{"type": "text", "text": {"content": chunk}} for chunk in chunks[:100]]


def linked_rich_text(url: str, label: str | None = None) -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": {
                "content": label or url,
                "link": {"url": url},
            },
        }
    ]


def infer_column_specs(
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    key_header: str,
    sources_column: str | None,
    tags_column: str | None,
    nearest_column: str | None,
    record_id_column: str | None,
    list_like_columns: set[str],
    url_like_columns: set[str],
    long_text_columns: set[str],
) -> list[NotionColumnSpec]:
    specs: list[NotionColumnSpec] = []
    for header in headers:
        if header == key_header:
            specs.append(NotionColumnSpec(name=header, kind="title", property_definition={"title": {}}))
            continue
        if header == nearest_column:
            specs.append(NotionColumnSpec(name=header, kind="relation"))
            continue
        if header in long_text_columns:
            continue
        if header == record_id_column:
            continue
        if header == sources_column:
            specs.append(NotionColumnSpec(name=header, kind="rich_text", property_definition={"rich_text": {}}))
            continue
        values = [row.get(header, "").strip() for row in rows if row.get(header, "").strip()]
        if not values:
            specs.append(NotionColumnSpec(name=header, kind="rich_text", property_definition={"rich_text": {}}))
            continue
        if is_location_type(header):
            sample = values[:25]
            parseable = sum(1 for value in sample if geocode_place(value) is not None)
            if parseable and parseable >= max(1, len(sample) // 2):
                specs.append(NotionColumnSpec(name=header, kind="place", property_definition={"place": {}}))
            else:
                specs.append(NotionColumnSpec(name=header, kind="rich_text", property_definition={"rich_text": {}}))
            continue
        if header in url_like_columns and all(value.startswith(("http://", "https://")) for value in values[:25]):
            specs.append(NotionColumnSpec(name=header, kind="url", property_definition={"url": {}}))
            continue
        if all(_looks_numeric(value) for value in values[:25]):
            specs.append(NotionColumnSpec(name=header, kind="number", property_definition={"number": {"format": "number"}}))
            continue
        if header == tags_column or header in list_like_columns:
            specs.append(NotionColumnSpec(name=header, kind="multi_select", property_definition={"multi_select": {"options": []}}))
            continue
        unique_values = sorted({value for value in values if value})
        if 1 < len(unique_values) <= min(20, max(8, len(rows) // 2)) and max(len(value) for value in unique_values) <= 64:
            specs.append(NotionColumnSpec(name=header, kind="select", property_definition={"select": {"options": []}}))
            continue
        specs.append(NotionColumnSpec(name=header, kind="rich_text", property_definition={"rich_text": {}}))
    return specs


def _looks_numeric(value: str) -> bool:
    try:
        float(value.replace(",", ""))
    except ValueError:
        return False
    return True


def _property_value(
    spec: NotionColumnSpec,
    value: str,
) -> dict[str, Any] | None:
    if not value:
        return None
    if spec.kind == "title":
        return {"title": rich_text_array(value)}
    if spec.kind == "rich_text":
        return {"rich_text": rich_text_array(value)}
    if spec.kind == "number":
        try:
            return {"number": float(value.replace(",", ""))}
        except ValueError:
            return {"rich_text": rich_text_array(value)}
    if spec.kind == "url":
        return {"url": value}
    if spec.kind == "place":
        place = geocode_place(value)
        return {"place": place} if place else None
    if spec.kind == "select":
        return {"select": {"name": value[:100]}}
    if spec.kind == "multi_select":
        options = [{"name": item[:100]} for item in split_multi_value(value)]
        return {"multi_select": options}
    if spec.kind == "relation":
        return {"relation": []}
    return {"rich_text": rich_text_array(value)}


def split_multi_value(value: str) -> list[str]:
    normalized = re.sub(r"\s*<br\s*/?>\s*", ",", value, flags=re.IGNORECASE)
    items = [item.strip() for item in normalized.split(",")]
    result: list[str] = []
    for item in items:
        if item and item not in result:
            result.append(item)
    return result


def heading_block(text: str, level: int = 2) -> dict[str, Any]:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": rich_text_array(text, max_chars=180)}}


def paragraph_block(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": rich_text_array(text)}}


def bulleted_block(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": rich_text_array(text, max_chars=180)}}


def linked_bulleted_block(url: str) -> dict[str, Any]:
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": linked_rich_text(url)}}


def toggle_block(title: str, children: list[dict[str, Any]], *, url: str | None = None) -> dict[str, Any]:
    rich_text = linked_rich_text(url, title) if url else rich_text_array(title, max_chars=180)
    return {
        "object": "block",
        "type": "toggle",
        "toggle": {
            "rich_text": rich_text,
            "children": children[:50],
        },
    }


def render_row_children(
    row: dict[str, str], long_text_columns: set[str], sources_column: str | None, source_raw_column: str | None
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if sources_column and row.get(sources_column, "").strip():
        blocks.append(heading_block("Sources", level=2))
        source_urls = as_urls(row[sources_column])
        raw_map = parse_source_raw_map(row.get(source_raw_column, "")) if source_raw_column else {}
        for domain, urls in group_urls_by_domain(source_urls).items():
            blocks.append(heading_block(domain, level=3))
            for url in urls:
                raw_body = raw_map.get(url, "")
                if raw_body:
                    children = [paragraph_block(chunk) for chunk in _chunk_text(raw_body)]
                    blocks.append(toggle_block(url, children, url=url))
                else:
                    blocks.append(linked_bulleted_block(url))
    for column in sorted(long_text_columns):
        value = row.get(column, "").strip()
        if not value:
            continue
        if column == source_raw_column:
            continue
        blocks.append(heading_block(column, level=2))
        for chunk in _chunk_text(value):
            blocks.append(paragraph_block(chunk))
    return blocks[:100]


def group_urls_by_domain(urls: list[str]) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for url in urls:
        domain = urllib.parse.urlparse(url).netloc or "unknown"
        grouped.setdefault(domain, []).append(url)
    return grouped


def parse_source_raw_map(value: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for part in [part.strip() for part in re.split(r"\n(?=URL:\s)", value or "") if part.strip()]:
        lines = part.splitlines()
        if not lines:
            continue
        url = lines[0].replace("URL:", "").strip()
        body = "\n".join(lines[1:]).strip()
        if url:
            mapping[url] = body
    return mapping


def _chunk_text(text: str, limit: int = 1800) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    cursor = 0
    while cursor < len(text):
        end = min(len(text), cursor + limit)
        if end < len(text):
            candidate = text.rfind("\n", cursor, end)
            if candidate > cursor + limit // 2:
                end = candidate
        chunks.append(text[cursor:end].strip())
        cursor = end
    return [chunk for chunk in chunks if chunk]


def export_dataset_to_notion(
    *,
    title: str,
    headers: list[str],
    rows: list[dict[str, str]],
    key_header: str,
    sources_column: str | None,
    source_raw_column: str | None,
    tags_column: str | None,
    nearest_column: str | None,
    record_id_column: str | None,
    list_like_columns: set[str],
    url_like_columns: set[str],
    long_text_columns: set[str],
) -> dict[str, Any]:
    parent_page_id = page_parent_id()
    specs = infer_column_specs(
        headers,
        rows,
        key_header=key_header,
        sources_column=sources_column,
        tags_column=tags_column,
        nearest_column=nearest_column,
        record_id_column=record_id_column,
        list_like_columns=list_like_columns,
        url_like_columns=url_like_columns,
        long_text_columns=long_text_columns,
    )

    properties = {spec.name: spec.property_definition for spec in specs if spec.property_definition is not None}

    create_body = {
        "parent": {"type": "page_id", "page_id": parent_page_id},
        "title": rich_text_array(title[:180]),
        "initial_data_source": {
            "title": rich_text_array(title[:180]),
            "properties": properties,
        },
    }
    database = notion_request("POST", "/databases", create_body)
    database_id = database.get("id")
    if not database_id:
        raise RuntimeError("Notion did not return a database ID.")

    data_source_id = ((database.get("initial_data_source") or {}).get("id")) or _extract_first_data_source_id(
        notion_request("GET", f"/databases/{database_id}")
    )
    if not data_source_id:
        raise RuntimeError("Could not determine the Notion data source ID for the new database.")

    if nearest_column:
        notion_request(
            "PATCH",
            f"/data_sources/{data_source_id}",
            {
                "properties": {
                    nearest_column: {
                        "relation": {
                            "data_source_id": data_source_id,
                            "single_property": {},
                        }
                    }
                }
            },
        )

    pages_by_record_id: dict[str, str] = {}
    page_ids_by_key: dict[str, str] = {}
    row_specs = {spec.name: spec for spec in specs}
    geocode_cache: dict[str, dict[str, Any] | None] = {}
    for row in rows:
        properties_payload: dict[str, Any] = {}
        for header, spec in row_specs.items():
            if spec.kind == "relation":
                continue
            value = row.get(header, "").strip()
            property_value = _property_value(
                spec,
                value,
                geocode_cache=geocode_cache,
            )
            if property_value is not None:
                properties_payload[header] = property_value
        create_page_body = {
            "parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "properties": properties_payload,
        }
        children = render_row_children(row, long_text_columns, sources_column, source_raw_column)
        if children:
            create_page_body["children"] = children
        create_page_body = ensure_notion_safe_create_page_body(
            create_page_body,
            row,
            long_text_columns,
            sources_column,
            source_raw_column,
        )
        page = notion_request("POST", "/pages", create_page_body)
        page_id = page.get("id")
        record_id = row.get(record_id_column or "", "").strip()
        key_value = row.get(key_header, "").strip()
        if page_id and record_id:
            pages_by_record_id[record_id] = page_id
        if page_id and key_value:
            page_ids_by_key[key_value] = page_id

    if nearest_column and record_id_column:
        for row in rows:
            page_id = pages_by_record_id.get(row.get(record_id_column, "").strip())
            if not page_id:
                continue
            relation_ids = [
                {"id": pages_by_record_id[item]} for item in split_multi_value(row.get(nearest_column, "")) if item in pages_by_record_id
            ]
            if not relation_ids:
                relation_ids = [
                    {"id": page_ids_by_key[item]} for item in split_multi_value(row.get(nearest_column, "")) if item in page_ids_by_key
                ]
            if not relation_ids:
                continue
            notion_request(
                "PATCH",
                f"/pages/{page_id}",
                {"properties": {nearest_column: {"relation": relation_ids}}},
            )

    return {
        "database_id": database_id,
        "data_source_id": data_source_id,
        "database_url": database.get("url", ""),
        "row_count": len(rows),
    }


def _extract_first_data_source_id(database: dict[str, Any]) -> str:
    data_sources = database.get("data_sources")
    if isinstance(data_sources, list):
        for item in data_sources:
            if isinstance(item, dict) and item.get("id"):
                return str(item["id"])
    initial = database.get("initial_data_source")
    if isinstance(initial, dict) and initial.get("id"):
        return str(initial["id"])
    return ""
