from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from .core import LATEST_NOTION_VERSION, notion_api_token, notion_parent_page

NOTION_API_BASE = "https://api.notion.com/v1"
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
    token = notion_api_token().strip()
    if not token:
        raise ValueError("Set a Notion API Token in Settings to export to Notion.")
    url = f"{NOTION_API_BASE}{path}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(url, data=data, method=method, headers=notion_headers(token))
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace").strip()
        if payload:
            try:
                detail = json.loads(payload)
                message = detail.get("message") or payload
            except json.JSONDecodeError:
                message = payload
        else:
            message = exc.reason
        raise RuntimeError(f"Notion API {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Notion API request failed: {exc.reason}") from exc


def page_parent_id() -> str:
    configured = notion_parent_page().strip()
    if not configured:
        raise ValueError("Set a Notion Parent Page ID or URL in Settings to export to Notion.")
    return normalize_notion_id(configured)


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
        if is_location_column(header):
            specs.append(NotionColumnSpec(name=header, kind="place", property_definition={"place": {}}))
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


def _property_value(spec: NotionColumnSpec, value: str) -> dict[str, Any] | None:
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
        place = parse_place_value(value)
        return {"place": place} if place else {"rich_text": rich_text_array(value)}
    if spec.kind == "select":
        return {"select": {"name": value[:100]}}
    if spec.kind == "multi_select":
        options = [{"name": item[:100]} for item in split_multi_value(value)]
        return {"multi_select": options}
    if spec.kind == "relation":
        return {"relation": []}
    return {"rich_text": rich_text_array(value)}


def split_multi_value(value: str) -> list[str]:
    items = [item.strip() for item in value.split(",")]
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
        source_urls = split_multi_value(row[sources_column].replace("\n", ","))
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
    return {domain: sorted(values) for domain, values in sorted(grouped.items())}


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


def is_location_column(header: str) -> bool:
    lowered = header.strip().lower()
    return any(token in lowered for token in ["location", "address", "adress"])


def parse_place_value(value: str) -> dict[str, Any] | None:
    cleaned = value.strip()
    if not cleaned:
        return None
    parts = [part.strip() for part in cleaned.split(",") if part.strip()]
    return {
        "name": parts[0],
        "address": ", ".join(parts),
    }


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
    for row in rows:
        properties_payload: dict[str, Any] = {}
        for header, spec in row_specs.items():
            if spec.kind == "relation":
                continue
            value = row.get(header, "").strip()
            property_value = _property_value(spec, value)
            if property_value is not None:
                properties_payload[header] = property_value
        create_page_body = {
            "parent": {"type": "data_source_id", "data_source_id": data_source_id},
            "properties": properties_payload,
        }
        children = render_row_children(row, long_text_columns, sources_column, source_raw_column)
        if children:
            create_page_body["children"] = children
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
