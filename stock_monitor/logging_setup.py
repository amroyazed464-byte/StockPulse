"""Logging configuration for the stock_monitor package.

Provides console output (INFO+) and optional rotating file output (DEBUG).
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(
    level: str = "INFO",
    log_file: str = "",
    *,
    console_fmt: str | None = None,
    file_fmt: str | None = None,
) -> logging.Logger:
    """Configure the root ``stock_monitor`` logger.

    Args:
        level: Log level for the console handler (DEBUG/INFO/WARNING/ERROR).
        log_file: Path to a log file. If empty, no file handler is attached.
        console_fmt: Override console log format.
        file_fmt: Override file log format.

    Returns:
        The package root logger (``stock_monitor``).
    """
    root = logging.getLogger("stock_monitor")
    root.setLevel(logging.DEBUG)  # capture everything; handlers filter
    root.handlers.clear()

    if console_fmt is None:
        console_fmt = "%(asctime)s [%(levelname)-7s] %(name)s | %(message)s"
    if file_fmt is None:
        file_fmt = "%(asctime)s [%(levelname)-7s] %(name)s:%(lineno)d | %(message)s"

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(_level_value(level))
    console.setFormatter(logging.Formatter(console_fmt, datefmt="%H:%M:%S"))
    root.addHandler(console)

    # File handler (rotating, 1 MB × 3 backups)
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(
            path, maxBytes=1_048_576, backupCount=3, encoding="utf-8"
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(file_fmt, datefmt="%Y-%m-%d %H:%M:%S"))
        root.addHandler(fh)

    # Quiet noisy third-party loggers — clear handlers AND raise level
    for noisy in ("scrapling", "urllib3", "yfinance"):
        lg = logging.getLogger(noisy)
        lg.setLevel(logging.WARNING)
        lg.handlers.clear()
        lg.propagate = False  # prevent bubbling up to root

    return root


def _level_value(name: str) -> int:
    """Convert string level name to logging constant."""
    return getattr(logging, name.upper(), logging.INFO)
