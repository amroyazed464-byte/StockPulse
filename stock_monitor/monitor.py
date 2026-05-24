"""AsyncStockMonitor — event-driven async orchestrator.

Architecture
------------
Data flows through the EventBus::

    HTTP Sources ──→ Monitor (dedup) ──→ EventBus.publish(PriceUpdateEvent)
                                              │
              ┌────────────────────────────────┼────────────────────────────┐
              ▼                                ▼                            ▼
       Display.print()              AlertManager.check()            Exporters.write()
              ▲                        │
              │                        ▼
              │               EventBus.publish(AlertTriggeredEvent)
              │                        │
              └────────────────────────┼────────────────────────────┐
                                       ▼                            ▼
                                Display.print()          TelegramNotifier.send()

All components are wired at startup via ``component.wire(bus)``.  No
component holds a direct reference to any other — the bus is the single
point of coupling.
"""

from __future__ import annotations

import asyncio
import logging
import signal
import time
from typing import Any

import httpx

from stock_monitor.alerts import AlertManager
from stock_monitor.config import StockMonitorConfig
from stock_monitor.display import Display
from stock_monitor.events import (
    AlertTriggeredEvent,
    EventBus,
    FetchCompletedEvent,
    MarketStatusEvent,
    PriceUpdateEvent,
    ShutdownEvent,
    SourceFailEvent,
    StatsTickEvent,
)
from stock_monitor.exporters.base import BaseExporter
from stock_monitor.notifiers.telegram import TelegramNotifier
from stock_monitor.plugins import (
    PluginRegistry,
    StockPulsePlugin,
    discover_plugins,
    teardown_registry,
    wire_registry,
)
from stock_monitor.plugins.exporters import bridge_builtin_exporters
from stock_monitor.plugins.notifiers import bridge_builtin_notifiers
from stock_monitor.plugins.sources import bridge_builtin_sources
from stock_monitor.plugins.strategies import Signal
from stock_monitor.sources.base import BaseSource
from stock_monitor.tracker import SessionStats
from stock_monitor.volume_spike import VolumeSpikeDetector

logger = logging.getLogger("stock_monitor.monitor")


class AsyncStockMonitor:
    """Event-driven async stock quote monitor.

    Usage::

        config = StockMonitorConfig(symbols=["NVDA", "AAPL"])
        monitor = AsyncStockMonitor(config)
        await monitor.run()
    """

    def __init__(self, config: StockMonitorConfig) -> None:
        self.config = config
        self.display = Display(use_color=config.use_color)
        self._bus = EventBus()

        # Components — created now, wired in _setup_wiring()
        self._registry = PluginRegistry()
        self._sources: list[BaseSource] = []
        self._exporters: list[BaseExporter] = []
        self._alert_mgr = AlertManager(config.alerts)
        self._telegram: TelegramNotifier | None = None
        self._stats = SessionStats()
        self._volume_spike = VolumeSpikeDetector(
            window_size=config.volume_spike_window,
            spike_ratio=config.volume_spike_ratio,
        )
        self._plugins: list[StockPulsePlugin] = []

        # Runtime state
        self._last_quotes: dict[str, dict[str, Any]] = {}
        self._consecutive_failures = 0
        self._was_down = False

        # Async primitives
        self._shutdown_event = asyncio.Event()
        self._client: httpx.AsyncClient | None = None
        self._fetch_sem: asyncio.Semaphore | None = None

    # ── Public API ────────────────────────────────────────────────────

    async def run(self) -> None:
        """Enter the event-driven async monitoring loop."""
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
            self._setup_wiring()

            # Startup banner (not event-driven — one-shot administrative)
            print(self.display.banner(
                self.config.symbols, self.config.interval,
                self.config.csv_path, self.config.source_order,
            ))
            print(self.display.header())

            logger.info("Monitor started: %s", ", ".join(self.config.symbols))

            try:
                await self._main_loop()
            except asyncio.CancelledError:
                logger.info("Monitor task cancelled — shutting down")
            finally:
                await self._teardown()

    # ── Setup ──────────────────────────────────────────────────────────

    def _setup_sources(self, client: httpx.AsyncClient) -> None:
        from stock_monitor.sources import get_source_chain
        self._sources = get_source_chain(self.config.source_order, client)
        bridge_builtin_sources(self._sources, self._registry)

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

        bridge_builtin_exporters(self._exporters, self._registry)

    def _setup_telegram(self, client: httpx.AsyncClient) -> None:
        if self.config.telegram:
            self._telegram = TelegramNotifier(
                client,
                bot_token=self.config.telegram.bot_token,
                chat_id=self.config.telegram.chat_id,
                cooldown_seconds=self.config.telegram.cooldown_seconds,
            )
            bridge_builtin_notifiers([self._telegram], self._registry)
            logger.info("Telegram notifications enabled")

    def _setup_wiring(self) -> None:
        """Wire every component to the EventBus via the PluginRegistry.

        Built-in components are bridged into the registry during
        construction.  External plugins are auto-discovered from
        ``plugins/`` and any extra paths in config.  The registry
        then wires all enabled plugins in one pass.
        """
        bus = self._bus

        # ── Core components (not plugin-managed) ────────────────
        self.display.wire(bus)
        self._alert_mgr.wire(bus)
        self._stats.wire(bus)
        self._volume_spike.wire(bus)

        # Legacy direct wiring for built-in exporters & notifiers
        # (these are also bridged in the registry, but their wire()
        # must be called directly since the adapter delegates to them)
        for exp in self._exporters:
            exp.wire(bus)
        if self._telegram and self._telegram.enabled:
            self._telegram.wire(bus)

        # ── External plugins ────────────────────────────────────
        self._plugins = discover_plugins(
            registry=self._registry,
            disabled_names=self.config.disabled_plugins,
            extra_paths=self.config.plugin_paths,
        )

        # ── Wire all enabled plugins in the registry ────────────
        wire_registry(self._registry, bus)

        # Auto-discovered plugins also need wiring (discover_plugins
        # registers them, wire_registry wires them, but the returned
        # list includes both bridged-builtins and discovered externals)
        # wire_registry already handles all registered plugins.

        logger.info(
            "EventBus wired: %d subscribers across %d event types\n"
            "  Registry: %s",
            bus.subscriber_count,
            len(bus.stats) or 0,
            self._registry.summary(),
        )

    def _setup_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()

        def _on_signal() -> None:
            logger.debug("Shutdown signal received")
            self._shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, _on_signal)
            except NotImplementedError:
                pass

    # ── Teardown ───────────────────────────────────────────────────────

    async def _teardown(self) -> None:
        """Publish shutdown event, teardown plugins, close exporters, print summary."""
        await self._bus.publish(ShutdownEvent(
            reason="user_interrupt",
            runtime_seconds=self._stats.elapsed,
        ))

        teardown_registry(self._registry)

        for exp in self._exporters:
            try:
                exp.close()
            except Exception as exc:
                logger.warning("Error closing exporter %s: %s",
                               type(exp).__name__, exc)

        print(self._stats.summary())
        logger.info(
            "Monitor stopped. Runtime: %.0fs | Events published: %s",
            self._stats.elapsed, self._bus.stats,
        )

    # ── Main Loop ─────────────────────────────────────────────────────

    async def _main_loop(self) -> None:
        """Core event-driven polling loop.

        Fetches all symbols concurrently, deduplicates, and publishes
        events for downstream consumers.
        """
        interval = self.config.interval

        while not self._shutdown_event.is_set():
            cycle_start = time.monotonic()
            any_success = False

            # ── Fan-out: fetch all symbols concurrently ──────────
            coros = [self._fetch_one_symbol(sym) for sym in self.config.symbols]
            results = await asyncio.gather(*coros, return_exceptions=True)

            for symbol, result in zip(self.config.symbols, results):
                if isinstance(result, Exception):
                    logger.error("%s: fetch task raised %s", symbol, result)
                    asyncio.create_task(
                        self._bus.publish(FetchCompletedEvent(
                            symbol=symbol, source="?", success=False,
                        ))
                    )
                    continue

                if result is not None:
                    any_success = True
                    self._last_quotes[symbol] = result
                    asyncio.create_task(
                        self._bus.publish(FetchCompletedEvent(
                            symbol=symbol,
                            source=result.get("source", "?"),
                            success=True,
                            quote=result,
                        ))
                    )
                    self._publish_if_changed(symbol, result)
                else:
                    asyncio.create_task(
                        self._bus.publish(FetchCompletedEvent(
                            symbol=symbol,
                            source="all_failed",
                            success=False,
                        ))
                    )
                    await self._bus.publish(SourceFailEvent(
                        symbol=symbol,
                        sources_attempted=[s.name for s in self._sources],
                    ))

            # ── Market status transition ─────────────────────────
            await self._handle_market_status(any_success)

            # ── Per-minute stats ─────────────────────────────────
            now = time.time()
            if now - self._stats.last_stats_time >= self.config.stats_interval:
                self._stats.last_stats_time = now
                await self._bus.publish(StatsTickEvent(
                    symbols=list(self.config.symbols),
                    last_quotes=dict(self._last_quotes),
                ))

            # ── Sleep for remainder of interval ──────────────────
            elapsed = time.monotonic() - cycle_start
            sleep_time = max(0, interval - elapsed)
            if sleep_time > 0:
                await self._cancellable_sleep(sleep_time)

    # ── Per-symbol fetch ──────────────────────────────────────────────

    async def _fetch_one_symbol(self, symbol: str) -> dict[str, Any] | None:
        """Try all sources in priority order for one symbol."""
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

    # ── Event publishing ──────────────────────────────────────────────

    def _publish_if_changed(self, symbol: str, quote: dict[str, Any]) -> None:
        """Deduplicate against last known state, then publish.

        Only publishes when price or volume actually changed — this
        prevents redundant events and keeps downstream consumers quiet.
        The actual ``bus.publish()`` is scheduled as a task so the
        fetch cycle is not blocked by slow subscribers.
        """
        tr = self._stats.get_tracker(symbol)
        price = quote["price"]
        vol = quote.get("volume", 0)

        if price == tr.last_price and vol == tr.last_vol:
            return  # Duplicate — suppress

        # Schedule publish as a concurrent task so slow handlers
        # (e.g., Telegram HTTP timeout) don't delay the next poll.
        asyncio.create_task(
            self._bus.publish(PriceUpdateEvent(symbol=symbol, quote=quote))
        )

    async def _handle_market_status(self, any_success: bool) -> None:
        """Publish MarketStatusEvent on state transitions."""
        if any_success:
            if self._was_down:
                await self._bus.publish(MarketStatusEvent(status="recovered"))
            self._consecutive_failures = 0
            self._was_down = False
        else:
            self._consecutive_failures += 1
            backoff = min(
                self.config.retry_base_delay
                * (2 ** (self._consecutive_failures - 1)),
                self.config.retry_max_delay,
            )
            self._was_down = True
            logger.warning(
                "All sources down (fail #%d) — backing off %.1fs",
                self._consecutive_failures, backoff,
            )
            await self._bus.publish(MarketStatusEvent(
                status="all_sources_down",
                consecutive_failures=self._consecutive_failures,
                backoff_seconds=backoff,
            ))
            await self._cancellable_sleep(backoff)

    # ── Helpers ───────────────────────────────────────────────────────

    async def _cancellable_sleep(self, seconds: float) -> None:
        """Sleep for *seconds*, waking early if shutdown is signaled."""
        try:
            await asyncio.wait_for(
                self._shutdown_event.wait(), timeout=seconds,
            )
        except asyncio.TimeoutError:
            pass
