"""Command-line interface — argument parsing and async entry point."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from stock_monitor import __version__
from stock_monitor.config import (
    StockMonitorConfig,
    load_config_from_args,
    load_config_from_yaml,
    merge_configs,
)
from stock_monitor.logging_setup import setup_logging
from stock_monitor.monitor import AsyncStockMonitor


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the ArgumentParser with all CLI options."""
    p = argparse.ArgumentParser(
        prog="stock-monitor",
        description=(
            "Real-time async stock quote monitor (US + A-share) — polls Sina, "
            "EastMoney, and Yahoo Finance with optional price alerts and "
            "Telegram notifications."
        ),
        epilog=(
            "Examples:\n"
            "  python -m stock_monitor -s NVDA\n"
            "  python -m stock_monitor -s NVDA,AAPL,TSLA -i 1.5\n"
            "  python -m stock_monitor -s NVDA,600519.SH,000333.SZ\n"
            "  python -m stock_monitor -c config.yaml\n"
            "  python -m stock_monitor -s NVDA -a NVDA:>:230 --telegram\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "-s", "--symbols", type=str, default=None,
        help="Stock symbol(s), comma-separated (e.g. NVDA,AAPL,TSLA)",
    )
    p.add_argument(
        "-i", "--interval", type=float, default=None,
        help="Polling interval in seconds (default: 2.0)",
    )
    p.add_argument(
        "--csv", type=str, default=None,
        help="CSV output path (default: stock_ticks.csv)",
    )
    p.add_argument(
        "--json", type=str, default=None,
        help="JSON Lines output path (disabled by default)",
    )
    p.add_argument(
        "--no-color", action="store_true",
        help="Disable ANSI color output",
    )
    p.add_argument(
        "-c", "--config", type=str, default=None,
        help="Path to YAML config file (auto-detects ./config.yaml)",
    )
    p.add_argument(
        "-a", "--alert", action="append", dest="alert", default=None,
        metavar="SPEC",
        help=(
            "Price alert: SYM:OP:THR or SYM:FLD:OP:THR "
            "(e.g. -a NVDA:>:230 -a NVDA:change_pct:<:-5)"
        ),
    )
    p.add_argument(
        "--log-level", type=str, default=None,
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console log level (default: INFO)",
    )
    p.add_argument(
        "--log-file", type=str, default=None,
        help="Path to log file (rotating, DEBUG level)",
    )
    p.add_argument(
        "--telegram", action="store_true", default=None,
        help="Enable Telegram alert notifications (credentials in config.yaml)",
    )
    p.add_argument(
        "--test-telegram", action="store_true", default=False,
        help="Send a test message via Telegram Bot, then exit (requires --telegram)",
    )
    p.add_argument(
        "--max-concurrency", type=int, default=None, dest="max_concurrency",
        help="Max concurrent HTTP requests (default: 20)",
    )
    p.add_argument(
        "--version", action="version",
        version=f"stock-monitor v{__version__}",
        help="Show version and exit",
    )
    return p


def main(argv: list[str] | None = None) -> None:
    """Entry point: parse args, load config, configure logging, run monitor."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    # Try colorama for older Windows consoles
    if not args.no_color:
        try:
            import colorama
            colorama.just_fix_windows_console()
        except ImportError:
            pass

    # ── Logging (set up early) ──────────────────────────────────────
    setup_logging(
        level=args.log_level or "INFO",
        log_file=args.log_file or "",
    )

    # ── Config loading (layered: defaults → YAML → CLI) ─────────────
    yaml_path = args.config
    if yaml_path is None:
        default_yaml = Path("config.yaml")
        if default_yaml.exists():
            yaml_path = str(default_yaml)

    yaml_config = None
    if yaml_path:
        yaml_config = load_config_from_yaml(yaml_path)

    cli_config = load_config_from_args(args)
    config = merge_configs(yaml_config, cli_config) if yaml_config is not None else cli_config

    # ── Override with raw CLI args that don't fit dataclass flow ────
    if args.symbols is not None:
        config.symbols = [s.strip().upper()
                          for s in args.symbols.split(",") if s.strip()]
    if args.csv is not None:
        config.csv_path = args.csv
    if args.json is not None:
        config.json_path = args.json
    if args.interval is not None:
        config.interval = args.interval
    if args.no_color:
        config.use_color = False
    if args.log_level is not None:
        config.log_level = args.log_level
    if args.log_file is not None:
        config.log_file = args.log_file
    if args.telegram is not None:
        config.telegram.enabled = args.telegram
    if args.max_concurrency is not None:
        config.max_concurrency = args.max_concurrency

    # ── Logging (re-apply with final merged config) ─────────────────
    setup_logging(level=config.log_level, log_file=config.log_file)

    # ── Test Telegram ───────────────────────────────────────────────
    if args.test_telegram:
        asyncio.run(_run_telegram_test_async(config))
        return

    # ── Run async monitor ───────────────────────────────────────────
    monitor = AsyncStockMonitor(config)
    try:
        asyncio.run(monitor.run())
    except KeyboardInterrupt:
        pass  # Graceful — handled internally by shutdown event


async def _run_telegram_test_async(config: StockMonitorConfig) -> None:
    """Send a test message via Telegram Bot and print the result."""
    from stock_monitor.notifiers.telegram import TelegramNotifier

    tg_config = config.telegram
    if not tg_config.bot_token or not tg_config.chat_id:
        print("[FAIL] Telegram bot_token or chat_id not configured.")
        print("       Please fill them in config.yaml.")
        return

    import httpx

    async with httpx.AsyncClient() as client:
        tg = TelegramNotifier(
            client,
            bot_token=tg_config.bot_token,
            chat_id=tg_config.chat_id,
            cooldown_seconds=0,
        )
        print(f"Bot Token: {tg_config.bot_token[:10]}...{tg_config.bot_token[-4:]}")
        print(f"Chat ID  : {tg_config.chat_id}")
        print("Sending test message...")
        ok = await tg.send_test()
        if ok:
            print("[OK] Test message sent! Check your Telegram.")
        else:
            print("[FAIL] Test message failed. Check Bot Token and Chat ID.")
            print("       Common issues:")
            print("       1. Did you copy the Bot Token correctly from @BotFather?")
            print("       2. Have you sent /start to your Bot on Telegram?")
            print("       3. Is the Chat ID correct?")


if __name__ == "__main__":
    main()
