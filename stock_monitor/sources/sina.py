"""Sina Finance (hq.sinajs.cn) US-stock quote source."""

from __future__ import annotations

import re

from stock_monitor.sources.base import BaseSource, QuoteDict
from stock_monitor.utils import parse_symbol_market, safe_decode


class SinaSource(BaseSource):
    """US stock quotes via Sina Finance's lightweight text API.

    Fast and simple, but fewer fields than EastMoney.
    """

    name = "sina"

    def _headers(self) -> dict[str, str]:
        return {
            **super()._headers(),
            "Referer": "https://finance.sina.com.cn/",
        }

    def _build_url(self, symbol: str) -> str:
        return f"https://hq.sinajs.cn/list=gb_{symbol.lower()}"

    def _parse_response(self, raw: bytes, symbol: str) -> QuoteDict | None:
        text = safe_decode(raw)
        m = re.search(r'"([^"]+)"', text)
        if not m:
            return None
        parts = m.group(1).split(",")
        if len(parts) < 10:
            return None

        def _f(idx: int) -> float | None:
            try:
                val = parts[idx]
                return float(val) if val else None
            except (ValueError, IndexError):
                return None

        market, _code = parse_symbol_market(symbol)

        return QuoteDict(
            price=float(parts[1]),
            change_pct=float(parts[2]),
            change=_f(4) or 0.0,
            open=_f(5),
            high=_f(6),
            low=_f(7),
            volume=int(parts[10]) if len(parts) > 10 and parts[10] else 0,
            prev_close=_f(3),
            source="sina",
            market=market,
        )
