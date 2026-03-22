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

from werkzeugkasten_engine import codex_log, research_list, research_table, summarize
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


class CodexLogTests(unittest.TestCase):
    def test_parse_codex_log_extracts_prompt_plan_answer_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "session.jsonl"
            log_path.write_text(
                "\n".join(
                    json.dumps(item)
                    for item in [
                        {
                            "timestamp": "2026-03-22T10:00:00Z",
                            "type": "event_msg",
                            "payload": {"type": "task_started", "turn_id": "turn-1"},
                        },
                        {
                            "timestamp": "2026-03-22T10:00:01Z",
                            "type": "event_msg",
                            "payload": {
                                "type": "user_message",
                                "message": "Review this repo.",
                                "images": ["https://example.com/a.png"],
                                "local_images": [],
                            },
                        },
                        {
                            "timestamp": "2026-03-22T10:00:02Z",
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "assistant",
                                "phase": "commentary",
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": "<proposed_plan>\n1. Inspect\n2. Patch\n</proposed_plan>",
                                    }
                                ],
                            },
                        },
                        {
                            "timestamp": "2026-03-22T10:00:03Z",
                            "type": "response_item",
                            "payload": {"type": "function_call", "name": "read_file"},
                        },
                        {
                            "timestamp": "2026-03-22T10:00:04Z",
                            "type": "event_msg",
                            "payload": {
                                "type": "token_count",
                                "info": {"total_token_usage": {"total_tokens": 100}},
                            },
                        },
                        {
                            "timestamp": "2026-03-22T10:00:06Z",
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "assistant",
                                "phase": "final_answer",
                                "content": [{"type": "output_text", "text": "# Done\nApplied the fix."}],
                            },
                        },
                        {
                            "timestamp": "2026-03-22T10:00:07Z",
                            "type": "event_msg",
                            "payload": {
                                "type": "token_count",
                                "info": {"total_token_usage": {"total_tokens": 1300}},
                            },
                        },
                        {
                            "timestamp": "2026-03-22T10:00:08Z",
                            "type": "event_msg",
                            "payload": {
                                "type": "task_complete",
                                "turn_id": "turn-1",
                                "last_agent_message": "Applied the fix.",
                            },
                        },
                    ]
                ),
                encoding="utf-8",
            )

            turns = codex_log.parse_codex_log(log_path)

        self.assertEqual(len(turns), 1)
        self.assertEqual(turns[0].prompt, "Review this repo.")
        self.assertEqual(turns[0].plan, "1. Inspect\n2. Patch")
        self.assertEqual(turns[0].answer, "# Done\nApplied the fix.")
        self.assertEqual(turns[0].image_count, 1)
        self.assertEqual(turns[0].tool_call_count, 1)
        self.assertEqual(turns[0].total_tokens, 1200)
        self.assertEqual(turns[0].duration_seconds, 8)

    def test_prettify_codex_log_writes_transcript_next_to_input(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "session.jsonl"
            log_path.write_text(
                "\n".join(
                    json.dumps(item)
                    for item in [
                        {
                            "timestamp": "2026-03-22T10:00:00Z",
                            "type": "event_msg",
                            "payload": {"type": "task_started", "turn_id": "turn-1"},
                        },
                        {
                            "timestamp": "2026-03-22T10:00:01Z",
                            "type": "event_msg",
                            "payload": {
                                "type": "user_message",
                                "message": "Prompt text",
                                "images": [],
                                "local_images": [],
                            },
                        },
                        {
                            "timestamp": "2026-03-22T10:00:02Z",
                            "type": "response_item",
                            "payload": {
                                "type": "message",
                                "role": "assistant",
                                "phase": "final_answer",
                                "content": [{"type": "output_text", "text": "Answer text"}],
                            },
                        },
                        {
                            "timestamp": "2026-03-22T10:00:03Z",
                            "type": "event_msg",
                            "payload": {"type": "task_complete", "turn_id": "turn-1", "last_agent_message": "Answer text"},
                        },
                    ]
                ),
                encoding="utf-8",
            )

            result = codex_log.prettify_codex_log(log_path)
            output_path = Path(result["output_path"])
            rendered = output_path.read_text(encoding="utf-8")

        self.assertEqual(output_path.name, "session.jsonl.transcript.md")
        self.assertIn("### 🎙️ Prompt", rendered)
        self.assertIn("### 🤖 Answer", rendered)
        self.assertIn("> Prompt text", rendered)
        self.assertIn("> Answer text", rendered)

    def test_parse_codex_log_ignores_aborted_turns(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            log_path = Path(tmpdir) / "session.jsonl"
            log_path.write_text(
                "\n".join(
                    json.dumps(item)
                    for item in [
                        {
                            "timestamp": "2026-03-22T10:00:00Z",
                            "type": "event_msg",
                            "payload": {"type": "task_started", "turn_id": "turn-1"},
                        },
                        {
                            "timestamp": "2026-03-22T10:00:01Z",
                            "type": "event_msg",
                            "payload": {
                                "type": "user_message",
                                "message": "Prompt text",
                                "images": [],
                                "local_images": [],
                            },
                        },
                        {
                            "timestamp": "2026-03-22T10:00:02Z",
                            "type": "event_msg",
                            "payload": {"type": "turn_aborted", "turn_id": "turn-1"},
                        },
                    ]
                ),
                encoding="utf-8",
            )

            turns = codex_log.parse_codex_log(log_path)

        self.assertEqual(turns, [])

    def test_real_archived_session_smoke(self) -> None:
        archived = sorted((Path.home() / ".codex" / "archived_sessions").glob("*.jsonl"))
        if not archived:
            self.skipTest("No archived Codex sessions available.")
        turns = codex_log.parse_codex_log(archived[-1])
        self.assertIsInstance(turns, list)


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

    def test_prettify_codex_log_json_contract(self) -> None:
        expected = {
            "output_path": "/tmp/session.jsonl.transcript.md",
            "completed_turn_count": 2,
            "image_count": 1,
            "tool_call_count": 3,
            "total_token_count": 4200,
        }
        with patch("werkzeugkasten_engine.cli.prettify_codex_log", return_value=expected):
            with patch("sys.stdin", io.StringIO(json.dumps({"path": "/tmp/session.jsonl"}))):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    rc = cli_main(["prettify-codex-log"])
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(stdout.getvalue()), expected)


if __name__ == "__main__":
    unittest.main()
