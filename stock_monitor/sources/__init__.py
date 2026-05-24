"""Data source package — async registry and source chain builder."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

if TYPE_CHECKING:
    from stock_monitor.sources.base import BaseSource, QuoteDict  # noqa: F401

logger = logging.getLogger("stock_monitor.sources")


def get_source_chain(
    order: list[str],
    client: httpx.AsyncClient,
) -> list["BaseSource"]:
    """Return instantiated async source objects in priority order.

    Args:
        order: List of source names, e.g. ``["sina", "eastmoney", "yahoo"]``.
        client: Shared ``httpx.AsyncClient`` for all sources.

    Returns:
        List of *BaseSource* instances. Unknown source names are skipped.
    """
    from stock_monitor.sources.eastmoney import EastMoneySource
    from stock_monitor.sources.sina import SinaSource
    from stock_monitor.sources.yahoo import YahooSource

    _registry: dict[str, type[BaseSource]] = {
        "eastmoney": EastMoneySource,
        "sina": SinaSource,
        "yahoo": YahooSource,
    }

    chain: list[BaseSource] = []
    for name in order:
        cls = _registry.get(name)
        if cls is None:
            logger.warning("Unknown source %r — skipped", name)
            continue
        chain.append(cls(client))
    return chain
