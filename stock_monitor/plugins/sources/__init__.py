"""Source plugin base class and built-in source bridge.

Source plugins fetch stock quotes from data providers (web APIs,
WebSocket streams, local databases, etc.).

To create a source plugin, subclass ``SourcePlugin`` and implement:
  - ``fetch(symbol) -> QuoteDict | None``
  - Optionally ``_build_url`` / ``_parse_response`` if following the
    ``BaseSource`` pattern.

Built-in sources (Sina, EastMoney, Yahoo) are automatically bridged
into the plugin registry so they can be managed alongside third-party
source plugins.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING

import httpx

from stock_monitor.plugins import PluginMeta, PluginRegistry, StockPulsePlugin

if TYPE_CHECKING:
    from stock_monitor.events import EventBus
    from stock_monitor.sources.base import QuoteDict

logger = logging.getLogger("stock_monitor.plugins.sources")

_CATEGORY = "source"


class SourcePlugin(StockPulsePlugin):
    """Base class for data-source plugins.

    Subclasses must implement ``fetch(symbol)`` and may override
    ``wire(bus)`` to subscribe to events (e.g. for adaptive polling).

    The ``name`` property should return a short identifier used in
    source-order configuration (e.g. ``"sina"``, ``"eastmoney"``).

    Attributes:
        meta: PluginMeta with ``category="source"``.
        name: Short source identifier (must match config source_order).
        _client: Shared ``httpx.AsyncClient``, set via ``init_client()``.
    """

    meta: PluginMeta = PluginMeta(
        name="unnamed_source",
        category=_CATEGORY,
        description="Custom data source plugin",
    )

    _client: httpx.AsyncClient | None = None

    @property
    @abstractmethod
    def name(self) -> str:  # type: ignore[override]
        """Short identifier used in ``source_order`` config."""
        ...

    @abstractmethod
    async def fetch(self, symbol: str) -> QuoteDict | None:
        """Fetch a quote for *symbol*, returning a QuoteDict or None."""
        ...

    def init_client(self, client: httpx.AsyncClient) -> None:
        """Store a reference to the shared HTTP client."""
        self._client = client

    def wire(self, bus: EventBus) -> None:
        """Default: no-op. Override to subscribe to events."""

    def teardown(self) -> None:
        """Default: no-op."""


# ── Built-in source bridge ──────────────────────────────────────────


class _BuiltinSourceAdapter(SourcePlugin):
    """Wraps a built-in ``BaseSource`` as a ``SourcePlugin``."""

    def __init__(self, source: object) -> None:
        self._source = source
        source_name = getattr(source, "name", "unknown")
        source_desc = getattr(source, "__doc__", "") or ""
        self.meta = PluginMeta(
            name=source_name,
            version="builtin",
            description=source_desc.strip().split("\n")[0] if source_desc else "",
            author="StockPulse",
            category=_CATEGORY,
            enabled=True,
        )

    @property
    def name(self) -> str:
        return self._source.name  # type: ignore[attr-defined]

    async def fetch(self, symbol: str) -> QuoteDict | None:
        return await self._source.fetch(symbol)  # type: ignore[attr-defined]

    def wire(self, bus: EventBus) -> None:
        pass  # Built-in sources don't need the bus


def bridge_builtin_sources(
    sources: list[object],
    registry: PluginRegistry | None = None,
) -> list[SourcePlugin]:
    """Wrap built-in ``BaseSource`` instances as ``SourcePlugin`` objects.

    Args:
        sources: List of instantiated ``BaseSource`` objects.
        registry: Optional registry to register into.

    Returns:
        List of wrapped ``SourcePlugin`` instances.
    """
    plugins: list[SourcePlugin] = []
    for src in sources:
        plugin = _BuiltinSourceAdapter(src)
        plugins.append(plugin)
        if registry is not None:
            registry.register(plugin)
    logger.debug("Bridged %d built-in source(s) as plugins", len(plugins))
    return plugins
