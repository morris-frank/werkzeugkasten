from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .services import (
    inspect_table_service,
    prettify_codex_log_service,
    research_list_service,
    research_table_service,
    summary_service,
)


class WerkzeugkastenHandler(BaseHTTPRequestHandler):
    server_version = "WerkzeugkastenREST/0.1"

    def do_GET(self) -> None:
        if self.path == "/health":
            self._write_json(200, {"ok": True})
            return
        self._write_json(404, {"error": "Not found"})

    def do_POST(self) -> None:
        try:
            payload = self._read_json()
            if self.path == "/summary":
                self._write_json(200, summary_service(payload))
                return
            if self.path == "/research/list":
                items = payload.get("items")
                question = payload.get("question", "")
                if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
                    raise ValueError("`items` must be an array of strings.")
                self._write_json(200, research_list_service(items, question, payload=payload))
                return
            if self.path == "/research/table":
                raw_table_text = payload.get("raw_table_text", "")
                source_name = str(payload.get("source_name", "pasted-table"))
                if not isinstance(raw_table_text, str):
                    raise ValueError("`raw_table_text` must be a string.")
                self._write_json(200, research_table_service(raw_table_text, source_name=source_name, payload=payload))
                return
            if self.path == "/table/inspect":
                raw_table_text = payload.get("raw_table_text", "")
                source_name = str(payload.get("source_name", "pasted-table"))
                if not isinstance(raw_table_text, str):
                    raise ValueError("`raw_table_text` must be a string.")
                self._write_json(200, inspect_table_service(raw_table_text, source_name))
                return
            if self.path == "/codex/prettify":
                path = payload.get("path")
                if not isinstance(path, str):
                    raise ValueError("`path` must be a string.")
                self._write_json(200, prettify_codex_log_service(path))
                return
            self._write_json(404, {"error": "Not found"})
        except Exception as exc:
            self._write_json(400, {"error": str(exc)})

    def log_message(self, format: str, *args: Any) -> None:
        return

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("Expected a JSON object.")
        return payload

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="werkzeugkasten-rest")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8787)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    server = ThreadingHTTPServer((args.host, args.port), WerkzeugkastenHandler)
    print(json.dumps({"host": args.host, "port": args.port}))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
