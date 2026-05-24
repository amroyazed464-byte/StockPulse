"""East Money (push2.eastmoney.com) quote source — US stocks + A-shares.

This source applies stronger per-request retry (5 attempts, 1.5–4 s
jitter) because EastMoney frequently rate-limits or connection-resets.
"""

from __future__ import annotations

import json
import logging
import random as _random
import time as _time

from stock_monitor.sources.base import BaseSource, QuoteDict
from stock_monitor.utils import market_secid_prefix, parse_symbol_market

# ── EastMoney-specific retry constants ──────────────────────────────
_EM_MAX_RETRIES = 5
_EM_BASE_DELAY = 1.5         # seconds — jitter pushes to 1.5–4 s
_EM_MAX_DELAY = 12.0         # cap exponential backoff at 12 s
_EM_TIMEOUT = 6              # per-request HTTP timeout


class EastMoneySource(BaseSource):
    """Stock quotes via East Money's JSON API.

    Supports US stocks (NVDA, AAPL) and Chinese A-shares (600519.SH,
    000333.SZ).  Market type is auto-detected from the symbol suffix.

    Has the richest field set (price, OHLC, volume, market cap, P/E,
    EPS) but is also the most rate-limit-prone source, so its
    ``fetch()`` uses 5-attempt exponential backoff with 1.5–4 s
    randomised delay per retry.
    """

    name = "eastmoney"

    # Price scaling differs by market: US → thousandths, A-shares → cents
    _PRICE_SCALE: dict[str, float] = {"us": 1000.0, "sh": 100.0, "sz": 100.0}

    # ── Init with EastMoney-tuned retry params ────────────────────

    def __init__(self) -> None:
        super().__init__(
            max_retries=_EM_MAX_RETRIES,
            base_delay=_EM_BASE_DELAY,
            max_delay=_EM_MAX_DELAY,
        )

    # ── Hooks ─────────────────────────────────────────────────────

    def _headers(self) -> dict[str, str]:
        return {
            **super()._headers(),
            "Referer": "https://quote.eastmoney.com/",
        }

    def _build_url(self, symbol: str) -> str:
        market, code = parse_symbol_market(symbol)
        prefix = market_secid_prefix(market)
        fields = (
            "f43,f44,f45,f46,f47,f48,f50,f51,f52,f57,f58,f60,"
            "f116,f162,f167,f168,f169,f170,f171"
        )
        return (
            "https://push2.eastmoney.com/api/qt/stock/get"
            f"?secid={prefix}.{code}&fields={fields}"
        )

    def _parse_response(self, raw: bytes, symbol: str) -> QuoteDict | None:
        data = json.loads(raw)
        d = data.get("data") or {}
        if not d:
            return None

        market, _code = parse_symbol_market(symbol)
        scale = self._PRICE_SCALE.get(market, 1000.0)

        def px(key: str) -> float | None:
            v = d.get(key)
            return v / scale if v is not None else None

        return QuoteDict(
            price=px("f43"),
            high=px("f44"),
            low=px("f45"),
            open=px("f46"),
            volume=d.get("f47", 0),
            prev_close=px("f60"),
            change=px("f169"),
            change_pct=(d.get("f170") or 0) / 100.0,
            market_cap=d.get("f116", 0),
            pe=px("f162"),
            eps=px("f167"),
            source="eastmoney",
            market=market,
        )

    # ── Override fetch to use wider-jitter backoff ────────────────

    def fetch(self, symbol: str) -> QuoteDict | None:
        """Fetch a quote with EastMoney-tuned exponential backoff.

        Uses 5 attempts with 1.5–4 s randomised delay per retry and a
        shorter HTTP timeout (6 s) so that the source fails fast and
        the monitor can fall through to Sina quickly.
        """
        if not self._is_available():
            return None

        import scrapling  # noqa: F811 (already imported in base)

        url = self._build_url(symbol)
        headers = self._headers()

        for attempt in range(self.max_retries):
            try:
                from scrapling import Fetcher

                resp = Fetcher.get(
                    url,
                    headers=headers,
                    stealthy_headers=False,
                    timeout=_EM_TIMEOUT,
                    retries=1,
                )
                result = self._parse_response(resp.body, symbol)
                if result is not None and result.get("price") is not None:
                    result.setdefault("source", self.name)
                    return result

                # Empty / partial response — retry with jitter
                if attempt < self.max_retries - 1:
                    wait = min(
                        self.base_delay * (2 ** attempt),
                        self.max_delay,
                    )
                    jitter = _random.uniform(0.5, wait * 0.8)  # 50–80% jitter
                    self._logger.debug(
                        "%s: empty response for %s, retry %d/%d in %.1fs",
                        self.name, symbol, attempt + 1, self.max_retries,
                        wait + jitter,
                    )
                    _time.sleep(wait + jitter)

            except Exception as exc:
                if attempt < self.max_retries - 1:
                    wait = min(
                        self.base_delay * (2 ** attempt),
                        self.max_delay,
                    )
                    jitter = _random.uniform(0.5, wait * 0.8)
                    self._logger.debug(
                        "%s fetch failed for %s (attempt %d/%d): %s. "
                        "Retrying in %.1fs",
                        self.name, symbol, attempt + 1,
                        self.max_retries, exc, wait + jitter,
                    )
                    _time.sleep(wait + jitter)
                else:
                    self._logger.warning(
                        "%s: all %d attempts exhausted for %s: %s",
                        self.name, self.max_retries, symbol, exc,
                    )

        return None
