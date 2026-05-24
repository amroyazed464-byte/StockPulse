"""Abstract base class for quote exporters.

Exporters perform fast synchronous file writes — they do NOT need to be
async because the data volume is low and writes complete in microseconds.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from stock_monitor.events import EventBus


class BaseExporter(ABC):
    """Abstract exporter for stock quotes.

    Subclasses implement ``open``, ``write``, ``close``, and ``wire``.
    Writes are synchronous (fast file I/O) and should be called from
    the main async context without ``await``.
    """

    @abstractmethod
    def open(self) -> None:
        """Open the exporter for writing."""
        ...

    @abstractmethod
    def write(self, symbol: str, quote: dict[str, Any]) -> None:
        """Write one quote record.

        Args:
            symbol: Stock ticker (e.g. ``"NVDA"``).
            quote: Quote dictionary (see ``QuoteDict``).
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """Flush and close the exporter."""
        ...

    def wire(self, bus: EventBus) -> None:
        """Subscribe to EventBus events. Override to receive price updates.

        Called once during startup. The default implementation is a
        no-op so that exporters with no event subscriptions (e.g.
        custom one-shot exporters) don't need to implement it.
        """
