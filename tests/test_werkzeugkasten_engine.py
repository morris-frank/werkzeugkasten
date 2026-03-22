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

from werkzeugkasten_engine import codex_log, notion_export, research_list, research_table, summarize
from werkzeugkasten_engine.cli import main as cli_main
from werkzeugkasten_engine.core import choose_output_path, extract_json_block, summary_mirror_languages


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

    def test_choose_output_path_uses_explicit_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            explicit = Path(tmpdir) / "custom" / "result.md"
            selected = choose_output_path(datetime(2026, 3, 21), "Hello", explicit_path=explicit)
            self.assertEqual(selected, explicit)
            self.assertTrue(explicit.parent.exists())


class ResearchTableTests(unittest.TestCase):
    def test_guess_table_format(self) -> None:
        self.assertEqual(research_table.guess_table_format("| a | b |\n| --- | --- |\n| x | y |"), "markdown")
        self.assertEqual(research_table.guess_table_format("a,b\nx,y"), "csv")

    def test_inspect_table(self) -> None:
        preview = research_table.inspect_table("company,What do they do?,country\nOpenAI,,US\n")
        self.assertEqual(preview["detected_format"], "csv")
        self.assertEqual(preview["question_columns"], ["What do they do?"])
        self.assertEqual(preview["attribute_columns"], ["country"])

    def test_unique_header_name_suffixes_dynamic_columns(self) -> None:
        self.assertEqual(research_table.unique_header_name(["Name", "Sources"], "Sources"), "Sources 2")

    def test_research_options_normalize_dependencies(self) -> None:
        options = research_table.ResearchOptions(
            include_sources=False,
            include_source_raw=True,
            auto_tagging=False,
            nearest_neighbour=True,
        ).normalized()
        self.assertTrue(options.include_sources)
        self.assertTrue(options.include_source_raw)
        self.assertTrue(options.auto_tagging)
        self.assertTrue(options.nearest_neighbour)

    def test_normalization_examples(self) -> None:
        self.assertEqual(research_table.split_and_clean_items("water/air/soil", url_mode=False), ["Water", "Air", "Soil"])
        self.assertEqual(research_table.split_and_clean_items("water<br>air<br/>soil", url_mode=False), ["Water", "Air", "Soil"])
        self.assertEqual(research_table.split_and_clean_items("shotgun+16S/18S+LR", url_mode=False), ["Shotgun", "16S", "18S", "LR"])
        self.assertEqual(research_table.split_and_clean_items("B2B/NGO ([naturemetrics.com](http://naturemetrics.com/))", url_mode=False), ["B2B", "NGO"])
        self.assertEqual(research_table.normalize_url_value("https://www.useyardstick.com/?utm_source=openai"), "https://www.useyardstick.com")
        self.assertEqual(research_table.normalize_scalar_value("soil microbiome ([rhizebio.com](https://rhizebio.com/approach/))"), "Soil Microbiome")
        self.assertEqual(research_table.normalize_scalar_value("startup (rhizebio.com)"), "Startup")

    def test_run_research_dataset_respects_explicit_output_and_skip_logic(self) -> None:
        dataset = research_table.make_dataset_shape(
            source_name="pasted-table",
            detected_format="csv",
            headers=["Company", "What do they do?"],
            rows=[{"Company": "OpenAI", "What do they do?": "AI lab"}],
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "custom.md"
            result = research_table.run_research_dataset(
                dataset,
                options=research_table.ResearchOptions(output_path=str(output)),
            )
            self.assertEqual(result["output_path"], str(output))
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("## Skipped Rows", rendered)
            self.assertIn("- OpenAI", rendered)

    def test_run_research_dataset_merge_preserves_existing_dynamic_values(self) -> None:
        dataset = research_table.make_dataset_shape(
            source_name="pasted-table",
            detected_format="csv",
            headers=["Company", "What do they do?", "Sources"],
            rows=[{"Company": "OpenAI", "What do they do?": "", "Sources": "https://existing.example"}],
        )

        def fake_research_row(*_args, **_kwargs):
            return ({"What do they do?": "AI lab"}, '{"updates":{}}', ["https://new.example"], "")

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(research_table, "research_row", fake_research_row):
            output = Path(tmpdir) / "merge.md"
            research_table.run_research_dataset(
                dataset,
                options=research_table.ResearchOptions(
                    include_sources=True,
                    source_column_policy="merge",
                    output_path=str(output),
                ),
            )
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("https://existing.example", rendered)
            self.assertNotIn("https://new.example", rendered)

    def test_source_fetch_issues_are_reported(self) -> None:
        dataset = research_table.make_dataset_shape(
            source_name="pasted-table",
            detected_format="csv",
            headers=["Company", "What do they do?"],
            rows=[{"Company": "OpenAI", "What do they do?": ""}],
        )

        def fake_research_row(*_args, **_kwargs):
            return ({"What do they do?": "AI lab"}, '{"updates":{}}', ["https://blocked.example"], "")

        def fake_fetch(*_args, **_kwargs):
            return research_table.FetchResult(
                text="[Source fetch failed] https://blocked.example\nHTTP 403: Forbidden",
                status_code=403,
                error_class="HTTPError",
                message="Forbidden",
            )

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(research_table, "research_row", fake_research_row), patch.object(research_table, "fetch_source_raw_text", fake_fetch):
            output = Path(tmpdir) / "source-raw.md"
            research_table.run_research_dataset(
                dataset,
                options=research_table.ResearchOptions(
                    include_sources=True,
                    include_source_raw=True,
                    output_path=str(output),
                ),
            )
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("## Source Fetch Issues", rendered)
            self.assertIn("HTTP 403", rendered)

    def test_existing_sources_are_used_when_no_research_columns_are_missing(self) -> None:
        dataset = research_table.make_dataset_shape(
            source_name="pasted-table",
            detected_format="csv",
            headers=["Company", "Sources"],
            rows=[
                {
                    "Company": "OpenAI",
                    "Sources": "https://b.example/two<br>[one](https://a.example/one?utm_source=openai)",
                }
            ],
        )

        seen_urls: list[str] = []

        def fake_fetch(url: str, *_args, **_kwargs):
            seen_urls.append(url)
            return research_table.FetchResult(text=f"Fetched {url}")

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(research_table, "fetch_source_raw_text", fake_fetch):
            output = Path(tmpdir) / "existing-sources.md"
            research_table.run_research_dataset(
                dataset,
                options=research_table.ResearchOptions(
                    include_source_raw=True,
                    output_path=str(output),
                ),
            )
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("https://a.example/one", rendered)
            self.assertIn("https://b.example/two", rendered)
            self.assertNotIn("<br>", rendered)
            self.assertIn("https://a.example/one, https://b.example/two", rendered)
            self.assertEqual(seen_urls, ["https://a.example/one", "https://b.example/two"])

    def test_document_sources_are_downloaded_and_summarized(self) -> None:
        downloaded = Path(tempfile.gettempdir()) / "werkzeugkasten-test.pdf"
        downloaded.write_text("placeholder", encoding="utf-8")

        def fake_download(url: str) -> Path:
            self.assertEqual(url, "https://example.com/report.pdf")
            return downloaded

        def fake_summarize(path: Path, *, artifacts_directory: Path | None = None):
            self.assertEqual(path, downloaded)
            self.assertEqual(artifacts_directory, downloaded.parent)
            return {
                "input_path": str(downloaded),
                "contents_path": str(downloaded.parent / ".werkzeugkasten-test.pdf.contents.md"),
                "summary_path": str(downloaded.parent / "werkzeugkasten-test.pdf.summary.md"),
                "contents_markdown": "converted",
                "summary_markdown": "# Summary\nPDF summary",
            }

        with patch.object(research_table, "download_source_document", fake_download), patch.object(
            research_table, "summarize_local_file", fake_summarize
        ):
            result = research_table.fetch_source_raw_text("https://example.com/report.pdf", {})
            self.assertIn("PDF summary", result.text)
            self.assertIn("werkzeugkasten-test.pdf", result.text)

    def test_notion_export_requires_configuration(self) -> None:
        dataset = research_table.make_dataset_shape(
            source_name="pasted-table",
            detected_format="csv",
            headers=["Company", "What do they do?"],
            rows=[{"Company": "OpenAI", "What do they do?": "AI lab"}],
        )
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(ValueError, "Notion API Token"):
                research_table.run_research_dataset(
                    dataset,
                    options=research_table.ResearchOptions(export_to_notion=True),
                )

    def test_notion_grouped_sources_and_place_inference(self) -> None:
        specs = notion_export.infer_column_specs(
            headers=["Company", "Location", "Sources", "Record ID"],
            rows=[
                {
                    "Company": "OpenAI",
                    "Location": "Amsterdam HQ, Amsterdam, NL, 52.3676, 4.9041",
                    "Sources": "https://a.example,https://b.example",
                    "Record ID": "row-1",
                }
            ],
            key_header="Company",
            sources_column="Sources",
            tags_column=None,
            nearest_column=None,
            record_id_column="Record ID",
            list_like_columns={"Sources"},
            url_like_columns={"Sources"},
            long_text_columns=set(),
            open_meteo_key="openmeteo-test-key",
        )
        kinds = {spec.name: spec.kind for spec in specs}
        self.assertEqual(kinds["Location"], "place")
        self.assertNotIn("Record ID", kinds)
        self.assertEqual(
            notion_export.parse_place_value("Amsterdam HQ, Amsterdam, NL, 52.3676, 4.9041"),
            {
                "name": "Amsterdam HQ",
                "address": "Amsterdam HQ, Amsterdam, NL",
                "lat": 52.3676,
                "lon": 4.9041,
            },
        )
        self.assertIsNone(notion_export.parse_place_value("Amsterdam, NL"))
        no_geocoder_specs = notion_export.infer_column_specs(
            headers=["Company", "Location"],
            rows=[{"Company": "OpenAI", "Location": "Amsterdam, NL"}],
            key_header="Company",
            sources_column=None,
            tags_column=None,
            nearest_column=None,
            record_id_column=None,
            list_like_columns=set(),
            url_like_columns=set(),
            long_text_columns=set(),
            open_meteo_key="",
        )
        self.assertEqual({spec.name: spec.kind for spec in no_geocoder_specs}["Location"], "rich_text")
        self.assertEqual(
            notion_export.extract_source_urls("https://a.example/one<br>[two](https://b.example/two?utm_source=openai)"),
            ["https://a.example/one", "https://b.example/two"],
        )
        blocks = notion_export.render_row_children(
            {
                "Sources": "https://a.example/one<br>https://a.example/two,https://b.example/three",
                "Sources[RAW]": "URL: https://a.example/one\nBody one\n\nURL: https://b.example/three\nBody three",
            },
            {"Sources[RAW]"},
            "Sources",
            "Sources[RAW]",
        )
        self.assertTrue(any(block["type"] == "toggle" for block in blocks))

    def test_notion_safe_create_page_body_shrinks_before_api_limit(self) -> None:
        huge_a = "A" * 50_000
        huge_b = "B" * 10_000
        row = {
            "Sources": "https://a.example/x https://b.example/y",
            "Sources[RAW]": "URL: https://a.example/x\n" + huge_a + "\n\nURL: https://b.example/y\n" + huge_b,
        }
        properties = {"Name": {"title": notion_export.rich_text_array("Test")}}
        create_page_body = {
            "parent": {"type": "data_source_id", "data_source_id": "ds-id"},
            "properties": properties,
            "children": notion_export.render_row_children(
                row,
                {"Sources[RAW]"},
                "Sources",
                "Sources[RAW]",
            ),
        }
        self.assertGreater(notion_export.notion_request_json_byte_length(create_page_body), 20_000)
        with patch.object(notion_export, "NOTION_REQUEST_BODY_SAFE_MAX_BYTES", 20_000):
            safe = notion_export.ensure_notion_safe_create_page_body(
                create_page_body,
                row,
                {"Sources[RAW]"},
                "Sources",
                "Sources[RAW]",
            )
        self.assertLessEqual(notion_export.notion_request_json_byte_length(safe), 20_000)
        self.assertIn("Abbreviated", json.dumps(safe, ensure_ascii=True))
        self.assertGreater(
            json.dumps(safe, ensure_ascii=True).count("A"),
            json.dumps(safe, ensure_ascii=True).count("B"),
        )


class CoreTests(unittest.TestCase):
    def test_gpt5_models_get_medium_reasoning(self) -> None:
        from werkzeugkasten_engine import core

        self.assertEqual(core.reasoning_for_model("gpt-5.4"), {"effort": "medium"})
        self.assertIsNone(core.reasoning_for_model("gpt-4.1"))

    def test_summary_mirror_languages_parses_env(self) -> None:
        from werkzeugkasten_engine import core

        with patch.dict(os.environ, {core.SUMMARY_MIRROR_LANGUAGES_ENV: " A , B "}):
            self.assertEqual(summary_mirror_languages(), ["A", "B"])


class SummarizeTests(unittest.TestCase):
    def test_truncate_for_upload(self) -> None:
        text = "x" * (summarize.MAX_SUMMARY_INPUT + 1)
        truncated = summarize.truncate_for_upload(text)
        self.assertIn("[Truncated before upload]", truncated)

    def test_mirror_languages_instruction_phrasing(self) -> None:
        self.assertIn("English or German", summarize.mirror_languages_instruction(["English", "German"]))
        self.assertIn("French", summarize.mirror_languages_instruction(["French"]))
        self.assertIn("English, Spanish, or Italian", summarize.mirror_languages_instruction(["English", "Spanish", "Italian"]))

    def test_summary_prompt_uses_explicit_languages(self) -> None:
        body = summarize.summary_prompt("doc.txt", "ts", "hello", languages=["Dutch", "Polish"])
        self.assertIn("Dutch or Polish", body)
        self.assertIn("For all other languages, produce the summary in English.", body)


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
    def test_research_list_delegates_to_shared_dataset_pipeline(self) -> None:
        with patch(
            "werkzeugkasten_engine.research_list.run_research_dataset",
            return_value={
                "output_path": "/tmp/out.md",
                "headers": ["Item", "What?"],
                "question_columns": ["What?"],
                "attribute_columns": ["Sources"],
            },
        ) as run_dataset:
            result = research_list.run_research_list(
                ["A", "B"],
                "What",
                options=research_table.ResearchOptions(include_sources=True),
            )

        self.assertEqual(result["output_path"], "/tmp/out.md")
        self.assertEqual(result["item_count"], 2)
        self.assertEqual(result["completed_count"], 2)
        dataset = run_dataset.call_args.args[0]
        self.assertEqual(dataset.headers, ["Item", "What?"])
        self.assertEqual(dataset.question_columns, ["What?"])
        self.assertTrue(run_dataset.call_args.kwargs["options"].include_sources)

    def test_research_list_json_contract(self) -> None:
        with patch(
            "werkzeugkasten_engine.cli.run_research_list",
            return_value={
                "output_path": "/tmp/out.md",
                "item_count": 2,
                "completed_count": 2,
                "headers": ["Item", "Question"],
                "question_columns": ["Question"],
                "attribute_columns": [],
            },
        ):
            with patch("sys.stdin", io.StringIO(json.dumps({"items": ["A", "B"], "question": "Q"}))):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    rc = cli_main(["research-list"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            json.loads(stdout.getvalue()),
            {
                "output_path": "/tmp/out.md",
                "item_count": 2,
                "completed_count": 2,
                "headers": ["Item", "Question"],
                "question_columns": ["Question"],
                "attribute_columns": [],
            },
        )

    def test_research_options_parse_collision_policies(self) -> None:
        captured: dict[str, object] = {}

        def fake_research_list(items, question, progress=None, options=None):
            captured["options"] = options
            return {
                "output_path": "/tmp/out.md",
                "item_count": 1,
                "completed_count": 1,
                "headers": ["Item", "Question"],
                "question_columns": ["Question"],
                "attribute_columns": [],
            }

        payload = {
            "items": ["A"],
            "question": "Q",
            "include_source_raw": True,
            "nearest_neighbour": True,
            "source_column_policy": "overwrite",
            "source_raw_column_policy": "merge",
            "tag_column_policy": "overwrite",
            "nearest_column_policy": "overwrite",
            "record_id_column_policy": "overwrite",
            "output_path": "/tmp/custom.md",
            "export_to_notion": True,
        }
        with patch("werkzeugkasten_engine.cli.run_research_list", side_effect=fake_research_list):
            with patch("sys.stdin", io.StringIO(json.dumps(payload))):
                stdout = io.StringIO()
                with redirect_stdout(stdout):
                    rc = cli_main(["research-list"])
        self.assertEqual(rc, 0)
        options = captured["options"]
        self.assertTrue(options.include_sources)
        self.assertTrue(options.include_source_raw)
        self.assertTrue(options.auto_tagging)
        self.assertTrue(options.nearest_neighbour)
        self.assertTrue(options.export_to_notion)
        self.assertEqual(options.output_path, "/tmp/custom.md")
        self.assertEqual(options.source_column_policy, "overwrite")
        self.assertEqual(options.tag_column_policy, "overwrite")

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
