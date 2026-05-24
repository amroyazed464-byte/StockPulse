"""Telegram Bot notifier for sending real-time price alerts."""

from __future__ import annotations

import json
import logging
import time
import urllib.request
from datetime import datetime

from stock_monitor.utils import market_currency

logger = logging.getLogger("stock_monitor.notifiers.telegram")

TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"

# ── Retry constants ──────────────────────────────────────────────
_SEND_MAX_RETRIES = 3
_SEND_BASE_DELAY = 1.0  # seconds


class TelegramNotifier:
    """Sends price-alert messages via a Telegram Bot.

    Uses the Telegram Bot API directly (stdlib urllib — no extra dependency).
    Messages are rate-limited per symbol+field to avoid flooding the chat.

    Args:
        bot_token: Telegram Bot token from @BotFather.
        chat_id: Target chat ID (user, group, or channel).
        cooldown_seconds: Minimum seconds between messages per key.

    Usage::

        tg = TelegramNotifier(bot_token="...", chat_id="123456")
        tg.send_alert("NVDA", "price", ">", 230.0, 235.67)
    """

    def __init__(
        self,
        bot_token: str,
        chat_id: str,
        cooldown_seconds: int = 60,
    ) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.cooldown_seconds = cooldown_seconds
        self._last_sent: dict[str, float] = {}
        self._available = bool(bot_token and chat_id)

        if self._available:
            logger.info("Telegram notifier configured (cooldown=%ds)", cooldown_seconds)
        else:
            logger.warning("Telegram bot_token or chat_id missing — disabled")

    # ── Public API ────────────────────────────────────────────────

    def send_alert(
        self,
        symbol: str,
        field: str,
        operator: str,
        threshold: float,
        current_value: float,
        market: str = "us",
    ) -> bool:
        """Send a price alert to Telegram, respecting cooldown.

        Returns True if the message was sent, False if suppressed.
        """
        if not self._available:
            return False

        # Cooldown check per symbol+field+operator+threshold
        key = f"{symbol}:{field}:{operator}:{threshold}"
        now = time.time()
        last = self._last_sent.get(key, 0)
        if now - last < self.cooldown_seconds:
            logger.debug("Telegram cooldown — suppressed %s", key)
            return False

        currency = market_currency(market)
        text = self._build_alert_message(
            symbol, field, operator, threshold, current_value, currency,
        )

        ok = self._send_with_retry(text)
        if ok:
            self._last_sent[key] = now
            logger.info(
                "Telegram alert sent: %s %s %s %s",
                symbol, field, operator, threshold,
            )
        return ok

    def send_test(self) -> bool:
        """Send a one-shot test message to verify bot connectivity.

        Returns True if the test message was delivered successfully.
        """
        if not self._available:
            logger.warning("Cannot send test — Telegram credentials not configured")
            return False

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        text = (
            "✅ *StockPulse — 测试成功*\n\n"
            f"您的 Telegram Bot 已正确配置并成功连接。\n\n"
            f"• Bot Token: `{self._mask_token()}`\n"
            f"• Chat ID: `{self.chat_id}`\n"
            f"• 时间: `{ts}`\n\n"
            "ℹ️ 当股票价格触发告警阈值时，您将在此收到实时通知。"
        )
        return self._send_with_retry(text)

    # ── Message builders ──────────────────────────────────────────

    def _build_alert_message(
        self,
        symbol: str,
        field: str,
        operator: str,
        threshold: float,
        current_value: float,
        currency: str,
    ) -> str:
        """Format a rich Markdown alert message for Telegram."""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if field == "price":
            val_str = f"{currency}{current_value:.2f}"
            thr_str = f"{currency}{threshold:.2f}"
            field_label = "价格"
            field_emoji = "\U0001f4b0"  # 💰
        elif field == "change_pct":
            val_str = f"{current_value:+.2f}%"
            thr_str = f"{threshold:+.2f}%"
            field_label = "涨跌幅"
            field_emoji = "\U0001f4c8"  # 📈
        elif field == "volume":
            val_str = f"{current_value:,.0f}"
            thr_str = f"{threshold:,.0f}"
            field_label = "成交量"
            field_emoji = "\U0001f4ca"  # 📊
        else:
            val_str = f"{current_value:.4f}"
            thr_str = f"{threshold:.4f}"
            field_label = field
            field_emoji = "\U0001f514"  # 🔔

        direction_emoji = "\U0001f7e2" if current_value >= threshold else "\U0001f534"

        return (
            f"\U0001f6a8 *StockPulse Alert*\n"
            f"━━━━━━━━━━━━\n\n"
            f"{direction_emoji} *{symbol}* {field_label} 突破阈值！\n\n"
            f"{field_emoji} 当前{field_label}: `{val_str}`\n"
            f"⚖ 阈值条件: {operator} `{thr_str}`\n\n"
            f"_⏰ {ts}_"
        )

    def _mask_token(self) -> str:
        """Return a masked version of the bot token for display."""
        t = self.bot_token
        if len(t) > 12:
            return t[:8] + "***" + t[-4:]
        return "***"

    # ── HTTP transport ────────────────────────────────────────────

    def _send_with_retry(self, text: str) -> bool:
        """Post a message to Telegram with up to N retries on failure.

        Returns True once the API responds 200, False if all retries exhausted.
        """
        last_error: str | None = None

        for attempt in range(_SEND_MAX_RETRIES):
            try:
                if self._post_message(text):
                    return True
            except Exception as exc:
                last_error = str(exc)

            if attempt < _SEND_MAX_RETRIES - 1:
                wait = _SEND_BASE_DELAY * (2 ** attempt)
                logger.debug(
                    "Telegram send attempt %d/%d failed%s. Retrying in %.1fs",
                    attempt + 1, _SEND_MAX_RETRIES,
                    f": {last_error}" if last_error else "",
                    wait,
                )
                time.sleep(wait)

        logger.error(
            "Telegram send failed after %d attempts%s",
            _SEND_MAX_RETRIES,
            f": {last_error}" if last_error else "",
        )
        return False

    def _post_message(self, text: str) -> bool:
        """Single HTTP POST to the Telegram Bot API (stdlib urllib).

        Raises an exception on network / HTTP error so the retry loop
        can back off and re-attempt.
        """
        url = TELEGRAM_API.format(token=self.bot_token)
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read()
            if resp.status == 200:
                return True
            logger.warning(
                "Telegram API returned %d: %s",
                resp.status,
                body[:200].decode(errors="replace"),
            )
            raise RuntimeError(f"HTTP {resp.status}: {body[:100]!r}")

    @property
    def enabled(self) -> bool:
        """True if the notifier has valid credentials."""
        return self._available
