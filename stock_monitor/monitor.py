"""AsyncStockMonitor — fully async orchestrator for real-time stock monitoring.

Architecture
------------
Each polling cycle fans out across all symbols concurrently using
``asyncio.Task``.  A semaphore caps in-flight HTTP requests so we don't
overwhelm the network stack (or trigger rate-limits) when monitoring
100+ symbols.

Per-symbol failover is sequential — sources are tried in priority order.
This preserves the original behaviour where Sina is preferred, then
EastMoney, then Yahoo.  Retry with exponential backoff lives inside each
source and uses ``asyncio.sleep`` so the event loop stays free.

Graceful shutdown: SIGINT / SIGTERM sets an ``asyncio.Event``; the main
loop checks this event at every yield point and cancels all outstanding
tasks on exit.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import sys
import time
from typing import Any

import httpx

from stock_monitor.alerts import AlertManager
from stock_monitor.config import StockMonitorConfig
from stock_monitor.display import Display
from stock_monitor.exporters.base import BaseExporter
from stock_monitor.notifiers.telegram import TelegramNotifier
from stock_monitor.sources.base import BaseSource
from stock_monitor.tracker import SessionStats

logger = logging.getLogger("stock_monitor.monitor")


class AsyncStockMonitor:
    """Real-time multi-stock async quote monitor with alerting and export.

    Usage::

        config = StockMonitorConfig(symbols=["NVDA", "AAPL"])
        monitor = AsyncStockMonitor(config)
        await monitor.run()
    """

    def __init__(self, config: StockMonitorConfig) -> None:
        self.config = config
        self.display = Display(use_color=config.use_color)

        # Internal state
        self._sources: list[BaseSource] = []
        self._exporters: list[BaseExporter] = []
        self._alert_mgr = AlertManager(config.alerts)
        self._telegram: TelegramNotifier | None = None
        self._stats = SessionStats()
        self._last_quotes: dict[str, dict[str, Any]] = {}

        # Async primitives
        self._shutdown_event = asyncio.Event()
        self._client: httpx.AsyncClient | None = None
        self._fetch_sem: asyncio.Semaphore | None = None  # limits concurrent fetches
        self._active_tasks: set[asyncio.Task[Any]] = set()

        # Track consecutive all-source failures for global backoff
        self._consecutive_failures = 0

    # ── Public API ────────────────────────────────────────────────────

    async def run(self) -> None:
        """Enter the async monitoring loop. Blocks until interrupted.

        Creates the shared ``httpx.AsyncClient``, wires up sources and
        exporters, then runs the main polling loop.  Handles graceful
        shutdown on SIGINT / SIGTERM.
        """
        self._setup_signal_handlers()

        timeout = httpx.Timeout(self.config.http_timeout)
        limits = httpx.Limits(
            max_connections=self.config.max_concurrency,
            max_keepalive_connections=self.config.max_keepalive,
        )

        async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
            self._client = client
            self._fetch_sem = asyncio.Semaphore(self.config.max_concurrency)
            self._setup_sources(client)
            self._setup_exporters()
            self._setup_telegram(client)

            logger.info("Monitor started: %s", ", ".join(self.config.symbols))

            try:
                await self._main_loop()
            except asyncio.CancelledError:
                logger.info("Monitor task cancelled — shutting down")
            finally:
                await self._teardown()

    # ── Setup / Teardown ──────────────────────────────────────────────

    def _setup_sources(self, client: httpx.AsyncClient) -> None:
        from stock_monitor.sources import get_source_chain
        self._sources = get_source_chain(self.config.source_order, client)

    def _setup_exporters(self) -> None:
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

        # Banner + header
        print(self.display.banner(
            self.config.symbols, self.config.interval, self.config.csv_path,
            self.config.source_order,
        ))
        print(self.display.header())

    def _setup_telegram(self, client: httpx.AsyncClient) -> None:
        if self.config.telegram:
            self._telegram = TelegramNotifier(
                client,
                bot_token=self.config.telegram.bot_token,
                chat_id=self.config.telegram.chat_id,
                cooldown_seconds=self.config.telegram.cooldown_seconds,
            )
            logger.info("Telegram notifications enabled")

    async def _teardown(self) -> None:
        """Cancel outstanding tasks, close exporters, print summary."""
        # Cancel all active fetch tasks
        for task in self._active_tasks:
            task.cancel()
        if self._active_tasks:
            await asyncio.gather(*self._active_tasks, return_exceptions=True)
        self._active_tasks.clear()

        # Close exporters (sync — fast file I/O)
        for exp in self._exporters:
            try:
                exp.close()
            except Exception as exc:
                logger.warning("Error closing exporter %s: %s",
                               type(exp).__name__, exc)
        print(self._stats.summary())
        logger.info("Monitor stopped. Runtime: %.0fs", self._stats.elapsed)

    def _setup_signal_handlers(self) -> None:
        """Register SIGINT / SIGTERM handlers using asyncio event-loop signals."""
        loop = asyncio.get_running_loop()

        def _on_signal() -> None:
            logger.debug("Shutdown signal received")
            self._shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _on_signal)
            except NotImplementedError:
                # Windows ProactorEventLoop doesn't support add_signal_handler
                # for SIGTERM; SIGINT is handled via KeyboardInterrupt in run().
                pass

    # ── Main Loop ─────────────────────────────────────────────────────

    async def _main_loop(self) -> None:
        """Core async polling loop.

        Each cycle fans out to all symbols concurrently, bounded by
        ``_fetch_sem``.  Between cycles we sleep for the remainder of
        the interval, but the sleep is cancellable via the shutdown event.
        """
        interval = self.config.interval

        while not self._shutdown_event.is_set():
            cycle_start = time.monotonic()
            any_success = False

            # ── Fan-out: fetch all symbols concurrently ──────────────
            coros = [self._fetch_one_symbol(sym) for sym in self.config.symbols]
            # Use asyncio.gather to run all concurrently; a single failing
            # symbol doesn't cancel the rest.
            results = await asyncio.gather(*coros, return_exceptions=True)

            for symbol, result in zip(self.config.symbols, results):
                if isinstance(result, Exception):
                    logger.error("%s: fetch task raised %s", symbol, result)
                    self._stats.record_error()
                    continue
                if result is not None:
                    any_success = True
                    self._last_quotes[symbol] = result
                    self._stats.record_fetch(symbol, result)
                    self._process_quote(symbol, result)
                else:
                    self._stats.record_error()

            # ── Global backoff when all sources are down ─────────────
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
                print(self.display.warn(
                    f"  [warn] All sources down — retrying in {backoff:.1f}s "
                    f"(fail #{self._consecutive_failures})"
                ), file=sys.stderr, flush=True)
                await self._cancellable_sleep(backoff)
                continue

            # ── Per-minute stats ────────────────────────────────────
            now = time.time()
            if now - self._stats.last_stats_time >= self.config.stats_interval:
                self._print_minute_stats()

            # ── Sleep for remainder of interval (cancellable) ───────
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                await self._cancellable_sleep(sleep_time)

    # ── Per-symbol fetch (with semaphore-bound concurrency) ──────────

    async def _fetch_one_symbol(self, symbol: str) -> dict[str, Any] | None:
        """Try all sources in priority order for one symbol.

        The semaphore ensures we never exceed ``max_concurrency``
        simultaneous HTTP requests across *all* symbols.
        """
        # Ensure the semaphore is set (it always is during normal operation)
        sem = self._fetch_sem
        if sem is None:
            return None

        async with sem:
            for source in self._sources:
                try:
                    quote = await source.fetch(symbol)
                    if quote is not None and quote.get("price") is not None:
                        logger.debug("%s: got price from %s", symbol, source.name)
                        return quote
                except Exception as exc:
                    logger.warning("%s: source %s raised %s",
                                   symbol, source.name, exc)
        return None

    # ── Quote processing ──────────────────────────────────────────────

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

            # Fire-and-forget Telegram notification (don't block the tick)
            if self._telegram and self._telegram.enabled:
                task = asyncio.create_task(
                    self._telegram.send_alert(
                        symbol=cond.symbol,
                        field=cond.field,
                        operator=cond.operator,
                        threshold=cond.threshold,
                        current_value=quote.get(cond.field, 0),
                        market=quote.get("market", "us"),
                    )
                )
                self._active_tasks.add(task)
                task.add_done_callback(self._active_tasks.discard)

        # Write exporters (sync — microseconds)
        for exp in self._exporters:
            try:
                exp.write(symbol, quote)
            except Exception as exc:
                logger.error("Exporter %s write error: %s",
                             type(exp).__name__, exc)

    # ── Stats printing ────────────────────────────────────────────────

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

    # ── Helpers ───────────────────────────────────────────────────────

    async def _cancellable_sleep(self, seconds: float) -> None:
        """Sleep for *seconds*, waking early if shutdown is signaled."""
        try:
            await asyncio.wait_for(
                self._shutdown_event.wait(), timeout=seconds,
            )
        except asyncio.TimeoutError:
            pass  # Normal — sleep interval elapsed
