"""Notifier package — alert dispatch to external channels (Telegram, etc.)."""

from stock_monitor.notifiers.telegram import TelegramNotifier

__all__ = ["TelegramNotifier"]
