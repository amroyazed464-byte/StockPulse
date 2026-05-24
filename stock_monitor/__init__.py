"""Stock Monitor — async real-time multi-stock quote monitoring with alerting.

Polls Sina Finance, EastMoney, and Yahoo Finance for stock data,
with auto-failover, configurable price alerts, and CSV/JSON export.

Fully async architecture using asyncio + httpx for high-concurrency
monitoring of 100+ symbols.

Usage::

    from stock_monitor import AsyncStockMonitor, StockMonitorConfig

    config = StockMonitorConfig(symbols=["NVDA", "AAPL"], interval=2.0)
    monitor = AsyncStockMonitor(config)
    asyncio.run(monitor.run())
"""

__version__ = "3.0.0"

from stock_monitor.alerts import AlertCondition, AlertManager
from stock_monitor.config import AlertSpec, StockMonitorConfig, merge_configs
from stock_monitor.monitor import AsyncStockMonitor

# Backward-compat alias
StockMonitor = AsyncStockMonitor

__all__ = [
    "AsyncStockMonitor",
    "StockMonitor",    # backward-compat alias
    "StockMonitorConfig",
    "AlertSpec",
    "AlertCondition",
    "AlertManager",
    "merge_configs",
]
