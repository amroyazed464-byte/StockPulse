"""JSON Lines exporter — event-driven via PriceUpdateEvent subscription."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from stock_monitor.exporters.base import BaseExporter

if TYPE_CHECKING:
    from stock_monitor.events import EventBus, PriceUpdateEvent

logger = logging.getLogger("stock_monitor.exporters.json")


class JsonExporter(BaseExporter):
    """JSON Lines exporter — event-driven.

    Subscribes to ``PriceUpdateEvent`` so every tick is persisted
    automatically.  One JSON object per line.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._file: Any = None

    # ── Lifecycle ─────────────────────────────────────────────────

    def open(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._file = open(self.path, "a", encoding="utf-8")
        logger.info("JSON exporter opened: %s", self.path)

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None

    # ── Event bus wiring ──────────────────────────────────────────

    def wire(self, bus: EventBus) -> None:
        """Subscribe to price updates. Call once during setup."""
        from stock_monitor.events import PriceUpdateEvent

        bus.subscribe(PriceUpdateEvent, self._on_price_update)

    async def _on_price_update(self, event: PriceUpdateEvent) -> None:
        """Write a JSON line for every price update."""
        self.write(event.symbol, event.quote)

    # ── Core write ────────────────────────────────────────────────

    def write(self, symbol: str, quote: dict[str, Any]) -> None:
        if self._file is None:
            return
        record: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "symbol": symbol,
        }
        for key, val in quote.items():
            record[key] = val
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()
