"""ANSI color helpers and quote formatting for console output."""

from __future__ import annotations

from typing import Any

from stock_monitor.utils import market_currency


# ── ANSI escape codes ───────────────────────────────────────────

class _Color:
    """ANSI SGR codes for terminal styling."""

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"


def _pc(change: float) -> str:
    """Return ANSI color code for a price change."""
    if change > 0:
        return _Color.GREEN
    if change < 0:
        return _Color.RED
    return _Color.WHITE


# ── Display class ───────────────────────────────────────────────

class Display:
    """Formats quotes, stats, alerts, and banners for console output.

    Args:
        use_color: If False, all output is plain text (no ANSI codes).
    """

    __slots__ = ("use_color",)

    def __init__(self, use_color: bool = True) -> None:
        self.use_color = use_color

    def banner(self, symbols: list[str], interval: float, csv_path: str) -> str:
        """Return the startup banner string."""
        sym_list = ", ".join(symbols)
        base = f"  {sym_list}  |  {interval}s interval  |  → {csv_path}"
        if self.use_color:
            base = f"{_Color.BOLD}{base}{_Color.RESET}"
        lines = [
            f"\n{base}",
            "  Sources: EastMoney / Sina / Yahoo",
        ]
        running = "  Running...  Ctrl+C to exit"
        if self.use_color:
            running = f"{_Color.DIM}{running}{_Color.RESET}"
        lines.append(running)
        return "\n".join(lines)

    def header(self) -> str:
        """Return the column header line."""
        hdr = (
            f"  {'Time':>8s}  {'Sym':<10s}  {'Price':>10s}  {'Change':>10s}  "
            f"{'Chg%':>8s}  {'Volume':>14s}  {'Hi':>8s}  {'Lo':>8s}  [Src]"
        )
        sep = "─" * 82
        return f"{hdr}\n{sep}"

    def price_line(self, symbol: str, quote: dict[str, Any]) -> str:
        """Format a single quote as a one-line display string."""
        market = quote.get("market", "us")
        curr = market_currency(market)
        price = quote["price"]
        change = quote.get("change") or 0.0
        chg_pct = quote.get("change_pct") or 0.0
        vol = quote.get("volume", 0)
        hi = f"{quote['high']:.2f}" if quote.get("high") else "N/A"
        lo = f"{quote['low']:.2f}" if quote.get("low") else "N/A"
        src = quote.get("source", "?")[:4].upper()
        direction = "+" if change >= 0 else ""
        vol_str = f"{vol:,.0f}" if vol else "N/A"
        ts = _fmt_ts_now()

        if self.use_color:
            c = _pc(change)
            return (
                f"  {_Color.DIM}{ts:>8s}{_Color.RESET}  "
                f"{_Color.CYAN}{symbol:<10s}{_Color.RESET}  "
                f"{_Color.BOLD}{c}{curr}{price:>9.2f}{_Color.RESET}  "
                f"{c}{direction}{change:>+9.4f}{_Color.RESET}  "
                f"{c}{direction}{chg_pct:>+7.2f}%{_Color.RESET}  "
                f"{_Color.DIM}{vol_str:>14s}{_Color.RESET}  "
                f"{_Color.DIM}{hi:>8s}  {lo:>8s}{_Color.RESET}  "
                f"[{src}]"
            )
        return (
            f"  {ts:>8s}  "
            f"{symbol:<10s}  "
            f"{curr}{price:>9.2f}  "
            f"{direction}{change:>+9.4f}  "
            f"{direction}{chg_pct:>+7.2f}%  "
            f"{vol_str:>14s}  "
            f"{hi:>8s}  {lo:>8s}  "
            f"[{src}]"
        )

    def stats_header(self) -> str:
        """Return the per-minute stats section header."""
        hdr = "── 1min Stats ─────────────────────────────────────────────"
        if self.use_color:
            hdr = f"{_Color.YELLOW}{hdr}{_Color.RESET}"
        return hdr

    def stats_line(self, symbol: str, quote: dict[str, Any],
                   cycle_delta_vol: int) -> str:
        """Return a per-minute stats line for one symbol."""
        from stock_monitor.utils import fmt_vol

        market = quote.get("market", "us")
        curr = market_currency(market)
        price = quote["price"]
        chg_pct = quote.get("change_pct") or 0.0
        vol = quote.get("volume", 0)
        direction = "+" if chg_pct >= 0 else ""
        delta_dir = "+" if cycle_delta_vol >= 0 else ""
        delta_str = (
            f"{delta_dir}{fmt_vol(abs(cycle_delta_vol))}"
            if cycle_delta_vol else "—"
        )

        if self.use_color:
            c = _pc(quote.get("change") or 0.0)
            return (
                f"    {_Color.CYAN}{symbol:<10s}{_Color.RESET}  "
                f"{c}{curr}{price:>9.2f}  {direction}{chg_pct:>+7.2f}%{_Color.RESET}  "
                f"vol {fmt_vol(vol):>8s}  "
                f"Δ {delta_str}"
            )
        return (
            f"    {symbol:<10s}  "
            f"{curr}{price:>9.2f}  {direction}{chg_pct:>+7.2f}%  "
            f"vol {fmt_vol(vol):>8s}  "
            f"Δ {delta_str}"
        )

    def stats_footer(self) -> str:
        """Return the per-minute stats section footer."""
        ft = "──────────────────────────────────────────────────────────"
        if self.use_color:
            ft = f"{_Color.YELLOW}{ft}{_Color.RESET}"
        return ft

    def alert(self, symbol: str, field: str, op: str,
              threshold: float, current: float, market: str = "us") -> str:
        """Return a highlighted alert message.

        Example:
            [ALERT] NVDA price $183.25 > $180.00
        """
        curr = market_currency(market)
        if field == "price":
            val_str = f"{curr}{current:.2f}"
            thr_str = f"{curr}{threshold:.2f}"
        elif field == "change_pct":
            val_str = f"{current:+.2f}%"
            thr_str = f"{threshold:+.2f}%"
        else:
            val_str = f"{current:.4f}"
            thr_str = f"{threshold:.4f}"

        msg = f"  [ALERT] {symbol} {field} {val_str} {op} {thr_str}"
        if self.use_color:
            msg = f"{_Color.BOLD}{_Color.YELLOW}{msg}{_Color.RESET}"
        return msg

    def warn(self, message: str) -> str:
        """Return a dimmed warning message."""
        if self.use_color:
            return f"{_Color.YELLOW}{message}{_Color.RESET}"
        return message

    def dim(self, message: str) -> str:
        """Return a dimmed informational message."""
        if self.use_color:
            return f"{_Color.DIM}{message}{_Color.RESET}"
        return message

    def summary(self, text: str) -> str:
        """Return the session summary (already formatted)."""
        return text


# ── Internal helper ─────────────────────────────────────────────

def _fmt_ts_now() -> str:
    from datetime import datetime
    return datetime.now().strftime("%H:%M:%S")
