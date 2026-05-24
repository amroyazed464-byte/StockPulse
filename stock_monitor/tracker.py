"""Per-symbol and session-wide statistics tracking."""

from __future__ import annotations

import logging
import time
from typing import Any

from stock_monitor.utils import fmt_duration

logger = logging.getLogger("stock_monitor.tracker")


class SymbolTracker:
    """Tracks state for a single stock symbol: last price, high/low, volume snapshots."""

    __slots__ = (
        "last_price", "last_vol", "price_high", "price_low",
        "tick_count", "vol_at_stats_start",
    )

    def __init__(self) -> None:
        self.last_price: float | None = None
        self.last_vol: int = 0
        self.price_high: float | None = None
        self.price_low: float | None = None
        self.tick_count: int = 0
        self.vol_at_stats_start: int = 0

    def update_high_low(self, price: float) -> None:
        """Update the tracked high / low range."""
        if self.price_high is None or price > self.price_high:
            self.price_high = price
        if self.price_low is None or price < self.price_low:
            self.price_low = price

    def record_tick(self, price: float, vol: int) -> None:
        """Record a price/volume change tick."""
        self.tick_count += 1
        self.last_price = price
        self.last_vol = vol


class SessionStats:
    """Aggregate session statistics across all symbols."""

    __slots__ = (
        "_start_time", "fetch_count", "tick_count", "error_count",
        "source_counts", "_trackers", "last_stats_time",
    )

    def __init__(self) -> None:
        self._start_time = time.time()
        self.fetch_count: int = 0
        self.tick_count: int = 0
        self.error_count: int = 0
        self.source_counts: dict[str, int] = {}
        self._trackers: dict[str, SymbolTracker] = {}
        self.last_stats_time: float = time.time()

    def get_tracker(self, symbol: str) -> SymbolTracker:
        """Return (creating if needed) the per-symbol tracker."""
        if symbol not in self._trackers:
            self._trackers[symbol] = SymbolTracker()
        return self._trackers[symbol]

    def record_fetch(self, symbol: str, quote: dict[str, Any]) -> None:
        """Record a successful API fetch (regardless of dedup)."""
        self.fetch_count += 1
        src = quote.get("source", "?")
        self.source_counts[src] = self.source_counts.get(src, 0) + 1
        self.get_tracker(symbol).update_high_low(quote["price"])

    def record_tick(self, symbol: str, quote: dict[str, Any]) -> None:
        """Record a logged tick (price/volume changed)."""
        self.tick_count += 1
        self.get_tracker(symbol).record_tick(
            quote["price"], quote.get("volume", 0)
        )

    def record_error(self) -> None:
        """Record a failed fetch cycle."""
        self.error_count += 1

    @property
    def elapsed(self) -> float:
        """Seconds elapsed since session start."""
        return time.time() - self._start_time

    @property
    def trackers(self) -> dict[str, SymbolTracker]:
        """Read-only view of per-symbol trackers."""
        return dict(self._trackers)

    def summary(self) -> str:
        """Build the session summary block for display on exit."""
        lines = [
            "",
            "═" * 72,
            "  SESSION SUMMARY",
            "═" * 72,
            f"  Runtime:          {fmt_duration(self.elapsed)}",
            f"  API fetches:      {self.fetch_count}",
            f"  Ticks logged:     {self.tick_count}",
            f"  Errors:           {self.error_count}",
        ]
        if self.fetch_count > 0:
            rate = self.elapsed / self.fetch_count
            lines.append(f"  Avg fetch rate:   {rate:.2f}s/fetch")
        if self.tick_count > 0:
            rate = self.elapsed / self.tick_count
            lines.append(f"  Avg tick rate:    {rate:.2f}s/tick")
        if self.source_counts:
            src_str = "  ".join(
                f"{k}: {v}" for k, v in self.source_counts.items()
            )
            lines.append(f"  Sources used:     {src_str}")
        # Per-symbol detail
        for sym, tr in self._trackers.items():
            parts = [f"  {sym:<6s}"]
            if tr.price_low is not None and tr.price_high is not None:
                parts.append(
                    f"${tr.price_low:.2f} – ${tr.price_high:.2f}"
                )
            if tr.last_price is not None:
                parts.append(f"last: ${tr.last_price:.2f}")
            parts.append(f"({tr.tick_count} ticks)")
            lines.append("  ".join(parts))
        lines.append("═" * 72)
        return "\n".join(lines)
