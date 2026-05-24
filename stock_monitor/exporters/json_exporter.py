"""JSON Lines exporter for stock quotes."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from stock_monitor.exporters.base import BaseExporter

logger = logging.getLogger("stock_monitor.exporters.json")


class JsonExporter(BaseExporter):
    """JSON Lines (one JSON object per line) exporter.

    Each line is a self-contained record, making it easy to stream or
    process with tools like ``jq``.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file: Any = None

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "a", encoding="utf-8")
        logger.info("JSON exporter opened: %s", self.path)

    def write(self, symbol: str, quote: dict[str, Any]) -> None:
        if self._file is None:
            return
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
        }
        # Flatten quote dict, converting None→null for valid JSON
        for key, val in quote.items():
            record[key] = val

        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
