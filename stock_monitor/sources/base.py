"""Abstract base class for stock quote data sources."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, TypedDict

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
    """Abstract base for stock quote data sources.

    Subclasses must implement ``_build_url()`` and ``_parse_response()``.
    The ``fetch()`` method provides exponential-backoff retry automatically.
    """

    name: str = "base"
    _logger: logging.Logger

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self._logger = logging.getLogger(f"stock_monitor.sources.{self.name}")

    # ── Subclass contract ───────────────────────────────────────

    @abstractmethod
    def _build_url(self, symbol: str) -> str:
        """Build the API URL for the given symbol."""
        ...

    @abstractmethod
    def _parse_response(self, raw: bytes, symbol: str) -> QuoteDict | None:
        """Parse the raw HTTP response into a *QuoteDict*, or None."""
        ...

    def _is_available(self) -> bool:
        """Override to return False if the source cannot be used (e.g.
        missing optional dependency)."""
        return True

    # ── Public API ──────────────────────────────────────────────

    def fetch(self, symbol: str) -> QuoteDict | None:
        """Fetch a quote for *symbol* with automatic retry on failure.

        Returns:
            A ``QuoteDict`` on success, or ``None`` if all retries fail
            or the source is unavailable.
        """
        if not self._is_available():
            return None
        return self._fetch_with_retry(symbol)

    # ── Internal ────────────────────────────────────────────────

    def _fetch_with_retry(self, symbol: str) -> QuoteDict | None:
        """Core fetch loop with exponential backoff."""
        import time as _time
        import random as _random

        from scrapling import Fetcher

        from stock_monitor.utils import safe_decode

        # Scrapling's import chain resets its logger to INFO on first import.
        # Silence it once per process lifetime.
        if not getattr(BaseSource, "_scrapling_silenced", False):
            _sl = logging.getLogger("scrapling")
            _sl.setLevel(logging.WARNING)
            for _h in _sl.handlers:
                _h.setLevel(logging.WARNING)
            BaseSource._scrapling_silenced = True  # type: ignore[attr-defined]

        url = self._build_url(symbol)

        for attempt in range(self.max_retries):
            try:
                resp = Fetcher.get(
                    url,
                    headers=self._headers(),
                    stealthy_headers=False,
                    timeout=8,
                )
                text = safe_decode(resp.body)
                result = self._parse_response(resp.body, symbol)
                if result is not None and result.get("price") is not None:
                    result.setdefault("source", self.name)
                    return result
                # Response parsed but no valid price — treat as transient
                if attempt < self.max_retries - 1:
                    wait = min(self.base_delay * (2 ** attempt), self.max_delay)
                    self._logger.debug(
                        "%s: empty/partial response for %s, retry in %.1fs",
                        self.name, symbol, wait,
                    )
                    _time.sleep(wait)
            except Exception as exc:
                if attempt < self.max_retries - 1:
                    wait = min(self.base_delay * (2 ** attempt), self.max_delay)
                    jitter = _random.uniform(0, wait * 0.1)
                    self._logger.debug(
                        "%s fetch failed for %s (attempt %d/%d): %s. "
                        "Retrying in %.1fs",
                        self.name, symbol, attempt + 1, self.max_retries,
                        exc, wait + jitter,
                    )
                    _time.sleep(wait + jitter)
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
