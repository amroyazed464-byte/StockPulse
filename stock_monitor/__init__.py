"""Stock Monitor — real-time multi-stock quote monitoring with alerting.

Polls EastMoney, Sina Finance, and Yahoo Finance for US stock data,
with auto-failover, configurable price alerts, and CSV/JSON export.

Usage::

    from stock_monitor import StockMonitor, StockMonitorConfig

    config = StockMonitorConfig(symbols=["NVDA", "AAPL"], interval=2.0)
    monitor = StockMonitor(config)
    monitor.run()
"""

__version__ = "2.1.0"

from stock_monitor.alerts import AlertCondition, AlertManager
from stock_monitor.config import AlertSpec, StockMonitorConfig, merge_configs
from stock_monitor.monitor import StockMonitor

__all__ = [
    "StockMonitor",
    "StockMonitorConfig",
    "AlertSpec",
    "AlertCondition",
    "AlertManager",
    "merge_configs",
]
