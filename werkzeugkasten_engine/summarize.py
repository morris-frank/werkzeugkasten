from __future__ import annotations

from pathlib import Path

from .summary_service import (
    DOWNLOADED_SOURCE_DIR,
    MAX_SUMMARY_INPUT,
    convert_to_markdown,
    get_stream_info,
    mirror_languages_instruction,
    stable_download_directory,
    stable_download_path,
    summary,
    summary_prompt,
    truncate_for_upload,
)


def summarize_text_input(title: str, text: str) -> str:
    return str(summary(title=title, text=text)["summary_markdown"]).strip()


def summarize_local_file(
    path: Path,
    *,
    artifacts_directory: Path | None = None,
) -> dict[str, str]:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"Not a file: {resolved}")
    target_directory = (artifacts_directory or resolved.parent).expanduser()
    target_directory.mkdir(parents=True, exist_ok=True)
    result = summary(title=resolved.name, paths=[resolved], artifacts_directory=target_directory)
    markdown = str(result["contents_markdown"])
    summary_markdown = str(result["summary_markdown"])
    contents_paths = result.get("contents_paths") or []
    contents_path = Path(contents_paths[0]) if contents_paths else target_directory / f".{resolved.name}.contents.md"
    summary_path = Path(str(result.get("summary_path") or target_directory / f"{resolved.name}.summary.md"))

    return {
        "input_path": str(resolved),
        "contents_path": str(contents_path),
        "summary_path": str(summary_path),
        "contents_markdown": markdown,
        "summary_markdown": summary_markdown,
    }


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
