"""Abstract base class for quote exporters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class BaseExporter(ABC):
    """Abstract exporter for stock quotes.

    Subclasses implement ``open``, ``write``, and ``close``.
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
