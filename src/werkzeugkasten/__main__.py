from __future__ import annotations

import sys
from typing import Any

import typer
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, Field

from .internal.env import E
from .service import *


class EngineRequest(BaseModel):
    service: str
    payload: dict[str, Any] = Field(default_factory=dict)
    config: dict[str, str] = Field(default_factory=dict)


class EngineResponse(BaseModel):
    data: dict[str, Any]


api = FastAPI(title="werkzeugkasten")
cli = typer.Typer(add_completion=False, pretty_exceptions_enable=False)


@api.post("/research-list", response_model=ResearchTableResponse)
def research_list_api(request: EngineRequest) -> ResearchTableResponse:
    E.update(request.config)
    return research_list(
        items=request.payload.get("items", ""),
        question=request.payload.get("question", ""),
        output_path=request.payload.get("output_path"),
        # include_sources=bool(request.payload.get("include_sources", False)),
        # include_sources_summary=bool(request.payload.get("include_sources_summary", False)),
        # source_column_policy=request.payload.get("source_column_policy", "merge"),
        # source_summary_column_policy=request.payload.get("source_summary_column_policy", "merge"),
    )


@api.post("/inspect-table", response_model=InspectTableResponse)
def inspect_table_api(request: EngineRequest) -> InspectTableResponse:
    E.update(request.config)
    return inspect_table(str(request.payload.get("table", "")))


@api.post("/research-table", response_model=ResearchTableResponse)
def research_table_api(request: EngineRequest) -> ResearchTableResponse:
    E.update(request.config)

    return research_table(
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
def summarize_api(request: EngineRequest) -> SummarizeSourcesResponse:
    E.update(request.config)
    return summarize_sources(request.payload.get("sources", ""))


@api.post("/prettify-codex-log", response_model=PrettifyCodexLogResponse)
def prettify_codex_log_api(request: EngineRequest) -> PrettifyCodexLogResponse:
    E.update(request.config)
    return prettify_codex_log(request.payload.get("path", ""))


_engine_routes = {
    "research-list": research_list_api,
    "inspect-table": inspect_table_api,
    "research-table": research_table_api,
    "summarize-files": summarize_api,
    "summarize-text": summarize_api,
    "prettify-codex-log": prettify_codex_log_api,
}


@cli.command()
def run() -> None:
    payload = sys.stdin.read()
    if not payload.strip():
        raise ValueError("Expected JSON payload on stdin.")
    request = EngineRequest.model_validate_json(payload)
    response = _engine_routes[request.service](request=request)
    sys.stdout.write(EngineResponse(data=response.model_dump()).model_dump_json())
    sys.stdout.write("\n")


@cli.command()
def serve(host: str = "127.0.0.1", port: int = 8000) -> None:
    uvicorn.run(api, host=host, port=port)


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
