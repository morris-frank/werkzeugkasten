from __future__ import annotations

from pathlib import Path
from typing import Any

from .codex_log import prettify_codex_log
from .research_list import run_research_list
from .research_table import ResearchOptions, inspect_table, run_research_table
from .summary_service import summary


def research_options_from_payload(payload: dict[str, Any]) -> ResearchOptions:
    return ResearchOptions(
        include_sources=bool(payload.get("include_sources", False)),
        include_source_raw=bool(payload.get("include_source_raw", False)),
        auto_tagging=bool(payload.get("auto_tagging", False)),
        nearest_neighbour=bool(payload.get("nearest_neighbour", False)),
        export_to_notion=bool(payload.get("export_to_notion", False)),
        output_path=str(payload.get("output_path", "") or ""),
        source_column_policy=str(payload.get("source_column_policy", "merge") or "merge"),
        source_raw_column_policy=str(payload.get("source_raw_column_policy", "merge") or "merge"),
        tag_column_policy=str(payload.get("tag_column_policy", "merge") or "merge"),
        nearest_column_policy=str(payload.get("nearest_column_policy", "merge") or "merge"),
        record_id_column_policy=str(payload.get("record_id_column_policy", "merge") or "merge"),
    ).normalized()


def inspect_table_service(raw_table_text: str, source_name: str = "pasted-table") -> dict[str, object]:
    return inspect_table(raw_table_text, source_name)


def research_table_service(
    raw_table_text: str,
    *,
    source_name: str = "pasted-table",
    output_dir: Path | None = None,
    progress=None,
    payload: dict[str, Any] | None = None,
) -> dict[str, object]:
    return run_research_table(
        raw_table_text,
        source_name=source_name,
        output_dir=output_dir,
        progress=progress,
        options=research_options_from_payload(payload or {}),
    )


def research_list_service(
    items: list[str],
    question: str,
    *,
    output_dir: Path | None = None,
    progress=None,
    payload: dict[str, Any] | None = None,
) -> dict[str, object]:
    return run_research_list(
        items,
        question,
        output_dir=output_dir,
        progress=progress,
        options=research_options_from_payload(payload or {}),
    )


def summary_service(payload: dict[str, Any]) -> dict[str, Any]:
    title = payload.get("title")
    text = payload.get("text")
    paths = payload.get("paths")
    urls = payload.get("urls")
    artifacts_directory = payload.get("artifacts_directory")
    if title is not None and not isinstance(title, str):
        raise ValueError("`title` must be a string.")
    if text is not None and not isinstance(text, str):
        raise ValueError("`text` must be a string.")
    if paths is not None and (not isinstance(paths, list) or not all(isinstance(path, str) for path in paths)):
        raise ValueError("`paths` must be an array of strings.")
    if urls is not None and (not isinstance(urls, list) or not all(isinstance(url, str) for url in urls)):
        raise ValueError("`urls` must be an array of strings.")
    return summary(
        title=title,
        text=text,
        paths=paths,
        urls=urls,
        artifacts_directory=artifacts_directory,
    )


def prettify_codex_log_service(path: str) -> dict[str, Any]:
    return prettify_codex_log(path)
