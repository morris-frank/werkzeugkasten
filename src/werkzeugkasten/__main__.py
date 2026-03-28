from __future__ import annotations

import sys
from typing import Any

import typer
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from . import service
from .internal.env import E
from .service.models import *

AnyResponse = SummarizeSourcesResponse | ResearchTableResponse | InspectTableResponse | PrettifyCodexLogResponse


class EngineRequest(BaseModel):
    service: str
    payload: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, str] = Field(default_factory=dict)


api = FastAPI(title="werkzeugkasten")
cli = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


def _read_request() -> EngineRequest:
    payload = sys.stdin.read()
    if not payload.strip():
        raise ValueError("Expected JSON payload on stdin.")
    return EngineRequest.model_validate_json(payload)


@api.post("/research-list", response_model=ResearchTableResponse)
def research_list(request: EngineRequest) -> ResearchTableResponse:
    E.update(request.config)
    return service.research_list(
        items=request.payload.get("items", ""),
        question=request.payload.get("question", ""),
        output_path=request.payload.get("output_path"),
        include_sources=bool(request.payload.get("include_sources", False)),
        include_sources_summary=bool(request.payload.get("include_sources_summary", False)),
        # source_column_policy=request.payload.get("source_column_policy", "merge"),
        # source_summary_column_policy=request.payload.get("source_summary_column_policy", "merge"),
    )


@api.post("/inspect-table", response_model=InspectTableResponse)
def inspect_table(request: EngineRequest) -> InspectTableResponse:
    E.update(request.config)
    return service.inspect_table(str(request.payload.get("table", "")))


@api.post("/research-table", response_model=ResearchTableResponse)
def research_table(request: EngineRequest) -> ResearchTableResponse:
    E.update(request.config)

    return service.research_table(
        str(request.payload.get("table", "")),
        include_sources=bool(request.payload.get("include_sources", False)),
        include_sources_summary=bool(request.payload.get("include_source_summary", False)),
        auto_tagging=bool(request.payload.get("auto_tagging", False)),
        nearest_neighbour=bool(request.payload.get("nearest_neighbour", False)),
        output_path=request.payload.get("output_path"),
        # source_column_policy=request.payload.get("source_column_policy", "merge"),
        # source_summary_column_policy=request.payload.get("source_summary_column_policy", "merge"),
        # tag_column_policy=request.payload.get("tag_column_policy", "merge"),
        # nearest_column_policy=request.payload.get("nearest_column_policy", "merge"),
    )


@api.post("/summarize", response_model=SummarizeSourcesResponse)
def summarize(request: EngineRequest) -> dict[str, Any]:
    E.update(request.config)
    return service.summarize_sources(request.payload.get("sources", ""))


@api.post("/prettify-codex-log", response_model=PrettifyCodexLogResponse)
def prettify_codex_log(request: EngineRequest) -> PrettifyCodexLogResponse:
    E.update(request.config)
    return service.prettify_codex_log(request.payload.get("path", ""))


@api.post("/run", response_model=AnyResponse)
def run_api(request: EngineRequest) -> AnyResponse:
    try:
        return api.routes[request.service](request)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@cli.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    uvicorn.run(api, host=host, port=port)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
