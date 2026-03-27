from __future__ import annotations

import json
import sys
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .actions import inspect_table, prettify_codex_log, research_table, summarize
from .internal import get_content, read_json_stdin, text_to_source


def _as_jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return {key: _as_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): _as_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_as_jsonable(item) for item in value]
    return value


def _read_command_payload() -> tuple[str, dict[str, Any]]:
    if len(sys.argv) < 2:
        raise ValueError("Expected a command.")
    return sys.argv[1], read_json_stdin()


def _summarize_text(payload: dict[str, Any]) -> dict[str, str]:
    text = str(payload.get("text", "")).strip()
    return {"summary_markdown": summarize([text_to_source(text)])}


def _sidecar_path(path: Path, suffix: str) -> Path:
    return path.with_name(path.name + suffix)


def _summarize_files(payload: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    files: list[dict[str, str]] = []
    failures: list[dict[str, str]] = []
    for raw_path in payload.get("paths", []):
        path = Path(raw_path).expanduser()
        try:
            contents = get_content([path])
            summary = summarize([path])
            contents_path = _sidecar_path(path, ".contents.md")
            summary_path = _sidecar_path(path, ".summary.md")
            contents_path.write_text(contents, encoding="utf-8")
            summary_path.write_text(summary, encoding="utf-8")
            files.append(
                {
                    "input_path": str(path),
                    "contents_path": str(contents_path),
                    "summary_path": str(summary_path),
                }
            )
        except Exception as exc:
            failures.append({"input_path": str(path), "error": str(exc)})
    return {"files": files, "failures": failures}


def _inspect_table_cli(payload: dict[str, Any]) -> dict[str, object]:
    return inspect_table(str(payload.get("raw_table_text", "")))


def _research_table_cli(payload: dict[str, Any]) -> dict[str, object]:
    return research_table(
        str(payload.get("raw_table_text", "")),
        include_sources=bool(payload.get("include_sources", False)),
        include_source_raw=bool(payload.get("include_source_raw", False)),
        auto_tagging=bool(payload.get("auto_tagging", False)),
        nearest_neighbour=bool(payload.get("nearest_neighbour", False)),
        output_path=payload.get("output_path"),
    )


def _prettify_codex_log_cli(payload: dict[str, Any]) -> dict[str, object]:
    return _as_jsonable(prettify_codex_log(str(payload.get("path", ""))))


def main() -> int:
    command, payload = _read_command_payload()
    handlers = {
        "inspect-table": _inspect_table_cli,
        "research-table": _research_table_cli,
        "summarize-files": _summarize_files,
        "summarize-text": _summarize_text,
        "prettify-codex-log": _prettify_codex_log_cli,
    }
    if command not in handlers:
        raise ValueError(f"Unsupported command: {command}")
    result = handlers[command](payload)
    sys.stdout.write(json.dumps(_as_jsonable(result), ensure_ascii=False))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
