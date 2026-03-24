from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from .core import read_json_stdin
from .rest_server import main as rest_main
from .services import (
    inspect_table_service,
    prettify_codex_log_service,
    research_list_service,
    research_table_service,
    summary_service,
)
from .summarize import summarize_files


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
    serve = subparsers.add_parser("serve")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "serve":
            return rest_main(["--host", args.host, "--port", str(args.port)])
        payload = read_json_stdin()
        if args.command == "research-list":
            items = payload.get("items")
            question = payload.get("question", "")
            if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                raise ValueError("`items` must be an array of strings.")
            return _print_json(
                research_list_service(
                    items,
                    question,
                    progress=_progress(args.progress),
                    payload=payload,
                )
            )

        if args.command == "inspect-table":
            raw_table_text = payload.get("raw_table_text", "")
            if not isinstance(raw_table_text, str):
                raise ValueError("`raw_table_text` must be a string.")
            return _print_json(inspect_table_service(raw_table_text, payload.get("source_name", args.source_name)))

        if args.command == "research-table":
            raw_table_text = payload.get("raw_table_text", "")
            if not isinstance(raw_table_text, str):
                raise ValueError("`raw_table_text` must be a string.")
            return _print_json(
                research_table_service(
                    raw_table_text,
                    source_name=payload.get("source_name", args.source_name),
                    progress=_progress(args.progress),
                    payload=payload,
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
            return _print_json(summary_service({"title": title, "text": text}))

        if args.command == "prettify-codex-log":
            path = payload.get("path")
            if not isinstance(path, str):
                raise ValueError("`path` must be a string.")
            return _print_json(prettify_codex_log_service(path))
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
