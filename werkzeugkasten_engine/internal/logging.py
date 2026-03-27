from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

ProgressCallback = Callable[[int, int, str], None]


class DebugLogger:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")

    def log(self, event: str, **payload: object) -> None:
        record = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "event": event,
            **payload,
        }
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
