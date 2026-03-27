import csv
import re
from collections import defaultdict
from enum import Enum
from functools import partial
from io import StringIO
from typing import Any, Callable

import markdown
import pandas as pd
from numpy import average
from pandas.io.xml import is_url
from rapidfuzz import fuzz
from werkzeug.datastructures.cache_control import cache_control_property

from werkzeugkasten_engine.internal.value import as_canonical, as_url, as_urls, is_empty, normalize_list, str_contains


class Policy(Enum):
    MERGE = "merge"
    OVERWRITE = "overwrite"


class ColumnType(Enum):
    LONG_TEXT = "long_text"
    LOCATION = "location"
    URL = "url"
    LIST = "list"
    LOCATION = "location"
    QUESTION = "question"
    SCALAR = "scalar"


class Table:
    def __init__(self, content: str | pd.DataFrame, *, policy: Policy = Policy.MERGE):
        if isinstance(content, pd.DataFrame):
            self._df = content
            self.format = "dataframe"
        elif len(content.splitlines()[0].split("|")) >= 2:
            Table._parse_markdown_table(content)
        else:
            Table._parse_csv_table(content)
        self._df.set_index(self._df.columns[0], inplace=True)
        self._policies = defaultdict(lambda: Policy.MERGE, {column: policy for column in self._df.columns})

    def _parse_markdown_table(self, md: str, /) -> None:
        html = markdown.markdown(md, extensions=["tables"])
        self._df = pd.read_html(StringIO(html))[0]
        self.format = "markdown"

    def _parse_csv_table(self, csv: str, /) -> None:
        self._df = pd.read_csv(StringIO(csv), sep=None)
        self.format = "csv"

    def __str__(self) -> str:
        return self._df.to_markdown(index=False, tablefmt="github")

    def __contains__(self, column: str, /) -> bool:
        column = column.strip().lower()
        return any(c.strip().lower() == column for c in self._df.columns)

    def __setitem__(self, key: tuple[str, str], value: Any) -> None:
        row, column = key
        match self._policies[column]:
            case Policy.MERGE:
                if not is_empty(self._df.loc[row, column]):
                    self._df.loc[row, column] = value
            case Policy.OVERWRITE:
                self._df.loc[row, column] = value

    def safe_column(self, preferred: str, /) -> str:
        candidate = preferred.strip() or "Column"
        if candidate not in self:
            return candidate
        suffix = 2
        while f"{candidate} {suffix}" in self:
            suffix += 1
        return f"{candidate} {suffix}"

    @property
    def columns(self) -> list[str]:
        return self._df.columns.tolist()

    def column(self, column: str, /) -> str | None:
        column = column.strip().lower()
        for c in self._df.columns:
            if c.strip().lower() == column:
                return c
        return None

    @property
    def origin(self) -> str:
        return self._df.index.name

    def __len__(self) -> int:
        return len(self._df)

    @property
    def width(self) -> int:
        return len(self._df.columns)

    def _column_type(self, column: str, /) -> ColumnType:
        values = self._df[column].dropna().sample(min(25, len(self)))
        if not isinstance(values, pd.Series):
            return ColumnType.SCALAR

        avg_length = sum(len(value) for value in values) / len(values)
        multiline = any("\n" in value for value in values)
        if avg_length > 180 or multiline:
            return ColumnType.LONG_TEXT

        delimiter_hits = sum(1 for value in values if re.search(r"\s*(?:/|\+|,|;)\s*", value))
        if delimiter_hits >= max(2, len(values) // 3):
            return ColumnType.LIST

        score = sum(1 for value in values if as_url(value))
        if score and score == len(values):
            return ColumnType.URL

        return ColumnType.SCALAR

    def _normalize_column(self, column: str, /):
        match self._column_type(column):
            case ColumnType.QUESTION:
                pass
            case ColumnType.LOCATION:
                pass
            case ColumnType.LONG_TEXT:
                self._df[column] = self._df[column].str.strip()
            case ColumnType.URL:
                self._df[column] = self._df[column].apply(as_urls)
            case ColumnType.LIST | ColumnType.SCALAR:
                canonicals: list[str] = []
                for value in self._df[column]:
                    norm_value = normalize_list(value)
                    canonical = as_canonical(norm_value, canonicals)
                    canonicals.append(canonical)
                self._df[column] = canonicals
