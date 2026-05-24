"""Utility functions: decoding, time formatting, volume formatting, async retry."""

from __future__ import annotations

import asyncio
import logging
import random as _random
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import TypeVar

logger = logging.getLogger("stock_monitor.utils")

T = TypeVar("T")

# ── String / encoding helpers ──────────────────────────────────────


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


# ── Symbol / market helpers ────────────────────────────────────────


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
        return "￥"  # full-width yen
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


# ── Async retry with exponential backoff ───────────────────────────


async def async_retry_with_backoff(
    func: Callable[[], Awaitable[T]],
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    *,
    jitter_pct: float = 0.1,
    _logger: logging.Logger | None = None,
) -> tuple[T | None, int]:
    """Execute an async callable with exponential backoff on exception.

    Returns ``(result, attempts_used)``.  *result* is None if all retries
    are exhausted.

    Args:
        func: Async callable that may raise on transient failures.
        max_retries: Maximum number of attempts.
        base_delay: Initial backoff delay in seconds.
        max_delay: Maximum backoff delay cap.
        jitter_pct: Fraction of delay to add as random jitter (0.0–1.0).
    """
    log = _logger or logger
    for attempt in range(max_retries):
        try:
            result = await func()
            return result, attempt + 1
        except Exception as exc:
            if attempt < max_retries - 1:
                wait = min(base_delay * (2 ** attempt), max_delay)
                jitter = _random.uniform(0, wait * jitter_pct)
                total_wait = wait + jitter
                log.debug(
                    "Attempt %d/%d failed: %s. Retrying in %.1fs",
                    attempt + 1, max_retries, exc, total_wait,
                )
                await asyncio.sleep(total_wait)
            else:
                log.warning("All %d attempts exhausted: %s", max_retries, exc)
    return None, max_retries


# ── Synchronous retry (kept for non-async contexts like yfinance wrapper) ─


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
                jitter = _random.uniform(0, wait * 0.1)
                log.debug("Attempt %d/%d failed: %s. Retrying in %.1fs",
                          attempt + 1, max_retries, exc, wait + jitter)
                time.sleep(wait + jitter)
            else:
                log.warning("All %d attempts exhausted: %s", max_retries, exc)
    return None
