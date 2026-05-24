"""Configuration dataclasses, YAML loading, and merge logic."""

from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from argparse import Namespace

logger = logging.getLogger("stock_monitor.config")

# ── Alert Spec ──────────────────────────────────────────────────────


@dataclass
class AlertSpec:
    """Definition of a single price-alert threshold.

    Example YAML::

        alerts:
          - symbol: NVDA
            field: price
            operator: ">"
            threshold: 230.0
    """

    symbol: str
    field: str = "price"
    operator: str = ">"
    threshold: float = 0.0
    cooldown_ticks: int = 5
    source: str = ""  # "yaml" or "cli" — for merge dedup

    _valid_fields = frozenset({"price", "change", "change_pct", "volume"})
    _valid_ops = frozenset({">", "<", ">=", "<="})

    def __post_init__(self) -> None:
        self.symbol = self.symbol.strip().upper()
        if self.field not in self._valid_fields:
            raise ValueError(
                f"Alert field '{self.field}' not in {sorted(self._valid_fields)}"
            )
        if self.operator not in self._valid_ops:
            raise ValueError(
                f"Alert operator '{self.operator}' not in {sorted(self._valid_ops)}"
            )


# ── Telegram Config ──────────────────────────────────────────────────


@dataclass
class TelegramConfig:
    """Telegram Bot notification settings.

    Example YAML::

        telegram:
          bot_token: "123456:ABC-DEF1234ghikl"
          chat_id: "987654321"
          enabled: true
          cooldown_seconds: 60
    """

    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = False
    cooldown_seconds: int = 60

    def __bool__(self) -> bool:
        return self.enabled and bool(self.bot_token) and bool(self.chat_id)


# ── Main Config ─────────────────────────────────────────────────────


@dataclass
class StockMonitorConfig:
    """Runtime configuration for StockMonitor.

    Values can be set via hardcoded defaults, a YAML config file,
    or command-line arguments (with CLI taking highest priority).
    """

    symbols: list[str] = field(default_factory=lambda: ["NVDA"])
    interval: float = 2.0
    csv_path: str = "stock_ticks.csv"
    json_path: str = ""
    use_color: bool = True
    stats_interval: float = 60.0
    alerts: list[AlertSpec] = field(default_factory=list)
    source_order: list[str] = field(
        default_factory=lambda: ["sina", "eastmoney", "yahoo"]
    )
    retry_max: int = 3
    retry_base_delay: float = 1.0
    retry_max_delay: float = 30.0
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    log_level: str = "INFO"
    log_file: str = ""


# ── YAML Loading ────────────────────────────────────────────────────


def load_config_from_yaml(path: str | Path) -> StockMonitorConfig | None:
    """Load configuration from a YAML file.

    Returns None if the file does not exist or PyYAML is not installed.
    """
    try:
        import yaml
    except ImportError:
        logger.warning("PyYAML not installed — cannot load config file")
        return None

    yaml_path = Path(path)
    if not yaml_path.exists():
        logger.debug("Config file not found: %s", yaml_path)
        return None

    with open(yaml_path, encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    # Parse alerts
    alert_specs: list[AlertSpec] = []
    for entry in raw.pop("alerts", []) or []:
        entry["source"] = "yaml"
        entry["symbol"] = str(entry.get("symbol", "")).strip().upper()
        alert_specs.append(AlertSpec(**entry))

    # Parse telegram
    tg_raw = raw.pop("telegram", {}) or {}
    telegram_cfg = TelegramConfig(
        bot_token=str(tg_raw.get("bot_token", "")),
        chat_id=str(tg_raw.get("chat_id", "")),
        enabled=bool(tg_raw.get("enabled", False)),
        cooldown_seconds=int(tg_raw.get("cooldown_seconds", 60)),
    )

    raw_symbols: list[str] = raw.get("symbols", ["NVDA"])
    symbols = [s.strip().upper() for s in raw_symbols if s.strip()]

    return StockMonitorConfig(
        symbols=symbols or ["NVDA"],
        interval=float(raw.get("interval", 2.0)),
        csv_path=str(raw.get("csv_path", "stock_ticks.csv")),
        json_path=str(raw.get("json_path", "")),
        use_color=bool(raw.get("use_color", True)),
        stats_interval=float(raw.get("stats_interval", 60.0)),
        alerts=alert_specs,
        source_order=raw.get("source_order", ["eastmoney", "sina", "yahoo"]),
        retry_max=int(raw.get("retry_max", 3)),
        retry_base_delay=float(raw.get("retry_base_delay", 1.0)),
        retry_max_delay=float(raw.get("retry_max_delay", 30.0)),
        telegram=telegram_cfg,
        log_level=str(raw.get("log_level", "INFO")),
        log_file=str(raw.get("log_file", "")),
    )


# ── CLI Loading ─────────────────────────────────────────────────────


def load_config_from_args(args: Namespace) -> StockMonitorConfig:
    """Build a ``StockMonitorConfig`` from parsed CLI arguments.

    Only fields explicitly set via CLI are populated; all others use
    the dataclass defaults so the merge step can distinguish them.
    """
    from dataclasses import fields as dc_fields

    # Start with defaults, then overwrite only what CLI provides
    kwargs: dict = {}
    cli_fields = {f.name for f in dc_fields(StockMonitorConfig)}
    _skip = {"telegram", "alerts"}  # handled separately

    for name in cli_fields - _skip:
        if hasattr(args, name):
            val = getattr(args, name)
            if val is not None:
                kwargs[name] = val

    # Parse alert specs from CLI: list of "SYMBOL:FIELD:OP:THRESHOLD"
    alert_specs: list[AlertSpec] = []
    raw_alerts: list[str] = getattr(args, "alert", []) or []
    for spec_str in raw_alerts:
        parts = spec_str.split(":", maxsplit=3)
        if len(parts) == 3:
            sym, op, thr = parts
            fld = "price"
        elif len(parts) == 4:
            sym, fld, op, thr = parts
        else:
            logger.warning("Invalid alert spec: %r (expected SYM:OP:THR or SYM:FLD:OP:THR)", spec_str)
            continue
        alert_specs.append(AlertSpec(
            symbol=sym.upper(),
            field=fld,
            operator=op,
            threshold=float(thr),
            source="cli",
        ))

    cfg = StockMonitorConfig(**kwargs) if kwargs else StockMonitorConfig()
    if alert_specs:
        cfg.alerts = alert_specs
    return cfg


# ── Merge Logic ─────────────────────────────────────────────────────


def merge_configs(
    base: StockMonitorConfig, override: StockMonitorConfig
) -> StockMonitorConfig:
    """Deep-merge two configs, with *override* values taking priority.

    Special handling for ``alerts``:
        CLI-defined alerts are *appended* to YAML-defined alerts
        (not replaced), so both sources are active.
    """
    merged = deepcopy(base)
    for field_name in _config_field_names(base):
        override_val = getattr(override, field_name)
        base_val = getattr(base, field_name)
        default_val = _default_for_field(StockMonitorConfig, field_name)

        if field_name == "alerts":
            # Append CLI alerts to YAML alerts (dedup by symbol+field+operator+threshold)
            existing = {(a.symbol, a.field, a.operator, a.threshold) for a in base.alerts}
            for a in override.alerts:
                if (a.symbol, a.field, a.operator, a.threshold) not in existing:
                    merged.alerts.append(a)
                    existing.add((a.symbol, a.field, a.operator, a.threshold))
        elif override_val != default_val:
            setattr(merged, field_name, override_val)

    return merged


def _config_field_names(cfg: StockMonitorConfig) -> list[str]:
    from dataclasses import fields as dc_fields
    return [f.name for f in dc_fields(type(cfg))]


def _default_for_field(cls: type, field_name: str) -> object:
    from dataclasses import MISSING, fields as dc_fields
    for f in dc_fields(cls):
        if f.name == field_name:
            if f.default_factory is not MISSING:
                return f.default_factory()
            if f.default is not MISSING:
                return f.default
    return None
