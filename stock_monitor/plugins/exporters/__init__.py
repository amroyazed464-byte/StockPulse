"""Exporter plugin base class and built-in exporter bridge.

Exporter plugins persist stock quote data to output formats (CSV, JSON,
Parquet, databases, cloud storage, etc.).

To create an exporter plugin, subclass ``ExporterPlugin`` and implement:
  - ``open()`` — initialize the output
  - ``write(symbol, quote)`` — persist one quote record
  - ``close()`` — flush and close
  - ``wire(bus)`` — subscribe to ``PriceUpdateEvent`` (or other events)

Built-in exporters (CSV, JSON) are automatically bridged into the
plugin registry.
"""

from __future__ import annotations

import logging
from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from stock_monitor.plugins import PluginMeta, PluginRegistry, StockPulsePlugin

if TYPE_CHECKING:
    from stock_monitor.events import EventBus

logger = logging.getLogger("stock_monitor.plugins.exporters")

_CATEGORY = "exporter"


class ExporterPlugin(StockPulsePlugin):
    """Base class for exporter plugins.

    Subclasses must implement ``open``, ``write``, ``close``, and
    ``wire``.  Exporters are typically synchronous (fast file I/O)
    and are called from async event handlers.

    Attributes:
        meta: PluginMeta with ``category="exporter"``.
    """

    meta: PluginMeta = PluginMeta(
        name="unnamed_exporter",
        category=_CATEGORY,
        description="Custom exporter plugin",
    )

    @abstractmethod
    def open(self) -> None:
        """Initialize the exporter (open file, connect to DB, etc.)."""
        ...

    @abstractmethod
    def write(self, symbol: str, quote: dict[str, Any]) -> None:
        """Persist a single quote record.

        Args:
            symbol: Stock ticker (e.g. ``"NVDA"``).
            quote: Quote dictionary (see ``QuoteDict``).
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Flush and close the exporter."""
        ...

    @abstractmethod
    def wire(self, bus: EventBus) -> None:
        """Subscribe to ``PriceUpdateEvent`` (or other events)."""
        ...

    def teardown(self) -> None:
        """Default: calls ``close()``."""
        try:
            self.close()
        except Exception as exc:
            logger.warning(
                "Exporter %s close error: %s", self.meta.name, exc,
            )


# ── Built-in exporter bridge ────────────────────────────────────────


class _BuiltinExporterAdapter(ExporterPlugin):
    """Wraps a built-in ``BaseExporter`` as an ``ExporterPlugin``."""

    def __init__(self, exporter: object, name: str = "builtin_exporter") -> None:
        self._exporter = exporter
        self.meta = PluginMeta(
            name=name,
            version="builtin",
            description=getattr(type(exporter), "__doc__", "") or "",
            author="StockPulse",
            category=_CATEGORY,
            enabled=True,
        )

    def open(self) -> None:
        self._exporter.open()  # type: ignore[attr-defined]

    def write(self, symbol: str, quote: dict[str, Any]) -> None:
        self._exporter.write(symbol, quote)  # type: ignore[attr-defined]

    def close(self) -> None:
        self._exporter.close()  # type: ignore[attr-defined]

    def wire(self, bus: EventBus) -> None:
        if hasattr(self._exporter, "wire"):
            self._exporter.wire(bus)  # type: ignore[attr-defined]


def bridge_builtin_exporters(
    exporters: list[object],
    registry: PluginRegistry | None = None,
) -> list[ExporterPlugin]:
    """Wrap built-in ``BaseExporter`` instances as ``ExporterPlugin`` objects.

    Args:
        exporters: List of instantiated ``BaseExporter`` objects.
        registry: Optional registry to register into.

    Returns:
        List of wrapped ``ExporterPlugin`` instances.
    """
    plugins: list[ExporterPlugin] = []
    for exp in exporters:
        name = type(exp).__name__
        plugin = _BuiltinExporterAdapter(exp, name=name)
        plugins.append(plugin)
        if registry is not None:
            registry.register(plugin)
    logger.debug("Bridged %d built-in exporter(s) as plugins", len(plugins))
    return plugins
