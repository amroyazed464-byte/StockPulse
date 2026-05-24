"""Stock Monitor — event-driven async multi-stock quote monitoring.

Polls Sina Finance, EastMoney, and Yahoo Finance for stock data.
Fully async architecture with an internal EventBus for decoupled
producer/consumer communication.

Usage::

    from stock_monitor import AsyncStockMonitor, StockMonitorConfig

    config = StockMonitorConfig(symbols=["NVDA", "AAPL"], interval=2.0)
    monitor = AsyncStockMonitor(config)
    asyncio.run(monitor.run())
"""

__version__ = "3.2.0"

from stock_monitor.alerts import AlertCondition, AlertManager
from stock_monitor.config import AlertSpec, StockMonitorConfig, merge_configs
from stock_monitor.events import (
    AlertTriggeredEvent,
    EventBus,
    FetchCompletedEvent,
    MarketStatusEvent,
    PriceUpdateEvent,
    ShutdownEvent,
    SourceFailEvent,
    StatsTickEvent,
    VolumeSpikeEvent,
    event_discriminator,
    get_event_type,
)
from stock_monitor.monitor import AsyncStockMonitor
from stock_monitor.plugins import (
    PluginMeta,
    PluginRegistry,
    StockPulsePlugin,
    discover_plugins,
    teardown_plugins,
    teardown_registry,
    wire_plugins,
    wire_registry,
)
from stock_monitor.plugins.exporters import ExporterPlugin, bridge_builtin_exporters
from stock_monitor.plugins.notifiers import NotifierPlugin, bridge_builtin_notifiers
from stock_monitor.plugins.sources import SourcePlugin, bridge_builtin_sources
from stock_monitor.plugins.strategies import Signal, SignalKind, StrategyPlugin

# Backward-compat alias
StockMonitor = AsyncStockMonitor

__all__ = [
    # Core
    "AsyncStockMonitor",
    "StockMonitor",
    "StockMonitorConfig",
    "EventBus",
    # Config
    "AlertSpec",
    "AlertCondition",
    "AlertManager",
    "merge_configs",
    # Events
    "PriceUpdateEvent",
    "AlertTriggeredEvent",
    "SourceFailEvent",
    "MarketStatusEvent",
    "VolumeSpikeEvent",
    "ShutdownEvent",
    "StatsTickEvent",
    "FetchCompletedEvent",
    "get_event_type",
    "event_discriminator",
    # Plugin system
    "PluginMeta",
    "PluginRegistry",
    "StockPulsePlugin",
    "discover_plugins",
    "teardown_plugins",
    "teardown_registry",
    "wire_plugins",
    "wire_registry",
    # Plugin categories
    "SourcePlugin",
    "bridge_builtin_sources",
    "ExporterPlugin",
    "bridge_builtin_exporters",
    "NotifierPlugin",
    "bridge_builtin_notifiers",
    "StrategyPlugin",
    "Signal",
    "SignalKind",
]
