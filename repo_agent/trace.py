"""Append-only JSONL trace: every model call, tool call and budget event."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


class Tracer:
    """Writes one JSON object per event; keeps an in-memory copy for tests."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path else None
        self.events: list[dict[str, Any]] = []
        if self.path is not None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text("", encoding="utf-8")

    def event(self, kind: str, **data: Any) -> None:
        record = {"ts": round(time.time(), 4), "kind": kind, **data}
        self.events.append(record)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
