from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import markitdown
from markitdown import MarkItDown

from .core import openai_client, summary_model

PROMPT = """Summarise this file in Markdown.

Return exactly these sections:

# Summary
Very brief bullet point summary of the file. Never more than necessary. If there is only one important thing, just say that. Follow the MECE (Mutually Exclusive, Collectively Exhaustive) Framework.

# Key details
Important facts, decisions, names, dates, methods, or structure. If there are any contrasting opinions, make those explicit. Follow the MECE Framework.

# Open questions
Anything unclear, missing, or worth checking.

# Input
Filename: {filename}
Timestamp: {timestamp}


Document content:
{text}/
"""

MAX_SUMMARY_INPUT = 120_000


def get_stream_info(path: Path) -> Optional[markitdown.StreamInfo]:
    if path.suffix.lower() in {".txt", ".text", ".md", ".markdown", ".json", ".jsonl"}:
        return markitdown.StreamInfo(charset="utf-8")
    return None


def truncate_for_upload(text: str, limit: int = MAX_SUMMARY_INPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[Truncated before upload]"


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


def summarize_text_input(title: str, text: str) -> str:
    response = openai_client().responses.create(
        model=summary_model(),
        input=PROMPT.format(
            filename=title,
            text=truncate_for_upload(text),
            timestamp=datetime.now().isoformat(),
        ),
    )
    return (response.output_text or "").strip()


def process_file(path_str: str) -> dict[str, str]:
    path = Path(path_str).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Not a file: {path}")

    markdown = convert_to_markdown(path)
    if not markdown:
        raise RuntimeError(f"No extractable content for {path.name}")

    contents_path = path.with_name(f".{path.name}.contents.md")
    contents_path.write_text(markdown + "\n", encoding="utf-8")

    summary = summarize_text_input(path.name, markdown)
    summary_path = path.with_name(path.name + ".summary.md")
    summary_path.write_text(summary + "\n", encoding="utf-8")

    return {
        "input_path": str(path),
        "contents_path": str(contents_path),
        "summary_path": str(summary_path),
    }


def summarize_files(paths: list[str]) -> dict[str, object]:
    if not paths:
        raise ValueError("No input files provided.")

    files: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for path in paths:
        try:
            files.append(process_file(path))
        except Exception as exc:
            failures.append({"input_path": str(Path(path).expanduser()), "error": str(exc)})
    return {"files": files, "failures": failures}
