from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from werkzeugkasten_engine import research_list, research_table, summarize
from werkzeugkasten_engine.cli import main as cli_main
from werkzeugkasten_engine.core import choose_output_path, extract_json_block


class ResearchListTests(unittest.TestCase):
    def test_parse_items(self) -> None:
        self.assertEqual(
            research_list.parse_items("- Apple\n2. Banana\n* Cherry"),
            ["Apple", "Banana", "Cherry"],
        )

    def test_extract_json_block(self) -> None:
        wrapped = '```json\n{"answer":"ok"}\n```'
        self.assertEqual(extract_json_block(wrapped), '{"answer":"ok"}')

    def test_choose_output_path_suffixes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            base = choose_output_path(datetime(2026, 3, 21), "Hello", Path(tmpdir))
            base.write_text("taken", encoding="utf-8")
            second = choose_output_path(datetime(2026, 3, 21), "Hello", Path(tmpdir))
            self.assertTrue(second.name.endswith("-2.md"))


class ResearchTableTests(unittest.TestCase):
    def test_guess_table_format(self) -> None:
        self.assertEqual(research_table.guess_table_format("| a | b |\n| --- | --- |\n| x | y |"), "markdown")
        self.assertEqual(research_table.guess_table_format("a,b\nx,y"), "csv")

    def test_inspect_table(self) -> None:
        preview = research_table.inspect_table("company,What do they do?,country\nOpenAI,,US\n")
        self.assertEqual(preview["detected_format"], "csv")
        self.assertEqual(preview["question_columns"], ["What do they do?"])
        self.assertEqual(preview["attribute_columns"], ["country"])


class SummarizeTests(unittest.TestCase):
    def test_truncate_for_upload(self) -> None:
        text = "x" * (summarize.MAX_SUMMARY_INPUT + 1)
        truncated = summarize.truncate_for_upload(text)
        self.assertIn("[Truncated before upload]", truncated)


class CliTests(unittest.TestCase):
    def test_research_list_json_contract(self) -> None:
        with patch(
            "werkzeugkasten_engine.cli.run_research_list",
            return_value={"output_path": "/tmp/out.md", "item_count": 2, "completed_count": 2},
        ):
            with patch("sys.stdin", io.StringIO(json.dumps({"items": ["A", "B"], "question": "Q"}))):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    rc = cli_main(["research-list"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"output_path": "/tmp/out.md", "item_count": 2, "completed_count": 2})

    def test_summarize_text_json_contract(self) -> None:
        with patch("werkzeugkasten_engine.cli.summarize_text_input", return_value="# Summary\nOk"):
            with patch("sys.stdin", io.StringIO(json.dumps({"title": "Note", "text": "hello"}))):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    rc = cli_main(["summarize-text"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {"summary_markdown": "# Summary\nOk"})


if __name__ == "__main__":
    unittest.main()
