from __future__ import annotations

import sys
from pathlib import Path

from .research_list import parse_items, run_research_list, run_self_tests as run_research_list_self_tests
from .research_table import (
    inspect_table,
    run_research_table,
    run_self_tests as run_research_table_self_tests,
)
from .summarize import summarize_files


def _read_pasted_block(label: str) -> str:
    print(f"Paste the {label}. Press Enter twice when done.")
    lines: list[str] = []
    blank_streak = 0
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip():
            blank_streak = 0
        else:
            blank_streak += 1
            if lines and blank_streak >= 2:
                break
        lines.append(line)
    return "\n".join(lines)


def run_ai_research_cli(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if "--self-test" in args:
        run_research_list_self_tests()
        print("List parser self-test passed.")
        return 0

    while True:
        items = parse_items(_read_pasted_block("list"))
        if items:
            break
        print("No valid items found. Try again.", file=sys.stderr)

    print(f"\nParsed {len(items)} items.")
    for index, item in enumerate(items[:3], start=1):
        print(f"  {index}. {item}")
    if len(items) > 3:
        print("  ...")
    if input(f"Proceed with {len(items)} items? [Y/n]: ").strip().lower() not in {"", "y", "yes"}:
        print("Aborted.", file=sys.stderr)
        return 1

    question = ""
    while not question:
        question = input("\nQuestion: ").strip()
    print("")
    result = run_research_list(items, question, progress=lambda current, total, label: print(f"[{current}/{total}] {label}" if current else f"[0/{total}] {label}"))
    print(f"Done. Output saved to {result['output_path']}")
    return 0


def run_ai_research_table_cli(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if "--self-test" in args:
        run_research_table_self_tests()
        print("Table parser self-test passed.")
        return 0

    if args:
        path = Path(args[0]).expanduser().resolve()
        if not path.is_file():
            print(f"Not a file: {path}", file=sys.stderr)
            return 1
        raw = path.read_text(encoding="utf-8")
        source_name = path.name
    else:
        raw = _read_pasted_block("CSV or markdown table")
        if not raw.strip():
            print("No input provided.", file=sys.stderr)
            return 1
        source_name = "pasted-table"

    try:
        preview = inspect_table(raw, source_name)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("")
    print(f"Source: {preview['source_name']}")
    print(f"Detected format: {preview['detected_format']}")
    print(f"Rows: {preview['row_count']}")
    print(f"Requested columns per row: {max(0, len(preview['headers']) - 1)}")
    print(f"Key column: {preview['key_header']}")
    print(f"Object type: {preview['object_type']}")
    print("Question columns:")
    for column in preview["question_columns"] or ["none"]:
        print(f"  - {column}")
    print("Attribute columns:")
    for column in preview["attribute_columns"] or ["none"]:
        print(f"  - {column}")
    print(f"Example key: {preview['example_key']}")
    if input("\nProceed? [Y/n]: ").strip().lower() not in {"", "y", "yes"}:
        print("Aborted.", file=sys.stderr)
        return 1

    result = run_research_table(raw, source_name, progress=lambda current, total, label: print(f"[{current}/{total}] {label}" if current else f"[0/{total}] {label}"))
    print(f"Done. Output saved to {result['output_path']}")
    return 0


def run_summarize_file_cli(argv: list[str] | None = None) -> int:
    args = argv or sys.argv[1:]
    if not args:
        print("Usage: summarize-file <file1> [file2 ...]", file=sys.stderr)
        return 1

    result = summarize_files(args)
    for success in result["files"]:
        print(f"Wrote {success['contents_path']}")
        print(f"Wrote {success['summary_path']}")
    for failure in result["failures"]:
        print(f"Failed: {failure['input_path']}: {failure['error']}", file=sys.stderr)
    return 1 if result["failures"] else 0
