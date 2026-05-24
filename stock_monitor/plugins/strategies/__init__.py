"""Strategy plugin base class and signal infrastructure.

Strategy plugins implement trading signals, decision logic, or
analytics that consume events and optionally produce signals.

To create a strategy plugin, subclass ``StrategyPlugin`` and implement:
  - ``wire(bus)`` — subscribe to relevant events
  - ``evaluate(event) -> Signal | None`` — produce a signal or None

Signals are published back onto the EventBus so other components
(display, notifiers, exporters) can react without tight coupling.
"""

from __future__ import annotations

import logging
import time
from abc import abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

from stock_monitor.plugins import PluginMeta, PluginRegistry, StockPulsePlugin

if TYPE_CHECKING:
    from stock_monitor.events import EventBus

logger = logging.getLogger("stock_monitor.plugins.strategies")

_CATEGORY = "strategy"


# ── Signal types ────────────────────────────────────────────────────


class SignalKind(Enum):
    """Classification of a trading or analytic signal."""

    BUY = auto()
    SELL = auto()
    HOLD = auto()
    OVERBOUGHT = auto()
    OVERSOLD = auto()
    DIVERGENCE = auto()
    VOLUME_ANOMALY = auto()
    TREND_CHANGE = auto()
    CUSTOM = auto()


@dataclass(slots=True)
class Signal:
    """A structured trading signal produced by a strategy plugin.

    Published onto the EventBus as a user-defined event so downstream
    consumers (display, notifiers, loggers) can react.

    Attributes:
        kind: Classification of the signal.
        symbol: Stock ticker the signal applies to.
        strength: Confidence or intensity (0.0–1.0).
        reason: Human-readable explanation.
        metadata: Arbitrary strategy-specific data.
        strategy: Name of the strategy that generated the signal.
        timestamp: UTC epoch when the signal was created.
    """

    kind: SignalKind
    symbol: str
    strength: float = 0.5
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    strategy: str = ""
    timestamp: float = field(default_factory=time.time)

    def __post_init__(self) -> None:
        if not 0.0 <= self.strength <= 1.0:
            raise ValueError(f"strength must be 0.0–1.0, got {self.strength}")


# ── Strategy plugin base ───────────────────────────────────────────


class StrategyPlugin(StockPulsePlugin):
    """Base class for trading-strategy and analytics plugins.

    Subclasses must implement ``wire`` and may implement ``evaluate``.
    Strategies typically subscribe to ``PriceUpdateEvent``,
    ``VolumeSpikeEvent``, or other events, and produce ``Signal``
    objects that are published back onto the EventBus.

    The ``publish_signal()`` helper publishes a signal to the bus if
    one is available after wiring.

    Attributes:
        meta: PluginMeta with ``category="strategy"``.
        _bus: Reference to the EventBus (set during ``wire()``).
    """

    meta: PluginMeta = PluginMeta(
        name="unnamed_strategy",
        category=_CATEGORY,
        description="Custom strategy plugin",
    )

    _bus: EventBus | None = None

    @abstractmethod
    def wire(self, bus: EventBus) -> None:
        """Subscribe to events. Store ``bus`` for signal publishing."""
        ...

    def evaluate(self, event: Any) -> Signal | None:
        """Evaluate an event and optionally produce a signal.

        Override in subclasses.  The default returns None.
        """
        return None

    async def publish_signal(self, signal: Signal) -> None:
        """Publish a signal onto the EventBus.

        The signal is published as a raw object — downstream consumers
        should subscribe to ``Signal`` directly.
        """
        if self._bus is None:
            logger.warning(
                "Cannot publish signal from %s — not wired", self.meta.name,
            )
            return
        signal.strategy = self.meta.name
        await self._bus.publish(signal)

    def teardown(self) -> None:
        """Default: no-op."""
