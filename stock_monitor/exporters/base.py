"""Abstract base class for quote exporters.

Exporters perform fast synchronous file writes — they do NOT need to be
async because the data volume is low and writes complete in microseconds.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseExporter(ABC):
    """Abstract exporter for stock quotes.

    Subclasses implement ``open``, ``write``, and ``close``.
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
