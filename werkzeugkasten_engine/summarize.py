from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import markitdown
from markitdown import MarkItDown

from .core import openai_client, summary_mirror_languages, summary_model


def mirror_languages_instruction(languages: list[str]) -> str:
    """Build the 'match source language' instruction for the summary prompt."""
    if not languages:
        languages = summary_mirror_languages()
    if len(languages) == 1:
        lang = languages[0]
        return f"If the text is in {lang}, produce the summary in {lang}."
    if len(languages) == 2:
        a, b = languages[0], languages[1]
        return f"If the text is in {a} or {b}, produce the summary in that same language ({a} or {b})."
    *rest, last = languages
    phrase = ", ".join(rest) + f", or {last}"
    return f"If the text is in {phrase}, produce the summary in the same language as the source text."


def summary_prompt(filename: str, timestamp: str, text: str, *, languages: list[str] | None = None) -> str:
    langs = languages if languages is not None else summary_mirror_languages()
    mirror = mirror_languages_instruction(langs)
    return f"""Summarise this file in Markdown.

{mirror}
For all other languages, produce the summary in English.

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
{text}
"""

MAX_SUMMARY_INPUT = 120_000
DOWNLOADED_SOURCE_DIR = Path(tempfile.gettempdir()) / "werkzeugkasten-source-downloads"


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
        input=summary_prompt(
            title,
            datetime.now().isoformat(),
            truncate_for_upload(text),
        ),
    )
    return (response.output_text or "").strip()


def summarize_local_file(
    path: Path,
    *,
    artifacts_directory: Path | None = None,
) -> dict[str, str]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Not a file: {resolved}")

    markdown = convert_to_markdown(resolved)
    if not markdown:
        raise RuntimeError(f"No extractable content for {resolved.name}")

    target_directory = (artifacts_directory or resolved.parent).expanduser()
    target_directory.mkdir(parents=True, exist_ok=True)
    contents_path = target_directory / f".{resolved.name}.contents.md"
    contents_path.write_text(markdown + "\n", encoding="utf-8")

    summary = summarize_text_input(resolved.name, markdown)
    summary_path = target_directory / f"{resolved.name}.summary.md"
    summary_path.write_text(summary + "\n", encoding="utf-8")

    return {
        "input_path": str(resolved),
        "contents_path": str(contents_path),
        "summary_path": str(summary_path),
        "contents_markdown": markdown,
        "summary_markdown": summary,
    }


def stable_download_directory() -> Path:
    DOWNLOADED_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    return DOWNLOADED_SOURCE_DIR


def stable_download_path(url: str, suffix: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}" if suffix else ""
    return stable_download_directory() / f"{digest}{clean_suffix}"


def process_file(path_str: str) -> dict[str, str]:
    result = summarize_local_file(Path(path_str))
    return {
        "input_path": result["input_path"],
        "contents_path": result["contents_path"],
        "summary_path": result["summary_path"],
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
