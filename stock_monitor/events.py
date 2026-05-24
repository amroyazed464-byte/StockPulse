"""Internal event bus — async publish/subscribe for decoupled components.

All system communication flows through typed events.  Producers publish
events; subscribers react.  No component holds a direct reference to any
other — everything is wired through the bus at startup.

Usage::

    bus = EventBus()

    @dataclass
    class MyEvent:
        payload: str

    async def handler(event: MyEvent) -> None:
        print(event.payload)

    bus.subscribe(MyEvent, handler)
    await bus.publish(MyEvent(payload="hello"))
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("stock_monitor.events")

# ── Event type registry (discriminator for fast lookup) ────────────

_EVENT_REGISTRY: dict[str, type] = {}  # discriminator → event class


def _register(discriminator: str):
    """Return a decorator that registers an event class."""
    def _decorator(cls: type) -> type:
        _EVENT_REGISTRY[discriminator] = cls
        cls._discriminator = discriminator  # type: ignore[attr-defined]
        return cls
    return _decorator


# ── Event dataclasses ───────────────────────────────────────────────


@_register("price_update")
@dataclass(slots=True)
class PriceUpdateEvent:
    """Published when a symbol quote changes (price or volume delta)."""

    symbol: str
    quote: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


@_register("alert_triggered")
@dataclass(slots=True)
class AlertTriggeredEvent:
    """Published when a price-alert threshold is crossed."""

    symbol: str
    field: str
    operator: str
    threshold: float
    current_value: float
    market: str = "us"
    timestamp: float = field(default_factory=time.time)


@_register("source_fail")
@dataclass(slots=True)
class SourceFailEvent:
    """Published when all sources fail for a single symbol."""

    symbol: str
    sources_attempted: list[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


@_register("market_status")
@dataclass(slots=True)
class MarketStatusEvent:
    """Published when the global source-health state changes.

    Status values:
        ``"all_sources_down"`` — every source failed this cycle.
        ``"recovered"`` — at least one source succeeded after a down period.
    """

    status: str  # "all_sources_down" | "recovered"
    consecutive_failures: int = 0
    backoff_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)


@_register("volume_spike")
@dataclass(slots=True)
class VolumeSpikeEvent:
    """Published when volume exceeds the trailing average by a configurable ratio."""

    symbol: str
    volume: int
    avg_volume: int
    spike_ratio: float
    timestamp: float = field(default_factory=time.time)


@_register("shutdown")
@dataclass(slots=True)
class ShutdownEvent:
    """Published when the monitor begins graceful shutdown."""

    reason: str = "user_interrupt"
    runtime_seconds: float = 0.0
    timestamp: float = field(default_factory=time.time)


@_register("stats_tick")
@dataclass(slots=True)
class StatsTickEvent:
    """Published every ``stats_interval`` seconds with aggregate session data."""

    symbols: list[str] = field(default_factory=list)
    last_quotes: dict[str, dict[str, Any]] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@_register("fetch_completed")
@dataclass(slots=True)
class FetchCompletedEvent:
    """Published after every successful or failed API fetch attempt.

    Carries the raw source name and whether it succeeded so downstream
    components (stats, logging, metrics) can react without the monitor
    calling them directly.
    """

    symbol: str
    source: str
    success: bool
    quote: dict[str, Any] | None = None
    timestamp: float = field(default_factory=time.time)


# Convenience union for type-checking subscribers
Event = (
    PriceUpdateEvent
    | AlertTriggeredEvent
    | SourceFailEvent
    | MarketStatusEvent
    | VolumeSpikeEvent
    | ShutdownEvent
    | StatsTickEvent
    | FetchCompletedEvent
)

# ── EventBus ────────────────────────────────────────────────────────

EventHandler = Callable[[Any], Any]  # async (event) -> None


def get_event_type(discriminator: str) -> type | None:
    """Look up an event class by its registered discriminator string.

    Useful for dynamic dispatch, plugin loading, and wire-format decoding.
    """
    return _EVENT_REGISTRY.get(discriminator)


def event_discriminator(event: Any) -> str:
    """Return the discriminator string for an event instance."""
    return getattr(type(event), "_discriminator", type(event).__name__)


class EventBus:
    """Lightweight async publish/subscribe bus.

    Subscribers register for a specific event *type*.  When ``publish()``
    is called, all matching handlers fire concurrently via
    ``asyncio.gather``.  Exceptions in one handler never affect others.

    Typical usage inside a monitor::

        bus = EventBus()

        # Wire components
        bus.subscribe(PriceUpdateEvent, display.on_price_update)
        bus.subscribe(PriceUpdateEvent, alert_mgr.on_price_update)
        bus.subscribe(AlertTriggeredEvent, display.on_alert)
        bus.subscribe(AlertTriggeredEvent, telegram.on_alert)

        # In the fetch loop
        await bus.publish(PriceUpdateEvent(symbol="NVDA", quote={...}))
    """

    def __init__(self, max_handlers: int = 200) -> None:
        self._subscribers: dict[type, list[EventHandler]] = defaultdict(list)
        self._max_handlers = max_handlers
        self._total_handlers = 0
        self._publish_count: dict[str, int] = defaultdict(int)

    # ── Subscription management ───────────────────────────────────

    def subscribe(self, event_type: type, handler: EventHandler) -> None:
        """Register *handler* to receive every ``publish(event_type, ...)``.

        Raises ``RuntimeError`` if the handler cap is exceeded.
        """
        if self._total_handlers >= self._max_handlers:
            raise RuntimeError(
                f"EventBus handler cap ({self._max_handlers}) reached"
            )
        self._subscribers[event_type].append(handler)
        self._total_handlers += 1
        logger.debug(
            "subscribe: %s → %s (total=%d)",
            event_type.__name__, _handler_name(handler), self._total_handlers,
        )

    def unsubscribe(self, event_type: type, handler: EventHandler) -> None:
        """Remove a previously registered handler.

        Safe to call with an unregistered handler (no-op).
        """
        try:
            self._subscribers[event_type].remove(handler)
            self._total_handlers -= 1
            logger.debug(
                "unsubscribe: %s → %s (total=%d)",
                event_type.__name__, _handler_name(handler), self._total_handlers,
            )
        except (ValueError, KeyError):
            pass

    # ── Publishing ────────────────────────────────────────────────

    async def publish(self, event: Any) -> None:
        """Fire *event* to all matching subscribers concurrently.

        Handlers that raise are logged but never propagate — one broken
        subscriber does not affect others.
        """
        event_type = type(event)
        handlers = self._subscribers.get(event_type, [])
        if not handlers:
            return

        self._publish_count[event_type.__name__] += 1

        # Fan-out: all handlers run concurrently
        results = await asyncio.gather(
            *(self._safe_invoke(h, event) for h in handlers),
            return_exceptions=True,
        )

        for result in results:
            if isinstance(result, Exception):
                logger.error(
                    "EventBus handler error in %s: %s",
                    event_type.__name__, result,
                )

    async def publish_many(self, events: list[Any]) -> None:
        """Publish multiple events concurrently.

        Equivalent to ``asyncio.gather(*(bus.publish(e) for e in events))``
        but avoids creating intermediate task objects per event.
        """
        if not events:
            return
        coros = [
            self._safe_invoke(h, e)
            for e in events
            for h in self._subscribers.get(type(e), [])
        ]
        if not coros:
            return
        results = await asyncio.gather(*coros, return_exceptions=True)
        for result in results:
            if isinstance(result, Exception):
                logger.error("EventBus handler error: %s", result)

    async def _safe_invoke(self, handler: EventHandler, event: Any) -> None:
        """Invoke one handler, catching and logging exceptions."""
        try:
            result = handler(event)
            # Support both sync and async handlers transparently
            if asyncio.iscoroutine(result):
                await result
        except Exception as exc:
            logger.error(
                "Handler %s raised %s for event %s",
                _handler_name(handler), exc, type(event).__name__,
            )

    # ── Introspection ──────────────────────────────────────────────

    @property
    def subscriber_count(self) -> int:
        """Total registered handler count across all event types."""
        return self._total_handlers

    def subscribers_for(self, event_type: type) -> int:
        """Number of handlers registered for *event_type*."""
        return len(self._subscribers.get(event_type, []))

    @property
    def stats(self) -> dict[str, int]:
        """Per-event-type publish counts since startup."""
        return dict(self._publish_count)


# ── Helpers ────────────────────────────────────────────────────────


def _handler_name(handler: EventHandler) -> str:
    """Return a readable name for a handler function or bound method."""
    try:
        return f"{handler.__module__}.{handler.__qualname__}"
    except AttributeError:
        return str(handler)
