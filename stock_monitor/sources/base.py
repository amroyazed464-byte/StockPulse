"""Abstract base class for async stock quote data sources."""

from __future__ import annotations

import asyncio
import logging
import random as _random
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import httpx
from typing import TypedDict

if TYPE_CHECKING:
    from typing import NotRequired


class QuoteDict(TypedDict, total=False):
    """Typed dictionary for a single stock quote."""

    price: float
    change: float
    change_pct: float
    open: float | None
    high: float | None
    low: float | None
    volume: int
    prev_close: float | None
    source: str
    market: str  # "us", "sh", or "sz"

    # EastMoney-only extended fields
    market_cap: float
    pe: float | None
    eps: float | None


class BaseSource(ABC):
    """Abstract base for async stock quote data sources.

    Subclasses implement ``_build_url()`` and ``_parse_response()``.
    ``fetch()`` provides async exponential-backoff retry using the shared
    ``httpx.AsyncClient``.
    """

    name: str = "base"
    _client: httpx.AsyncClient
    _logger: logging.Logger

    def __init__(
        self,
        client: httpx.AsyncClient,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self._client = client
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._logger = logging.getLogger(f"stock_monitor.sources.{self.name}")

    # ── Subclass contract ────────────────────────────────────────────

    @abstractmethod
    def _build_url(self, symbol: str) -> str:
        """Build the API URL for the given symbol."""
        ...

    @abstractmethod
    def _parse_response(self, raw: bytes, symbol: str) -> QuoteDict | None:
        """Parse the raw HTTP response into a *QuoteDict*, or None."""
        ...

    def _is_available(self) -> bool:
        """Override to return False if the source cannot be used."""
        return True

    # ── Public API ───────────────────────────────────────────────────

    async def fetch(self, symbol: str) -> QuoteDict | None:
        """Fetch a quote for *symbol* with async retry on failure."""
        if not self._is_available():
            return None
        return await self._fetch_with_retry(symbol)

    # ── Internal async retry loop ────────────────────────────────────

    async def _fetch_with_retry(self, symbol: str) -> QuoteDict | None:
        """Core async fetch loop with exponential backoff.

        Each subclass uses the shared ``httpx.AsyncClient`` for all HTTP
        requests.  Retries use ``asyncio.sleep`` so the event loop stays
        free during backoff.
        """
        url = self._build_url(symbol)
        headers = self._headers()

        for attempt in range(self.max_retries):
            try:
                resp = await self._client.get(
                    url,
                    headers=headers,
                    follow_redirects=True,
                )
                result = self._parse_response(resp.content, symbol)
                if result is not None and result.get("price") is not None:
                    result.setdefault("source", self.name)
                    return result

                # Response parsed but no valid price — retry
                if attempt < self.max_retries - 1:
                    wait = min(self.base_delay * (2 ** attempt), self.max_delay)
                    self._logger.debug(
                        "%s: empty/partial response for %s, retry in %.1fs",
                        self.name, symbol, wait,
                    )
                    await asyncio.sleep(wait)

            except (httpx.TimeoutException, httpx.ConnectError,
                    httpx.RemoteProtocolError, OSError) as exc:
                if attempt < self.max_retries - 1:
                    wait = min(self.base_delay * (2 ** attempt), self.max_delay)
                    jitter = _random.uniform(0, wait * 0.1)
                    total_wait = wait + jitter
                    self._logger.debug(
                        "%s fetch failed for %s (attempt %d/%d): %s. "
                        "Retrying in %.1fs",
                        self.name, symbol, attempt + 1, self.max_retries,
                        exc, total_wait,
                    )
                    await asyncio.sleep(total_wait)
                else:
                    self._logger.warning(
                        "%s: all %d attempts exhausted for %s: %s",
                        self.name, self.max_retries, symbol, exc,
                    )
        return None

    def _headers(self) -> dict[str, str]:
        """Return HTTP headers for the request. Override if needed."""
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
        }
