"""Utility functions: decoding, time formatting, volume formatting, retry logic."""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import TypeVar

logger = logging.getLogger("stock_monitor.utils")

T = TypeVar("T")


def safe_decode(raw: bytes) -> str:
    """Decode bytes as UTF-8, falling back to GB18030 (used by Sina)."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gb18030")


def fmt_ts(timestamp: float | int | None = None) -> str:
    """Return HH:MM:SS formatted time string."""
    if timestamp:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%H:%M:%S")
    return datetime.now().strftime("%H:%M:%S")


def fmt_duration(seconds: float) -> str:
    """Return human-readable duration string."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    if seconds < 3600:
        m, s = divmod(seconds, 60)
        return f"{int(m)}m {int(s)}s"
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    return f"{int(h)}h {int(m)}m {int(s)}s"


def parse_symbol_market(symbol: str) -> tuple[str, str]:
    """Parse symbol into (market, clean_code).

    >>> parse_symbol_market("NVDA")      -> ("us", "NVDA")
    >>> parse_symbol_market("600519.SH") -> ("sh", "600519")
    >>> parse_symbol_market("000333.SZ") -> ("sz", "000333")
    >>> parse_symbol_market("AAPL.US")   -> ("us", "AAPL")
    """
    sym = symbol.upper().strip()
    if sym.endswith(".SH"):
        return ("sh", sym[:-3])
    if sym.endswith(".SZ"):
        return ("sz", sym[:-3])
    if sym.endswith(".US"):
        return ("us", sym[:-3])
    return ("us", sym)


def market_currency(market: str) -> str:
    """Return the currency symbol for a given market."""
    if market in ("sh", "sz"):
        return "￥"  # ￥ (full-width yen, GBK-safe)
    return "$"


def market_secid_prefix(market: str) -> str:
    """Return EastMoney secid prefix for a market."""
    return {"sh": "1", "sz": "0", "us": "105"}.get(market, "105")


def fmt_vol(vol: int | float) -> str:
    """Format volume as human-readable string: 12.35M, 456.7K, etc."""
    v = int(vol)
    if v >= 1_000_000_000:
        return f"{v / 1_000_000_000:.2f}B"
    if v >= 1_000_000:
        return f"{v / 1_000_000:.2f}M"
    if v >= 1_000:
        return f"{v / 1_000:.1f}K"
    return str(v)


def retry_with_backoff(
    func: Callable[[], T],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    *,
    _logger: logging.Logger | None = None,
) -> T | None:
    """Execute *func* with exponential backoff on exception.

    Args:
        func: Callable that may raise on transient failures.
        max_retries: Maximum number of attempts (default 3).
        base_delay: Initial backoff delay in seconds.
        max_delay: Maximum backoff delay cap.

    Returns:
        The result of *func*, or None if all retries exhausted.
    """
    log = _logger or logger
    for attempt in range(max_retries):
        try:
            return func()
        except Exception as exc:
            if attempt < max_retries - 1:
                wait = min(base_delay * (2 ** attempt), max_delay)
                jitter = random.uniform(0, wait * 0.1)
                log.debug("Attempt %d/%d failed: %s. Retrying in %.1fs",
                          attempt + 1, max_retries, exc, wait + jitter)
                time.sleep(wait + jitter)
            else:
                log.warning("All %d attempts exhausted: %s", max_retries, exc)
    return None
