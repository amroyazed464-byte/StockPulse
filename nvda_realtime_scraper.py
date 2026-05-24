#!/usr/bin/env python
"""Stock Monitor — legacy entry-point shim.

This file is kept for backward compatibility.
Prefer ``python -m stock_monitor`` for new usage.

Usage:
  python nvda_realtime_scraper.py -s NVDA
  python nvda_realtime_scraper.py -s NVDA,AAPL -i 1.5 -c config.yaml
"""

from stock_monitor.cli import main

if __name__ == "__main__":
    main()
