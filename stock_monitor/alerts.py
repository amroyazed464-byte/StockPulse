"""Price alert system with cooldown to prevent console spam."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from stock_monitor.config import AlertSpec

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
        Once triggered, the condition must re-arm before it fires again.
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
    """Manages a collection of alert conditions and checks quotes against them.

    Usage::

        mgr = AlertManager(config.alerts)
        for symbol, quote in fetch_loop():
            for triggered in mgr.check(symbol, quote):
                print(display.alert(triggered, quote))
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
        logger.debug("Loaded %d alert conditions", len(self._conditions))

    def check(self, symbol: str, quote: dict[str, Any]) -> list[AlertCondition]:
        """Evaluate all alert conditions for *symbol* against *quote*.

        Returns a list of newly-triggered conditions (empty if none).
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

        # Fresh trigger
        if condition_met and not cond.triggered:
            cond.triggered = True
            cond._ticks_since_trigger = 0
            logger.info(
                "Alert TRIGGERED: %s %s %s %s (value=%s)",
                cond.symbol, cond.field, cond.operator,
                cond.threshold, value,
            )
            return True

        # Re-arm when threshold no longer met
        if not condition_met:
            cond.triggered = False
            return False

        # Still triggered — check cooldown for re-fire
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

    def format_alert(self, spec: AlertSpec, quote: dict[str, Any]) -> str:
        """Build a human-readable alert message from an AlertSpec and quote."""
        value = quote.get(spec.field, "?")
        if spec.field == "price":
            val_s = f"${value:.2f}"
            thr_s = f"${spec.threshold:.2f}"
        elif spec.field == "change_pct":
            val_s = f"{value:+.2f}%"
            thr_s = f"{spec.threshold:+.2f}%"
        else:
            val_s = f"{value}"
            thr_s = f"{spec.threshold}"
        return (
            f"ALERT: {spec.symbol} {spec.field} {val_s} "
            f"{spec.operator} {thr_s}"
        )

    @property
    def conditions(self) -> list[AlertCondition]:
        """Read-only view of all alert conditions."""
        return list(self._conditions)
