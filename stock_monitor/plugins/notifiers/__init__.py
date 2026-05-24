"""Notifier plugin base class and built-in notifier bridge.

Notifier plugins dispatch alerts to external channels (Telegram, Slack,
email, webhooks, SMS, etc.).

To create a notifier plugin, subclass ``NotifierPlugin`` and implement:
  - ``send(event) -> bool`` — deliver an ``AlertTriggeredEvent``
  - ``wire(bus)`` — subscribe to ``AlertTriggeredEvent``
  - ``send_test() -> bool`` — optional connectivity test

Built-in notifiers (Telegram) are automatically bridged into the
plugin registry.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING

from stock_monitor.plugins import PluginMeta, PluginRegistry, StockPulsePlugin

if TYPE_CHECKING:
    from stock_monitor.events import AlertTriggeredEvent, EventBus

logger = logging.getLogger("stock_monitor.plugins.notifiers")

_CATEGORY = "notifier"


class NotifierPlugin(StockPulsePlugin):
    """Base class for notifier / alert-dispatch plugins.

    Subclasses must implement ``send`` and ``wire``.  Notifiers
    typically subscribe to ``AlertTriggeredEvent`` and may implement
    rate-limiting or batching internally.

    Attributes:
        meta: PluginMeta with ``category="notifier"``.
    """

    meta: PluginMeta = PluginMeta(
        name="unnamed_notifier",
        category=_CATEGORY,
        description="Custom notifier plugin",
    )

    @abstractmethod
    async def send(self, event: AlertTriggeredEvent) -> bool:
        """Deliver an alert to the external channel.

        Returns True if the delivery succeeded.
        """
        ...

    @abstractmethod
    def wire(self, bus: EventBus) -> None:
        """Subscribe to ``AlertTriggeredEvent``."""
        ...

    async def send_test(self) -> bool:
        """Send a connectivity test message. Override if supported."""
        logger.debug("send_test() not implemented for %s", self.meta.name)
        return False

    def teardown(self) -> None:
        """Default: no-op."""


# ── Built-in notifier bridge ────────────────────────────────────────


class _BuiltinNotifierAdapter(NotifierPlugin):
    """Wraps a built-in ``TelegramNotifier`` as a ``NotifierPlugin``."""

    def __init__(self, notifier: object, name: str = "builtin_notifier") -> None:
        self._notifier = notifier
        self.meta = PluginMeta(
            name=name,
            version="builtin",
            description=getattr(type(notifier), "__doc__", "") or "",
            author="StockPulse",
            category=_CATEGORY,
            enabled=True,
        )

    async def send(self, event: AlertTriggeredEvent) -> bool:
        if hasattr(self._notifier, "send_alert"):
            return await self._notifier.send_alert(  # type: ignore[attr-defined]
                symbol=event.symbol,
                field=event.field,
                operator=event.operator,
                threshold=event.threshold,
                current_value=event.current_value,
                market=event.market,
            )
        return False

    async def send_test(self) -> bool:
        if hasattr(self._notifier, "send_test"):
            return await self._notifier.send_test()  # type: ignore[attr-defined]
        return False

    def wire(self, bus: EventBus) -> None:
        if hasattr(self._notifier, "wire"):
            self._notifier.wire(bus)  # type: ignore[attr-defined]


def bridge_builtin_notifiers(
    notifiers: list[object],
    registry: PluginRegistry | None = None,
) -> list[NotifierPlugin]:
    """Wrap built-in notifier instances as ``NotifierPlugin`` objects.

    Args:
        notifiers: List of instantiated notifier objects (e.g. TelegramNotifier).
        registry: Optional registry to register into.

    Returns:
        List of wrapped ``NotifierPlugin`` instances.
    """
    plugins: list[NotifierPlugin] = []
    for n in notifiers:
        name = type(n).__name__
        plugin = _BuiltinNotifierAdapter(n, name=name)
        plugins.append(plugin)
        if registry is not None:
            registry.register(plugin)
    logger.debug("Bridged %d built-in notifier(s) as plugins", len(plugins))
    return plugins
