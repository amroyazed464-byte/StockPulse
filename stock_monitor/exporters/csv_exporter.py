"""CSV exporter for stock quotes."""

from __future__ import annotations

import csv
import logging
from pathlib import Path
from typing import Any

from stock_monitor.exporters.base import BaseExporter
from stock_monitor.utils import fmt_ts

logger = logging.getLogger("stock_monitor.exporters.csv")

CSV_FIELDS = [
    "timestamp", "symbol",
    "price", "change", "change_pct",
    "open", "high", "low",
    "volume", "prev_close",
    "source", "market",
]


class CsvExporter(BaseExporter):
    """Append-mode CSV writer using ``csv.DictWriter``.

    A header row is written automatically when the file is new or empty.
    Every ``write()`` call is flushed immediately for crash safety.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file: Any = None
        self._writer: csv.DictWriter | None = None

    def open(self) -> None:
        needs_header = not self.path.exists() or self.path.stat().st_size == 0
        self._file = open(self.path, "a", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(self._file, fieldnames=CSV_FIELDS)
        if needs_header:
            self._writer.writeheader()
            self._file.flush()
        logger.info("CSV exporter opened: %s", self.path)

    def write(self, symbol: str, quote: dict[str, Any]) -> None:
        if self._writer is None:
            return
        row = {
            "timestamp": fmt_ts(),
            "symbol": symbol,
            "price": _fmt(quote.get("price")),
            "change": _fmt(quote.get("change")),
            "change_pct": _fmt(quote.get("change_pct")),
            "open": _fmt(quote.get("open")),
            "high": _fmt(quote.get("high")),
            "low": _fmt(quote.get("low")),
            "volume": quote.get("volume", 0),
            "prev_close": _fmt(quote.get("prev_close")),
            "source": quote.get("source", "?"),
            "market": quote.get("market", "us"),
        }
        self._writer.writerow(row)
        self._file.flush()  # type: ignore[union-attr]

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
            self._writer = None


def _fmt(val: Any) -> str:
    """Format a numeric value for CSV, returning '' for None."""
    if val is None:
        return ""
    if isinstance(val, float):
        return f"{val:.4f}"
    return str(val)
