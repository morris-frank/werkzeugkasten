from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from .research_table import DatasetShape, ResearchOptions, run_research_dataset

ProgressCallback = Callable[[int, int, str], None]


def parse_items(raw: str) -> list[str]:
    items: list[str] = []
    for line in raw.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        cleaned = re.sub(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)", "", cleaned).strip()
        if not cleaned or not re.search(r"\w", cleaned):
            continue
        items.append(cleaned)
    return items


def question_header(question: str) -> str:
    normalized = question.strip()
    if not normalized:
        raise ValueError("Question cannot be empty.")
    if normalized.endswith("?"):
        return normalized
    return f"{normalized}?"


def run_research_list(
    items: list[str],
    question: str,
    output_dir: Path | None = None,
    progress: ProgressCallback | None = None,
    options: ResearchOptions | None = None,
) -> dict[str, object]:
    normalized_items = [item.strip() for item in items if item.strip()]
    if not normalized_items:
        raise ValueError("No valid items found.")

    header = question_header(question)
    dataset = DatasetShape(
        source_name="research-list",
        detected_format="generated-list",
        headers=["Item", header],
        rows=[{"Item": item, header: ""} for item in normalized_items],
        question_columns=[header],
    )
    result = run_research_dataset(dataset, output_dir=output_dir, progress=progress, options=options)
    return {
        "output_path": result["output_path"],
        "debug_log_path": result.get("debug_log_path", ""),
        "item_count": len(normalized_items),
        "completed_count": len(normalized_items),
        "headers": result["headers"],
        "question_columns": result["question_columns"],
        "attribute_columns": result["attribute_columns"],
    }


def run_self_tests() -> None:
    assert parse_items("- Apple\n- Banana\n- Cherry") == ["Apple", "Banana", "Cherry"]
    assert parse_items("1. Apple\n2. Banana\n3. Cherry") == ["Apple", "Banana", "Cherry"]
    assert parse_items("- Apple\n\n-  \n* Banana\n---\n+ Cherry") == ["Apple", "Banana", "Cherry"]
    assert parse_items("  - Acme Inc  \n  2) Beta BV  ") == ["Acme Inc", "Beta BV"]
    assert parse_items("- C++\n- A+\n- AT&T") == ["C++", "A+", "AT&T"]
    assert question_header("What does it do") == "What does it do?"
