"""East Money (push2.eastmoney.com) async quote source — US stocks + A-shares.

Uses wider per-request jitter (50–80%) because EastMoney is the most
rate-limit-prone source.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random as _random

import httpx

from stock_monitor.sources.base import BaseSource, QuoteDict
from stock_monitor.utils import market_secid_prefix, parse_symbol_market

_EM_MAX_RETRIES = 5
_EM_BASE_DELAY = 1.5
_EM_MAX_DELAY = 12.0


class EastMoneySource(BaseSource):
    """Async stock quotes via East Money's JSON API.

    Supports US stocks and Chinese A-shares.  Applies heavier retry
    (5 attempts) with randomised jitter because EastMoney frequently
    rate-limits.
    """

    name = "eastmoney"

    _PRICE_SCALE: dict[str, float] = {"us": 1000.0, "sh": 100.0, "sz": 100.0}

    def __init__(self, client: httpx.AsyncClient) -> None:
        super().__init__(
            client,
            max_retries=_EM_MAX_RETRIES,
            base_delay=_EM_BASE_DELAY,
            max_delay=_EM_MAX_DELAY,
        )

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

    async def fetch(self, symbol: str) -> QuoteDict | None:
        """Fetch with EastMoney-tuned async exponential backoff.

        Uses 5 attempts with 1.5–4 s randomised delay so the source
        fails fast and the monitor can fall through to Sina.
        """
        if not self._is_available():
            return None

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

                if attempt < self.max_retries - 1:
                    wait = min(self.base_delay * (2 ** attempt), self.max_delay)
                    jitter = _random.uniform(0.5, wait * 0.8)
                    self._logger.debug(
                        "%s: empty response for %s, retry %d/%d in %.1fs",
                        self.name, symbol, attempt + 1, self.max_retries,
                        wait + jitter,
                    )
                    await asyncio.sleep(wait + jitter)

            except (httpx.TimeoutException, httpx.ConnectError,
                    httpx.RemoteProtocolError, OSError) as exc:
                if attempt < self.max_retries - 1:
                    wait = min(self.base_delay * (2 ** attempt), self.max_delay)
                    jitter = _random.uniform(0.5, wait * 0.8)
                    self._logger.debug(
                        "%s fetch failed for %s (attempt %d/%d): %s. "
                        "Retrying in %.1fs",
                        self.name, symbol, attempt + 1, self.max_retries,
                        exc, wait + jitter,
                    )
                    await asyncio.sleep(wait + jitter)
                else:
                    self._logger.warning(
                        "%s: all %d attempts exhausted for %s: %s",
                        self.name, self.max_retries, symbol, exc,
                    )

        return None
