from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .codex_log import prettify_codex_log
from .core import read_json_stdin
from .research_list import run_research_list
from .research_table import ResearchOptions, inspect_table, run_research_table
from .summarize import summarize_files, summarize_text_input


def _progress(enabled: bool):
    if not enabled:
        return None

    def emit(current: int, total: int, label: str) -> None:
        event = {"kind": "progress", "current": current, "total": total, "label": label}
        print(json.dumps(event), file=sys.stderr, flush=True)

    return emit


def _print_json(data: dict[str, Any]) -> int:
    print(json.dumps(data))
    return 0


def _research_options(payload: dict[str, Any]) -> ResearchOptions:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="werkzeugkasten-engine")
    subparsers = parser.add_subparsers(dest="command", required=True)

    research_list = subparsers.add_parser("research-list")
    research_list.add_argument("--progress", action="store_true")

    inspect = subparsers.add_parser("inspect-table")
    inspect.add_argument("--source-name", default="pasted-table")

    research_table = subparsers.add_parser("research-table")
    research_table.add_argument("--progress", action="store_true")
    research_table.add_argument("--source-name", default="pasted-table")

    summarize_files_cmd = subparsers.add_parser("summarize-files")
    summarize_files_cmd.add_argument("--progress", action="store_true")

    subparsers.add_parser("summarize-text")
    subparsers.add_parser("prettify-codex-log")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        payload = read_json_stdin()
        if args.command == "research-list":
            items = payload.get("items")
            question = payload.get("question", "")
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                raise ValueError("`items` must be an array of strings.")
            return _print_json(
                run_research_list(
                    items,
                    question,
                    progress=_progress(args.progress),
                    options=_research_options(payload),
                )
            )

        if args.command == "inspect-table":
            raw_table_text = payload.get("raw_table_text", "")
            if not isinstance(raw_table_text, str):
                raise ValueError("`raw_table_text` must be a string.")
            return _print_json(inspect_table(raw_table_text, payload.get("source_name", args.source_name)))

        if args.command == "research-table":
            raw_table_text = payload.get("raw_table_text", "")
            if not isinstance(raw_table_text, str):
                raise ValueError("`raw_table_text` must be a string.")
            return _print_json(
                run_research_table(
                    raw_table_text,
                    source_name=payload.get("source_name", args.source_name),
                    progress=_progress(args.progress),
                    options=_research_options(payload),
                )
            )

        if args.command == "summarize-files":
            paths = payload.get("paths")
            if not isinstance(paths, list) or not all(isinstance(path, str) for path in paths):
                raise ValueError("`paths` must be an array of strings.")
            return _print_json(summarize_files(paths))

        if args.command == "summarize-text":
            title = payload.get("title", "Pasted text")
            text = payload.get("text", "")
            if not isinstance(title, str) or not isinstance(text, str):
                raise ValueError("`title` and `text` must be strings.")
            return _print_json({"summary_markdown": summarize_text_input(title, text)})

        if args.command == "prettify-codex-log":
            path = payload.get("path")
            if not isinstance(path, str):
                raise ValueError("`path` must be a string.")
            return _print_json(prettify_codex_log(path))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
