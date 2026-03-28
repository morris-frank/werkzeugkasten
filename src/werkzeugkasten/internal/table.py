from __future__ import annotations

import json
import re
from collections import defaultdict
from enum import Enum
from io import StringIO
from typing import Any, Iterator

import markdown
import pandas as pd

from .value import as_canonical, as_object_type, as_url, as_urls, is_empty, normalize_list, str_contains


class Policy(Enum):
    MERGE = "merge"
    OVERWRITE = "overwrite"


class ColumnType(Enum):
    LONG_TEXT = "long_text"
    LOCATION = "location"
    URL = "url"
    LIST = "list"
    QUESTION = "question"
    SCALAR = "scalar"


class Table:
    def __init__(self, content: str | pd.DataFrame | Table, *, policy: Policy = Policy.MERGE):
        if isinstance(content, Table):
            self._df = content._df.copy()
            self.format = content.format
            self._policies = content._policies.copy()
        elif isinstance(content, pd.DataFrame):
            self._df = content.copy()
            self.format = "dataframe"
        elif len(content.splitlines()[0].split("|")) >= 2:
            self._parse_markdown_table(content)
        else:
            self._parse_csv_table(content)
        self._df = self._df.fillna("").astype(str)
        self._df.set_index(self._df.columns[0], inplace=True)
        self._policies = defaultdict(lambda: Policy.MERGE, {column: policy for column in self._df.columns})

    def _parse_markdown_table(self, md: str, /) -> None:
        html = markdown.markdown(md, extensions=["tables"])
        self._df = pd.read_html(StringIO(html))[0]
        self.format = "markdown"

    def _parse_csv_table(self, csv: str, /) -> None:
        self._df = pd.read_csv(StringIO(csv), sep=None, engine="python", keep_default_na=False)
        self.format = "csv"

    @property
    def columns(self) -> list[str]:
        return self._df.columns.tolist()

    @property
    def objects(self) -> list[str]:
        return self._df.index.tolist()

    @property
    def object_type(self) -> str:
        return as_object_type(self._df.index.name or "Key")

    @property
    def origin(self) -> str:
        return self._df.index.name

    def __contains__(self, column: str, /) -> bool:
        column = column.strip().lower()
        return any(c.strip().lower() == column for c in self._df.columns)

    def __iter__(self) -> Iterator[dict[str, str]]:
        for key, row in self._df.iterrows():
            yield {**row, self.object_type: str(key)}

    def __setitem__(self, key: tuple[str, str] | str, value: Any | dict[str, str]) -> None:
        if isinstance(key, str):
            row = key
            if not isinstance(value, dict):
                raise ValueError("Value must be a dictionary if key is a string.")
            for column, value in value.items():
                if column in self:
                    self[row, column] = value

        else:
            row, column = key
            match self._policies[column]:
                case Policy.MERGE:
                    if is_empty(self._df.loc[row, column]):
                        self._df.loc[row, column] = value
                case Policy.OVERWRITE:
                    self._df.loc[row, column] = value

    def __len__(self) -> int:
        return len(self._df)

    def add_column(self, column: str, policy: Policy) -> None:
        if not column in self or policy == Policy.OVERWRITE:
            self._df[column] = ""
        self._policies[column] = policy
        self._normalize_column(column)

    def _column_type(self, column: str, /) -> ColumnType:
        values = self._df[column].dropna()
        if not isinstance(values, pd.Series) or values.empty:
            return ColumnType.SCALAR
        values = values.astype(str).sample(min(25, len(values)))

        avg_length = sum(len(value) for value in values) / len(values)
        multiline = any("\n" in value for value in values)
        if avg_length > 180 or multiline:
            return ColumnType.LONG_TEXT

        if "?" in column:
            return ColumnType.QUESTION
        if any(str_contains(column, token) for token in ("location", "address", "city", "country", "region", "state")):
            return ColumnType.LOCATION

        delimiter_hits = sum(1 for value in values if re.search(r"\s*(?:/|\+|,|;)\s*", value))
        if delimiter_hits >= max(2, len(values) // 3):
            return ColumnType.LIST

        score = sum(1 for value in values if as_url(value))
        if score and score == len(values):
            return ColumnType.URL

        return ColumnType.SCALAR

    def _normalize_column(self, column: str, /):
        match self._column_type(column):
            case ColumnType.LONG_TEXT:
                self._df[column] = self._df[column].str.strip()
            case ColumnType.URL:
                self._df[column] = self._df[column].apply(lambda value: ", ".join(as_urls(value)))
            case ColumnType.LIST | ColumnType.SCALAR:
                canonicals: list[str] = []
                for value in self._df[column]:
                    norm_value = ", ".join(normalize_list(value))
                    canonical = as_canonical(norm_value, canonicals)
                    canonicals.append(canonical)
                self._df[column] = canonicals
            case _:
                pass

    def _normalize_columns(self) -> None:
        for column in self._df.columns:
            self._normalize_column(column)

    def __str__(self) -> str:
        self._normalize_columns()
        return self._df.to_markdown(index=False, tablefmt="github")

    def to_json(self, without: set[str] = set()) -> str:
        self._normalize_columns()
        return json.dumps([row for row in self if not any(column in without for column in row)], ensure_ascii=False, indent=2)
