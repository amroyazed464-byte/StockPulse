"""Yahoo Finance (via yfinance) source — fallback when Chinese APIs are down."""

from __future__ import annotations

import logging

from stock_monitor.sources.base import BaseSource, QuoteDict
from stock_monitor.utils import parse_symbol_market

logger = logging.getLogger("stock_monitor.sources.yahoo")


class YahooSource(BaseSource):
    """US stock quotes via Yahoo Finance (yfinance library).

    This is a fallback source; its ``fetch()`` returns None immediately
    if ``yfinance`` is not installed.
    """

    name = "yahoo"
    _available: bool

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        super().__init__(max_retries, base_delay, max_delay)
        try:
            import yfinance  # noqa: F401
            self._available = True
        except ImportError:
            self._available = False
            self._logger.info("yfinance not installed — Yahoo source disabled")

    def _is_available(self) -> bool:
        return self._available

    def _build_url(self, symbol: str) -> str:
        # yfinance doesn't use URLs directly
        return ""

    def _parse_response(self, raw: bytes, symbol: str) -> QuoteDict | None:
        # Not used — we override fetch() directly
        return None

    def fetch(self, symbol: str) -> QuoteDict | None:
        """Fetch via yfinance. Overrides the template to bypass URL-based flow."""
        if not self._available:
            return None
        return self._do_fetch(symbol)

    def _do_fetch(self, symbol: str) -> QuoteDict | None:
        import time as _time
        import random as _random

        import yfinance as yf

        market, _code = parse_symbol_market(symbol)

        for attempt in range(self.max_retries):
            try:
                t = yf.Ticker(symbol)
                info = t.fast_info

                price = info.get("lastPrice") or info.get("regularMarketPrice")
                prev = info.get("previousClose") or info.get("regularMarketPreviousClose")
                volume = info.get("lastVolume") or info.get("regularMarketVolume")
                high = info.get("dayHigh") or info.get("regularMarketDayHigh")
                low = info.get("dayLow") or info.get("regularMarketDayLow")
                open_ = info.get("open") or info.get("regularMarketOpen")

                if price is None:
                    self._logger.debug(
                        "yfinance: no price data for %s (attempt %d)",
                        symbol, attempt + 1,
                    )
                    if attempt < self.max_retries - 1:
                        _time.sleep(self.base_delay * (2 ** attempt))
                    continue

                change = price - prev if (price and prev) else 0.0
                change_pct = (change / prev * 100) if prev else 0.0

                return QuoteDict(
                    price=price,
                    change=change,
                    change_pct=change_pct,
                    volume=volume or 0,
                    high=high,
                    low=low,
                    prev_close=prev,
                    open=open_,
                    source="yahoo",
                    market=market,
                )
            except Exception as exc:
                if attempt < self.max_retries - 1:
                    wait = min(self.base_delay * (2 ** attempt), self.max_delay)
                    jitter = _random.uniform(0, wait * 0.1)
                    self._logger.debug(
                        "yfinance fetch failed for %s (attempt %d): %s. "
                        "Retrying in %.1fs",
                        symbol, attempt + 1, exc, wait + jitter,
                    )
                    _time.sleep(wait + jitter)
                else:
                    self._logger.warning(
                        "yfinance: all %d attempts exhausted for %s: %s",
                        self.max_retries, symbol, exc,
                    )
        return None
