"""Price alert system — event-driven with publish/subscribe.

AlertManager subscribes to ``PriceUpdateEvent`` and publishes
``AlertTriggeredEvent`` when thresholds are crossed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from stock_monitor.config import AlertSpec

if TYPE_CHECKING:
    from stock_monitor.events import EventBus, PriceUpdateEvent

logger = logging.getLogger("stock_monitor.alerts")

# Operators that the alert engine understands
_OPERATORS: dict[str, Any] = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
}


@dataclass
class AlertCondition:
    """Runtime state for a single alert rule.

    Tracks whether the alert was previously triggered so we can detect
    *new* threshold crossings vs. staying above/below the threshold.
    """

    symbol: str
    field: str
    operator: str
    threshold: float
    cooldown_ticks: int = 5
    source: str = ""
    # Runtime state
    triggered: bool = False
    _ticks_since_trigger: int = 0

    def evaluate(self, quote: dict[str, Any]) -> bool:
        """Check if the alert condition is met for a quote.

        Returns True only on a *new* crossing (rising edge).
        """
        value = quote.get(self.field)
        if value is None:
            return False

        op_fn = _OPERATORS.get(self.operator)
        if op_fn is None:
            logger.warning("Unknown alert operator %r", self.operator)
            return False

        condition_met = op_fn(value, self.threshold)

        if condition_met and not self.triggered:
            # Rising edge — fire
            self.triggered = True
            self._ticks_since_trigger = 0
            logger.info(
                "Alert TRIGGERED: %s %s %s %s (value=%s)",
                self.symbol, self.field, self.operator, self.threshold, value,
            )
            return True

        if not condition_met:
            # Re-arm when price goes back below/above threshold
            self.triggered = False

        if self.triggered:
            self._ticks_since_trigger += 1

        return False

    def cooldown_expired(self) -> bool:
        """True if the cooldown has elapsed, allowing a re-fire."""
        return self._ticks_since_trigger >= self.cooldown_ticks


class AlertManager:
    """Event-driven price alert engine.

    Subscribes to ``PriceUpdateEvent`` via the bus.  When a threshold is
    crossed, publishes ``AlertTriggeredEvent`` so display and notifiers
    can react independently.

    Usage::

        mgr = AlertManager(config.alerts)
        mgr.wire(bus)  # subscribes to PriceUpdateEvent
    """

    def __init__(self, specs: list[AlertSpec]) -> None:
        self._conditions: list[AlertCondition] = []
        for spec in specs:
            self._conditions.append(AlertCondition(
                symbol=spec.symbol.upper(),
                field=spec.field,
                operator=spec.operator,
                threshold=spec.threshold,
                cooldown_ticks=spec.cooldown_ticks,
                source=spec.source,
            ))
        self._bus: EventBus | None = None
        logger.debug("Loaded %d alert conditions", len(self._conditions))

    # ── Event bus wiring ────────────────────────────────────────

    def wire(self, bus: EventBus) -> None:
        """Subscribe to events. Call once during setup."""
        from stock_monitor.events import PriceUpdateEvent

        self._bus = bus
        bus.subscribe(PriceUpdateEvent, self._on_price_update)

    # ── Event handler ───────────────────────────────────────────

    async def _on_price_update(self, event: PriceUpdateEvent) -> None:
        """Check all alert conditions for a price update and publish triggers."""
        if self._bus is None:
            return
        triggered = self.check(event.symbol, event.quote)
        for cond in triggered:
            await self._bus.publish(
                _build_alert_triggered(cond, event)
            )

    # ── Core logic (kept sync — pure CPU, called from async handler) ─

    def check(self, symbol: str, quote: dict[str, Any]) -> list[AlertCondition]:
        """Evaluate alert conditions for *symbol* against *quote*.

        Returns newly-triggered conditions.
        """
        triggered: list[AlertCondition] = []
        for cond in self._conditions:
            if cond.symbol != symbol:
                continue
            if self._evaluate_single(cond, quote):
                triggered.append(cond)
        return triggered

    def _evaluate_single(self, cond: AlertCondition,
                         quote: dict[str, Any]) -> bool:
        """Check one condition, respecting cooldown for re-triggers."""
        value = quote.get(cond.field)
        if value is None:
            return False

        op_fn = _OPERATORS.get(cond.operator)
        if op_fn is None:
            return False

        condition_met = op_fn(value, cond.threshold)

        if condition_met and not cond.triggered:
            cond.triggered = True
            cond._ticks_since_trigger = 0
            logger.info(
                "Alert TRIGGERED: %s %s %s %s (value=%s)",
                cond.symbol, cond.field, cond.operator,
                cond.threshold, value,
            )
            return True

        if not condition_met:
            cond.triggered = False
            return False

        cond._ticks_since_trigger += 1
        if cond.cooldown_expired():
            cond._ticks_since_trigger = 0
            logger.info(
                "Alert RE-FIRED: %s %s %s %s (value=%s)",
                cond.symbol, cond.field, cond.operator,
                cond.threshold, value,
            )
            return True

        return False

    # ── Helpers ─────────────────────────────────────────────────

    @property
    def conditions(self) -> list[AlertCondition]:
        """Read-only view of all alert conditions."""
        return list(self._conditions)


def _build_alert_triggered(cond: AlertCondition,
                           event: Any) -> Any:
    """Build an AlertTriggeredEvent from a condition and the source quote event."""
    from stock_monitor.events import AlertTriggeredEvent

    return AlertTriggeredEvent(
        symbol=cond.symbol,
        field=cond.field,
        operator=cond.operator,
        threshold=cond.threshold,
        current_value=event.quote.get(cond.field, 0),
        market=event.quote.get("market", "us"),
    )
