from typing import Any

from pydantic import BaseModel, Field

from ..internal.value import as_json


class QueryUsage(BaseModel):
    number_queries: int = Field(default=0)
    token_count: int = Field(default=0)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)

    def __add__(self, other: "QueryUsage") -> "QueryUsage":
        return QueryUsage(
            number_queries=self.number_queries + other.number_queries,
            token_count=self.token_count + other.token_count,
            input_tokens=self.input_tokens + other.input_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
        )


class QueryResponse(BaseModel):
    text: str
    sources: list[str]
    usage: QueryUsage

    @property
    def as_json(self) -> dict[str, Any]:
        return as_json(self.text)


class SummarizeSourcesResponse(BaseModel):
    summary: str
    content: str
    usage: QueryUsage


class LookupObjectResponse(BaseModel):
    data: dict[str, Any]
    answer: str
    includes_sources: bool
    includes_sources_summary: bool
    count_fields_researched: int
    researched_fields: list[str]
    sources: list[str]
    usage: QueryUsage
    error: str | None


class InspectTableResponse(BaseModel):
    format: str
    object_type: str
    example_object: str
    row_count: int
    columns: list[str]
    question_columns: list[str]
    attribute_columns: list[str]


class ResearchTableResponse(BaseModel):
    table: list[dict[str, Any]]
    format: str
    output_path: str
    object_type: str
    example_object: str
    row_count: int
    columns: list[str]
    question_columns: list[str]
    attribute_columns: list[str]
    includes_sources: bool
    includes_sources_summary: bool
    includes_auto_tags: bool
    includes_nearest_neighbours: bool
    mean_count_fields_researched: float
    researched_fields: list[str]
    sources: list[str]
    usage: QueryUsage


class PrettifyCodexLogResponse(BaseModel):
    output_path: str
    completed_turn_count: int
    image_count: int
    tool_call_count: int
    total_token_count: int | None
