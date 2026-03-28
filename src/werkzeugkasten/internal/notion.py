from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import requests

from .env import E, E_req
from .geocoding import geocode_place
from .value import as_list, as_urls, is_location_type


# TODO: Merge into table.py -> integrate with parsing around tables
@dataclass(frozen=True)
class NotionColumnSpec:
    name: str
    kind: str
    target_name: str | None = None
    property_definition: dict[str, Any] | None = None


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


def _request_api(method: str, path: str, body: dict[str, Any] | None = None) -> dict[str, Any]:
    url = E["notion_api_base", "https://api.notion.com/v1"] + path
    try:
        response = requests.request(
            method,
            url,
            headers={
                "Authorization": f"Bearer {E_req['notion_api_token']}",
                "Notion-Version": E["notion_version", "2026-03-11"],
                "Content-Type": "application/json",
            },
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


def _request_json_byte_length(body: dict[str, Any]) -> int:
    return len(json.dumps(body, ensure_ascii=True).encode("utf-8"))


# TODO: Move to a values.py -> integrate with parsing around tables
def _looks_numeric(value: str) -> bool:
    try:
        float(value.replace(",", ""))
    except ValueError:
        return False
    return True


# TODO: Move to a values.py -> integrate with parsing around tables
def _infer_column_specs(
    headers: list[str],
    rows: list[dict[str, str]],
    *,
    object_type: str,
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
        if header == object_type:
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


# TODO: Move to a values.py -> integrate with parsing around tables
def _property_value(
    spec: NotionColumnSpec,
    value: str,
) -> dict[str, Any] | None:
    if not value:
        return None
    if spec.kind == "title":
        return {"title": _rich_text_array(value)}
    if spec.kind == "rich_text":
        return {"rich_text": _rich_text_array(value)}
    if spec.kind == "number":
        try:
            return {"number": float(value.replace(",", ""))}
        except ValueError:
            return {"rich_text": _rich_text_array(value)}
    if spec.kind == "url":
        return {"url": value}
    if spec.kind == "place":
        place = geocode_place(value)
        return {"place": place} if place else None
    if spec.kind == "select":
        return {"select": {"name": value[:100]}}
    if spec.kind == "multi_select":
        options = [{"name": item[:100]} for item in as_list(value)]
        return {"multi_select": options}
    if spec.kind == "relation":
        return {"relation": []}
    return {"rich_text": _rich_text_array(value)}


def _heading_block(text: str, level: int = 2) -> dict[str, Any]:
    key = f"heading_{level}"
    return {"object": "block", "type": key, key: {"rich_text": _rich_text_array(text, max_chars=180)}}


def _paragraph_block(text: str) -> dict[str, Any]:
    return {"object": "block", "type": "paragraph", "paragraph": {"rich_text": _rich_text_array(text)}}


def _linked_bulleted_block(url: str) -> dict[str, Any]:
    return {"object": "block", "type": "bulleted_list_item", "bulleted_list_item": {"rich_text": _linked_rich_text(url)}}


def _rich_text_array(text: str, *, max_chars: int = 1800) -> list[dict[str, Any]]:
    if not text:
        return []
    chunks = [text[i : i + max_chars] for i in range(0, len(text), max_chars)]
    return [{"type": "text", "text": {"content": chunk}} for chunk in chunks[:100]]


def _linked_rich_text(url: str, label: str | None = None) -> list[dict[str, Any]]:
    return [
        {
            "type": "text",
            "text": {
                "content": label or url,
                "link": {"url": url},
            },
        }
    ]


def render_row_children(
    row: dict[str, str], long_text_columns: set[str], sources_column: str | None, source_summary_column: str | None
) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if sources_column and row.get(sources_column, "").strip():
        blocks.append(_heading_block("Sources", level=2))
        for url in as_urls(row[sources_column]):
            blocks.append(_linked_bulleted_block(url))
    if source_summary_column and row.get(source_summary_column, "").strip():
        blocks.append(_heading_block("Source Summary", level=2))
        for chunk in _chunk_text(row.get(source_summary_column, "")):
            blocks.append(_paragraph_block(chunk))
    for column in sorted(long_text_columns):
        if value := row.get(column, "").strip():
            blocks.append(_heading_block(column, level=2))
            for chunk in _chunk_text(value):
                blocks.append(_paragraph_block(chunk))

    while _request_json_byte_length(blocks) > E["notion_request_body_safe_max_bytes"]:
        if len(blocks) <= 1:
            raise RuntimeError("Notion page body is too large to create.")
        blocks.pop()
    return blocks


def export_dataset_to_notion(
    *,
    title: str,
    headers: list[str],
    rows: list[dict[str, str]],
    object_type: str,
    sources_column: str | None,
    source_summary_column: str | None,
    tags_column: str | None,
    nearest_column: str | None,
    record_id_column: str | None,
    list_like_columns: set[str],
    url_like_columns: set[str],
    long_text_columns: set[str],
) -> dict[str, Any]:
    specs = _infer_column_specs(
        headers,
        rows,
        object_type=object_type,
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
        "parent": {"type": "page_id", "page_id": E_req["notion_parent_page"]},
        "title": _rich_text_array(title[:180]),
        "initial_data_source": {
            "title": _rich_text_array(title[:180]),
            "properties": properties,
        },
    }
    database = _request_api("POST", "/databases", create_body)
    database_id = database.get("id")
    if not database_id:
        raise RuntimeError("Notion did not return a database ID.")

    data_source_id = ((database.get("initial_data_source") or {}).get("id")) or _extract_first_data_source_id(
        _request_api("GET", f"/databases/{database_id}")
    )
    if not data_source_id:
        raise RuntimeError("Could not determine the Notion data source ID for the new database.")

    if nearest_column:
        _request_api(
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
        create_page_body["children"] = render_row_children(row, long_text_columns, sources_column, source_summary_column)
        page = _request_api("POST", "/pages", create_page_body)
        page_id = page.get("id")
        record_id = row.get(record_id_column or "", "").strip()
        key_value = row.get(object_type, "").strip()
        if page_id and record_id:
            pages_by_record_id[record_id] = page_id
        if page_id and key_value:
            page_ids_by_key[key_value] = page_id

    if nearest_column and record_id_column:
        for row in rows:
            page_id = pages_by_record_id.get(row.get(record_id_column, "").strip())
            if not page_id:
                continue
            relation_ids = [{"id": pages_by_record_id[item]} for item in as_list(row.get(nearest_column, "")) if item in pages_by_record_id]
            if not relation_ids:
                relation_ids = [{"id": page_ids_by_key[item]} for item in as_list(row.get(nearest_column, "")) if item in page_ids_by_key]
            if not relation_ids:
                continue
            _request_api(
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
