from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import tempfile

from .io_ops import convert_to_markdown, download_source_document, fetch_source_raw_text, get_stream_info
from .openai_ops import openai_client, summary_mirror_languages, summary_model

MAX_SUMMARY_INPUT = 120_000
DOWNLOADED_SOURCE_DIR = Path(tempfile.gettempdir()) / "werkzeugkasten-source-downloads"


def mirror_languages_instruction(languages: list[str]) -> str:
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


def truncate_for_upload(text: str, limit: int = MAX_SUMMARY_INPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n[Truncated before upload]"


def stable_download_directory() -> Path:
    DOWNLOADED_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    return DOWNLOADED_SOURCE_DIR


def stable_download_path(url: str, suffix: str) -> Path:
    import hashlib

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    clean_suffix = suffix if suffix.startswith(".") else f".{suffix}" if suffix else ""
    return stable_download_directory() / f"{digest}{clean_suffix}"


def _document_downloader(url: str) -> Path:
    return download_source_document(url, destination_factory=stable_download_path)


def _summary_markdown(title: str, text: str) -> str:
    response = openai_client().responses.create(
        model=summary_model(),
        input=summary_prompt(
            title,
            datetime.now().isoformat(),
            truncate_for_upload(text),
        ),
    )
    return (response.output_text or "").strip()


def _normalize_paths(paths: Iterable[str | Path] | None) -> list[Path]:
    normalized: list[Path] = []
    for path in paths or []:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise FileNotFoundError(f"Not a file: {resolved}")
        normalized.append(resolved)
    return normalized


def _normalize_urls(urls: Iterable[str] | None) -> list[str]:
    from .io_ops import normalize_source_urls

    return normalize_source_urls([url for url in urls or [] if str(url).strip()])


def _collect_url_text(url: str) -> str:
    result = fetch_source_raw_text(
        url,
        {},
        document_downloader=_document_downloader,
    )
    if result.is_error:
        raise RuntimeError(result.message or result.text)
    return f"Source URL: {url}\n\n{result.text}".strip()


def summary(
    *,
    title: str | None = None,
    text: str | None = None,
    paths: Iterable[str | Path] | None = None,
    urls: Iterable[str] | None = None,
    artifacts_directory: str | Path | None = None,
) -> dict[str, Any]:
    normalized_text = (text or "").strip()
    normalized_paths = _normalize_paths(paths)
    normalized_urls = _normalize_urls(urls)
    if not normalized_text and not normalized_paths and not normalized_urls:
        raise ValueError("Provide text, paths, or URLs.")

    source_documents: list[str] = []
    contents_sections: list[str] = []
    contents_paths: list[str] = []

    if normalized_text:
        contents_sections.append(normalized_text)
        source_documents.append(title or "Pasted text")

    target_directory = Path(artifacts_directory).expanduser() if artifacts_directory else None
    if target_directory is not None:
        target_directory.mkdir(parents=True, exist_ok=True)

    for path in normalized_paths:
        markdown = convert_to_markdown(path)
        if not markdown:
            raise RuntimeError(f"No extractable content for {path.name}")
        contents_sections.append(f"Source file: {path.name}\n\n{markdown}".strip())
        source_documents.append(path.name)
        if target_directory is not None:
            contents_path = target_directory / f".{path.name}.contents.md"
            contents_path.write_text(markdown + "\n", encoding="utf-8")
            contents_paths.append(str(contents_path))

    for url in normalized_urls:
        contents_sections.append(_collect_url_text(url))
        source_documents.append(url)

    combined_markdown = "\n\n---\n\n".join(section for section in contents_sections if section.strip()).strip()
    resolved_title = title or (source_documents[0] if len(source_documents) == 1 else "Combined sources")
    summary_markdown = _summary_markdown(resolved_title, combined_markdown)

    summary_path = None
    if target_directory is not None:
        safe_name = Path(resolved_title).name or "summary"
        summary_path = target_directory / f"{safe_name}.summary.md"
        summary_path.write_text(summary_markdown + "\n", encoding="utf-8")

    return {
        "title": resolved_title,
        "summary_markdown": summary_markdown,
        "contents_markdown": combined_markdown,
        "source_documents": source_documents,
        "contents_paths": contents_paths,
        "summary_path": str(summary_path) if summary_path else "",
    }
