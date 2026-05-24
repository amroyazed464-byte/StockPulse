"""Sina Finance (hq.sinajs.cn) quote source — US stocks + A-shares."""

from __future__ import annotations

import re

from stock_monitor.sources.base import BaseSource, QuoteDict
from stock_monitor.utils import parse_symbol_market, safe_decode


class SinaSource(BaseSource):
    """Stock quotes via Sina Finance's lightweight text API.

    Supports both US stocks (``gb_`` prefix) and Chinese A-shares
    (``sh`` / ``sz`` prefix).  Field layout differs by market.
    """

    name = "sina"

    def _headers(self) -> dict[str, str]:
        return {
            **super()._headers(),
            "Referer": "https://finance.sina.com.cn/",
        }

    def _build_url(self, symbol: str) -> str:
        market, code = parse_symbol_market(symbol)
        if market == "sh":
            return f"https://hq.sinajs.cn/list=sh{code}"
        if market == "sz":
            return f"https://hq.sinajs.cn/list=sz{code}"
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

        if market in ("sh", "sz"):
            # A-share format: name, open, prev_close, price, high, low, ...
            price = _f(3) or 0.0
            prev = _f(2)
            change = price - prev if (price and prev) else 0.0
            change_pct = (change / prev * 100) if prev else 0.0
            return QuoteDict(
                price=price,
                change=change,
                change_pct=change_pct,
                open=_f(1),
                high=_f(4),
                low=_f(5),
                volume=int(parts[8]) if len(parts) > 8 and parts[8] else 0,
                prev_close=prev,
                source="sina",
                market=market,
            )

        # US stock format: name, price, change_pct, ?, change, ?, high, low, ...
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
