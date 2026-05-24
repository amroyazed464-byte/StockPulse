"""StockMonitor — main orchestrator for real-time stock quote monitoring."""

from __future__ import annotations

import logging
import signal
import sys
import time
from typing import Any

from stock_monitor.alerts import AlertManager
from stock_monitor.config import StockMonitorConfig
from stock_monitor.display import Display
from stock_monitor.exporters.base import BaseExporter
from stock_monitor.notifiers.telegram import TelegramNotifier
from stock_monitor.sources.base import BaseSource
from stock_monitor.tracker import SessionStats

logger = logging.getLogger("stock_monitor.monitor")


class StockMonitor:
    """Real-time multi-stock quote monitor with alerting and export.

    Usage::

        config = StockMonitorConfig(symbols=["NVDA", "AAPL"])
        monitor = StockMonitor(config)
        monitor.run()
    """

    # Minimum gap between outgoing HTTP requests to avoid rate-limit bans
    _MIN_REQUEST_GAP = 0.25  # seconds

    # ── Public API ──────────────────────────────────────────────

    def __init__(self, config: StockMonitorConfig) -> None:
        self.config = config
        self.display = Display(use_color=config.use_color)

        # State
        self._sources: list[BaseSource] = []
        self._exporters: list[BaseExporter] = []
        self._alert_mgr = AlertManager(config.alerts)
        self._telegram: TelegramNotifier | None = None
        self._stats = SessionStats()
        self._last_quotes: dict[str, dict[str, Any]] = {}
        self._running = False
        self._consecutive_failures = 0
        self._last_request_ts = 0.0  # for _MIN_REQUEST_GAP throttle

    def run(self) -> None:
        """Enter the main monitoring loop. Blocks until interrupted.

        Handles SIGINT / SIGTERM for graceful shutdown, printing a
        session summary on exit.
        """
        self._setup()
        self._register_signal_handlers()
        self._running = True
        logger.info("Monitor started: %s", ", ".join(self.config.symbols))

        try:
            self._main_loop()
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt received — shutting down")
        finally:
            self._teardown()

    # ── Setup / Teardown ────────────────────────────────────────

    def _setup(self) -> None:
        """Initialize sources and exporters from config."""
        from stock_monitor.sources import get_source_chain

        self._sources = get_source_chain(self.config.source_order)

        from stock_monitor.exporters.csv_exporter import CsvExporter

        if self.config.csv_path:
            csv_exp = CsvExporter(self.config.csv_path)
            csv_exp.open()
            self._exporters.append(csv_exp)

        if self.config.json_path:
            from stock_monitor.exporters.json_exporter import JsonExporter

            json_exp = JsonExporter(self.config.json_path)
            json_exp.open()
            self._exporters.append(json_exp)

        # Telegram notifier
        if self.config.telegram:
            self._telegram = TelegramNotifier(
                bot_token=self.config.telegram.bot_token,
                chat_id=self.config.telegram.chat_id,
                cooldown_seconds=self.config.telegram.cooldown_seconds,
            )
            logger.info("Telegram notifications enabled")

        # Print banner + header
        print(self.display.banner(
            self.config.symbols, self.config.interval, self.config.csv_path,
            self.config.source_order,
        ))
        print(self.display.header())

    def _teardown(self) -> None:
        """Close exporters and print session summary."""
        for exp in self._exporters:
            try:
                exp.close()
            except Exception as exc:
                logger.warning("Error closing exporter %s: %s",
                               type(exp).__name__, exc)
        print(self._stats.summary())
        logger.info("Monitor stopped. Runtime: %.0fs", self._stats.elapsed)

    def _register_signal_handlers(self) -> None:
        """Register SIGINT/SIGTERM for graceful shutdown on Windows + Unix."""

        def _handler(signum: int, frame: Any) -> None:  # noqa: ARG001
            logger.debug("Signal %d received", signum)
            self._running = False

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, _handler)
            except (ValueError, AttributeError):
                # SIGTERM handler not supported in some environments
                pass

    # ── Main Loop ───────────────────────────────────────────────

    def _main_loop(self) -> None:
        """Core polling loop: for each symbol try sources in order."""
        interval = self.config.interval

        while self._running:
            cycle_start = time.time()
            any_success = False

            for symbol in self.config.symbols:
                quote = self._fetch_symbol(symbol)

                if quote and quote.get("price") is not None:
                    any_success = True
                    self._last_quotes[symbol] = quote
                    self._stats.record_fetch(symbol, quote)
                    self._process_quote(symbol, quote)
                else:
                    self._stats.record_error()

            # All-sources-down backoff
            if any_success:
                self._consecutive_failures = 0
            else:
                self._consecutive_failures += 1
                backoff = min(
                    self.config.retry_base_delay
                    * (2 ** (self._consecutive_failures - 1)),
                    self.config.retry_max_delay,
                )
                logger.warning(
                    "All sources down (fail #%d) — backing off %.1fs",
                    self._consecutive_failures, backoff,
                )
                msg = self.display.warn(
                    f"  [warn] All sources down — retrying in {backoff:.1f}s "
                    f"(fail #{self._consecutive_failures})"
                )
                print(msg, file=sys.stderr, flush=True)
                time.sleep(backoff)
                continue

            # Per-minute stats
            now = time.time()
            if now - self._stats.last_stats_time >= self.config.stats_interval:
                self._print_minute_stats()

            # Sleep for remainder of interval
            elapsed = time.time() - cycle_start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0 and self._running:
                time.sleep(sleep_time)

    def _fetch_symbol(self, symbol: str) -> dict[str, Any] | None:
        """Try all sources in priority order for one symbol.

        Enforces a minimum gap between outgoing HTTP requests
        (``_MIN_REQUEST_GAP``) to avoid triggering rate-limit bans
        on shared API endpoints.
        """
        for source in self._sources:
            # ── Rate-limit guard ────────────────────────────────
            gap = time.time() - self._last_request_ts
            if gap < self._MIN_REQUEST_GAP:
                time.sleep(self._MIN_REQUEST_GAP - gap)

            try:
                quote = source.fetch(symbol)
                self._last_request_ts = time.time()
                if quote and quote.get("price") is not None:
                    logger.debug("%s: got price from %s", symbol, source.name)
                    return quote
            except Exception as exc:
                self._last_request_ts = time.time()
                logger.warning("%s: source %s raised %s",
                               symbol, source.name, exc)
        return None

    def _process_quote(self, symbol: str, quote: dict[str, Any]) -> None:
        """Check dedup, fire alerts, write exporters for a successful quote."""
        tr = self._stats.get_tracker(symbol)
        price = quote["price"]
        vol = quote.get("volume", 0)

        # Dedup: only print & export when price or volume changes
        if price == tr.last_price and vol == tr.last_vol:
            return

        self._stats.record_tick(symbol, quote)
        print(self.display.price_line(symbol, quote), flush=True)

        # Check alerts
        triggered = self._alert_mgr.check(symbol, quote)
        for cond in triggered:
            print(self.display.alert(
                cond.symbol, cond.field, cond.operator,
                cond.threshold, quote.get(cond.field, 0),
                market=quote.get("market", "us"),
            ), flush=True)
            # Telegram notification
            if self._telegram and self._telegram.enabled:
                self._telegram.send_alert(
                    symbol=cond.symbol,
                    field=cond.field,
                    operator=cond.operator,
                    threshold=cond.threshold,
                    current_value=quote.get(cond.field, 0),
                    market=quote.get("market", "us"),
                )

        # Write exporters
        for exp in self._exporters:
            try:
                exp.write(symbol, quote)
            except Exception as exc:
                logger.error("Exporter %s write error: %s",
                             type(exp).__name__, exc)

    def _print_minute_stats(self) -> None:
        """Print per-minute volume-delta statistics."""
        self._stats.last_stats_time = time.time()
        print()
        print(self.display.stats_header())
        for symbol in self.config.symbols:
            quote = self._last_quotes.get(symbol)
            if not quote:
                continue
            tr = self._stats.get_tracker(symbol)
            current_vol = int(quote.get("volume", 0))
            cycle_delta = current_vol - tr.vol_at_stats_start
            tr.vol_at_stats_start = current_vol
            print(self.display.stats_line(symbol, quote, cycle_delta),
                  flush=True)
        print(self.display.stats_footer())
