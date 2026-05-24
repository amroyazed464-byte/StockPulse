"""Data source package — registry, abstract base, and concrete implementations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from stock_monitor.sources.base import QuoteDict  # noqa: F401


# Registry: maps config name → source class (lazy to avoid circular imports)
def get_source_chain(order: list[str]) -> list:
    """Return instantiated source objects in priority order.

    Args:
        order: List of source names, e.g. ``["eastmoney", "sina", "yahoo"]``.

    Returns:
        List of *BaseSource* instances. Sources whose import fails are
        silently skipped.
    """
    from stock_monitor.sources.eastmoney import EastMoneySource
    from stock_monitor.sources.sina import SinaSource
    from stock_monitor.sources.yahoo import YahooSource

    _registry = {
        "eastmoney": EastMoneySource,
        "sina": SinaSource,
        "yahoo": YahooSource,
    }

    chain: list = []
    for name in order:
        cls = _registry.get(name)
        if cls is None:
            import logging
            logging.getLogger("stock_monitor.sources").warning(
                "Unknown source %r — skipped", name
            )
            continue
        chain.append(cls())
    return chain
