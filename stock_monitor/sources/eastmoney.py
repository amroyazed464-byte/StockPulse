"""East Money (push2.eastmoney.com) quote source — US stocks + A-shares."""

from __future__ import annotations

import json

from stock_monitor.sources.base import BaseSource, QuoteDict
from stock_monitor.utils import market_secid_prefix, parse_symbol_market


class EastMoneySource(BaseSource):
    """Stock quotes via East Money's JSON API.

    Supports US stocks (NVDA, AAPL) and Chinese A-shares (600519.SH, 000333.SZ).
    Market type is auto-detected from the symbol suffix.

    Provides the richest field set: price, OHLC, volume, market cap,
    P/E ratio, EPS.
    """

    name = "eastmoney"

    # Price scaling differs by market: US returns thousandths, A-shares return cents
    _PRICE_SCALE: dict[str, float] = {"us": 1000.0, "sh": 100.0, "sz": 100.0}

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
