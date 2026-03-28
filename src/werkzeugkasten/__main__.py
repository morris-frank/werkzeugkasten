from __future__ import annotations

import sys
from dataclasses import asdict, is_dataclass
from functools import partial
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import typer
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .internal.env import KastenConfig, kasten_config

Service = Literal[
    "research-list",
    "inspect-table",
    "research-table",
    "summarize-files",
    "summarize-text",
    "prettify-codex-log",
]


class EngineRequest(BaseModel):
    service: Service
    payload: dict[str, Any] = Field(default_factory=dict)
    config: KastenConfig = Field(default_factory=KastenConfig)


class EngineResponse(BaseModel):
    data: dict[str, Any]


api = FastAPI(title="werkzeugkasten")
cli = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


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


def _read_request() -> EngineRequest:
    payload = sys.stdin.read()
    if not payload.strip():
        raise ValueError("Expected JSON payload on stdin.")
    return EngineRequest.model_validate_json(payload)


def _research_list(payload: dict[str, Any]) -> dict[str, Any]:
    from .service import research_table

    items = [str(item).strip() for item in payload.get("items", []) if str(item).strip()]
    question = str(payload.get("question", "")).strip()
    if not items:
        raise ValueError("Expected at least one item.")
    if not question:
        raise ValueError("Expected a question.")

    return research_table(
        pd.DataFrame({"Item": items, question: [""] * len(items)}),
        include_sources=bool(payload.get("include_sources", False)),
        summarize_sources=bool(payload.get("include_source_raw", False)),
        auto_tagging=bool(payload.get("auto_tagging", False)),
        nearest_neighbour=bool(payload.get("nearest_neighbour", False)),
        output_path=payload.get("output_path"),
    )


def _inspect_table(payload: dict[str, Any]) -> dict[str, Any]:
    from .service import inspect_table

    return inspect_table(str(payload.get("raw_table_text", "")))


def _research_table(payload: dict[str, Any]) -> dict[str, Any]:
    from .service import research_table

    return research_table(
        str(payload.get("raw_table_text", "")),
        include_sources=bool(payload.get("include_sources", False)),
        summarize_sources=bool(payload.get("include_source_raw", False)),
        auto_tagging=bool(payload.get("auto_tagging", False)),
        nearest_neighbour=bool(payload.get("nearest_neighbour", False)),
        output_path=payload.get("output_path"),
    )


def _summarize(payload: dict[str, Any], key: str) -> dict[str, Any]:
    from .service import summarize

    return summarize(payload.get(key, ""))


def _prettify_codex_log(payload: dict[str, Any]) -> dict[str, Any]:
    from .service.codex_log import prettify_codex_log

    return prettify_codex_log(payload)


def _dispatch(request: EngineRequest) -> dict[str, Any]:
    global kasten_config
    kasten_config = request.config
    handlers = {
        "research-list": _research_list,
        "inspect-table": _inspect_table,
        "research-table": _research_table,
        "summarize-files": partial(_summarize, key="paths"),
        "summarize-text": partial(_summarize, key="text"),
        "prettify-codex-log": _prettify_codex_log,
    }
    return _as_jsonable(handlers[request.service](request.payload))


@api.post("/run", response_model=EngineResponse)
def run_api(request: EngineRequest) -> EngineResponse:
    try:
        return EngineResponse(data=_dispatch(request))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@cli.command()
def run() -> None:
    response = EngineResponse(data=_dispatch(_read_request()))
    sys.stdout.write(response.model_dump_json())
    sys.stdout.write("\n")


@cli.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    uvicorn.run(api, host=host, port=port)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
