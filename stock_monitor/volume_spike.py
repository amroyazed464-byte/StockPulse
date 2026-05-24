"""Volume spike detector — event-driven anomaly detection.

Subscribes to ``PriceUpdateEvent``, maintains a rolling volume window
per symbol, and publishes ``VolumeSpikeEvent`` when the current volume
exceeds the trailing average by a configurable ratio.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import field, dataclass
from typing import TYPE_CHECKING

from stock_monitor.events import PriceUpdateEvent, VolumeSpikeEvent

if TYPE_CHECKING:
    from stock_monitor.events import EventBus

logger = logging.getLogger("stock_monitor.volume_spike")


class VolumeSpikeDetector:
    """Detect anomalous volume surges using a rolling simple moving average.

    Subscribes to ``PriceUpdateEvent`` via the bus.  Maintains a window
    of the last *N* volume samples per symbol.  When a new sample exceeds
    ``avg * spike_ratio``, a ``VolumeSpikeEvent`` is published.

    Args:
        window_size: Number of samples in the rolling average (default 20).
        spike_ratio: Multiplier over the average that constitutes a spike
            (default 3.0, i.e. 3× the trailing average).
        min_samples: Minimum samples required before evaluating (avoids
            false positives at session start).
    """

    def __init__(
        self,
        window_size: int = 20,
        spike_ratio: float = 3.0,
        min_samples: int = 5,
    ) -> None:
        self._window_size = window_size
        self._spike_ratio = spike_ratio
        self._min_samples = min_samples
        self._history: dict[str, list[int]] = defaultdict(list)
        self._bus: EventBus | None = None

    # ── Event bus wiring ──────────────────────────────────────────

    def wire(self, bus: EventBus) -> None:
        """Subscribe to price updates. Call once during setup."""
        self._bus = bus
        bus.subscribe(PriceUpdateEvent, self._on_price_update)

    # ── Event handler ─────────────────────────────────────────────

    async def _on_price_update(self, event: PriceUpdateEvent) -> None:
        """Check for volume spikes on every price update."""
        if self._bus is None:
            return

        vol = event.quote.get("volume", 0)
        if not vol or vol <= 0:
            return

        symbol = event.symbol
        history = self._history[symbol]
        history.append(vol)

        # Keep window bounded
        if len(history) > self._window_size:
            history.pop(0)

        # Not enough data yet — suppress
        if len(history) < self._min_samples:
            return

        avg = sum(history[:-1]) / (len(history) - 1)
        if avg <= 0:
            return

        ratio = vol / avg
        if ratio >= self._spike_ratio:
            logger.info(
                "Volume spike: %s vol=%d avg=%.0f ratio=%.1fx",
                symbol, vol, avg, ratio,
            )
            await self._bus.publish(VolumeSpikeEvent(
                symbol=symbol,
                volume=vol,
                avg_volume=int(avg),
                spike_ratio=ratio,
            ))

    # ── Inspection ────────────────────────────────────────────────

    @property
    def tracked_symbols(self) -> list[str]:
        """Symbols currently tracked in the rolling window."""
        return list(self._history.keys())
