<div align="center">

<img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+">
<img src="https://img.shields.io/badge/license-MIT-green.svg" alt="MIT License">
<img src="https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg" alt="Platform">
<img src="https://img.shields.io/badge/version-2.1.0-brightgreen.svg" alt="v2.1.0">

</div>

# StockPulse

Real-time stock quote monitor with US + A-share support, multi-source auto-failover, Telegram alerts, and data export.

**StockPulse** polls EastMoney, Sina Finance, and Yahoo Finance with automatic failover, delivering live quotes for US stocks and Chinese A-shares to your terminal. Configure price alerts, send real-time notifications via Telegram Bot, and export tick data to CSV/JSON.

---

## 目录 | Table of Contents

- [功能特性 | Features](#-功能特性--features)
- [快速开始 | Quick Start](#-快速开始--quick-start)
- [安装 | Installation](#-安装--installation)
- [使用方式 | Usage](#-使用方式--usage)
- [配置说明 | Configuration](#-配置说明--configuration)
- [命令行参考 | CLI Reference](#-命令行参考--cli-reference)
- [性能表现 | Performance](#-性能表现--performance)
- [项目结构 | Project Structure](#-项目结构--project-structure)
- [打包为 EXE | Build EXE](#-打包为-exe--build-exe)
- [TODO | Roadmap](#-todo--roadmap)
- [贡献 | Contributing](#-贡献--contributing)
- [许可证 | License](#-许可证--license)

---

## 功能特性 | Features

- **Multi-Source Failover** — EastMoney (richest data) → Sina (fastest) → Yahoo (fallback), automatic fallback on failure
- **US + A-Share Support** — Monitor NVDA, AAPL, TSLA, 600519.SH, 000333.SZ, mixed markets in one pane
- **Auto Market Detection** — Symbols auto-routed to correct API (`.SH` → Shanghai, `.SZ` → Shenzhen, default → US)
- **Price Alerts** — Configurable threshold alerts with cooldown to prevent spam (e.g. NVDA > 230 or < 210)
- **Telegram Notifications** — Real-time alert push via Telegram Bot with cooldown (Markdown-formatted messages)
- **Smart Dedup** — Only prints when price or volume changes; fetches still counted for statistics
- **Per-Minute Stats** — Auto-prints volume delta and current price summary every 60 seconds
- **Data Export** — CSV (11 fields) and JSON Lines output with crash-safe flush-on-write
- **ANSI Colors** — Green for gains, red for losses, dimmed metadata; toggle with `--no-color`
- **Graceful Shutdown** — Ctrl+C prints session summary: runtime, total fetches, average rate, per-symbol last price & range
- **Structured Logging** — Console (INFO+) + rotating file (DEBUG), hierarchical logger names
- **Configurable** — YAML config file + CLI arguments, layered merge (defaults → YAML → CLI)
- **Type-Hinted & PEP8** — Full type annotations, dataclass config, ABC source/export abstractions
- **Backward Compatible** — Legacy `nvda_realtime_scraper.py` still works as a thin shim

---

## 快速开始 | Quick Start

```bash
# Clone and enter the project
cd scraping_exam

# Install dependencies
pip install -r requirements.txt

# Monitor NVDA with default 2s interval
python -m stock_monitor -s NVDA

# Monitor multiple stocks with custom interval
python -m stock_monitor -s NVDA,AAPL,TSLA -i 1.5

# Monitor A-shares (use .SH for Shanghai, .SZ for Shenzhen)
python -m stock_monitor -s 600519.SH,000333.SZ

# Mixed US + A-share monitoring
python -m stock_monitor -s NVDA,600519.SH,AAPL

# Add price alerts with Telegram notifications
python -m stock_monitor -s NVDA -a NVDA:>:230 --telegram
```

**Sample output:**

```
  NVDA, AAPL  |  2.0s interval  |  -> stock_ticks.csv
  Sources: EastMoney / Sina / Yahoo
  Running...  Ctrl+C to exit
      Time  Sym          Price      Change      Chg%          Volume        Hi        Lo  [Src]
==============================================================================================
  21:55:53  NVDA    $   215.33    -4.1800    -1.90%     169,275,710    221.01    214.80  [EAST]
  21:55:55  AAPL    $   308.82    +3.8300    +1.26%      43,670,223    311.40    305.84  [EAST]
  [ALERT] NVDA price $215.33 < $230.00
```

---

## 安装 | Installation

### Prerequisites

- Python **3.10+** (tested on 3.12, 3.14)
- pip

### Dependencies

| Package    | Version   | Purpose                          |
|------------|-----------|----------------------------------|
| scrapling  | >=0.4.8   | HTTP client with TLS impersonation |
| pyyaml     | >=6.0     | YAML config file parsing         |
| yfinance   | >=0.2.0   | Yahoo Finance data (optional)    |
| colorama   | >=0.4.6   | ANSI color on Windows            |

```bash
pip install -r requirements.txt
```

> **Note:** `pyyaml` and `yfinance` are optional. Without PyYAML, config files are disabled (CLI still works). Without yfinance, the Yahoo fallback source is skipped.

---

## 使用方式 | Usage

### 1. Basic: single stock

```bash
python -m stock_monitor -s NVDA
```

### 2. Multiple stocks

```bash
python -m stock_monitor -s NVDA,AAPL,TSLA -i 2
```

### 3. With YAML configuration

```bash
python -m stock_monitor -c config.yaml
```

### 4. With price alerts

```bash
# Alert when NVDA goes above $230 or below $210
python -m stock_monitor -s NVDA -a NVDA:>:230 -a NVDA:<:210

# Alert on percentage change (AAPL drops more than 5%)
python -m stock_monitor -s AAPL -a AAPL:change_pct:<:-5
```

Alert format: `SYMBOL:FIELD:OPERATOR:THRESHOLD`

- FIELD: `price` (default), `change`, `change_pct`, `volume`
- OPERATOR: `>`, `<`, `>=`, `<=`

### 5. A-share monitoring

```bash
# Shanghai Stock Exchange (use .SH suffix)
python -m stock_monitor -s 600519.SH        # 贵州茅台 (Kweichow Moutai)

# Shenzhen Stock Exchange (use .SZ suffix)
python -m stock_monitor -s 000333.SZ        # 美的集团 (Midea Group)

# Multiple A-shares
python -m stock_monitor -s 600519.SH,000333.SZ,000858.SZ

# Mixed US + A-shares
python -m stock_monitor -s NVDA,600519.SH,AAPL,000333.SZ
```

> **Symbol format:** `.SH` = Shanghai A-share, `.SZ` = Shenzhen A-share, no suffix = US stock
> A-share prices display in ¥ (yuan) automatically.

### 6. Telegram Bot notifications

#### Step 1: Create a Telegram Bot

1. Open Telegram, search for **@BotFather** (official bot creator)
2. Send `/newbot` and follow the prompts:
   - Enter a display name, e.g. `My StockPulse`
   - Enter a username ending in `bot`, e.g. `mystockpulse_bot`
3. BotFather will reply with your **Bot Token**:
   ```
   123456:ABC-DEF1234ghikl...
   ```
4. Copy this token — you'll paste it into `config.yaml`

#### Step 2: Get your Chat ID

**Option A — Direct Message (recommended for personal use):**
1. Open Telegram, search for your newly created bot (e.g. `@mystockpulse_bot`)
2. Click **Start** (or send `/start`) to activate the conversation
3. Search for **@userinfobot**, send `/start`, and it will reply with your numeric user ID
4. This number is your `chat_id`

**Option B — Group Chat:**
1. Create a new group, add your bot as a member
2. Send a message in the group mentioning your bot
3. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in a browser
4. Look for `"chat":{"id":-123456789,...}` — the negative number is your group `chat_id`

#### Step 3: Configure `config.yaml`

```yaml
telegram:
  bot_token: "123456:ABC-DEF1234ghikl"   # from @BotFather (Step 1)
  chat_id: "987654321"                    # from @userinfobot (Step 2)
  enabled: true                           # or use --telegram CLI flag
  cooldown_seconds: 60                    # minimum seconds between alerts
```

#### Step 4: Test the connection

```bash
python -m stock_monitor --test-telegram --telegram
```

You should see `[OK] 测试消息发送成功！` and receive this in Telegram:

```
✅ StockPulse — 测试成功
您的 Telegram Bot 已正确配置并成功连接。
```

If it fails, check:
- Did you send `/start` to your bot first?
- Is the `bot_token` copied correctly (no extra spaces)?
- Is the `chat_id` a number (private) or negative number (group)?

#### Step 5: Run with alerts

```bash
python -m stock_monitor -s NVDA -a NVDA:>:230 --telegram
```

When an alert triggers:

```
🚨 StockPulse Alert
━━━━━━━━━━━━

🟢 NVDA 价格 突破阈值！

💰 当前价格: $235.67
⚖ 阈值条件: > $230.00

⏰ 2026-05-24 14:22:15
```

#### Advanced: Enable without CLI flag

Set `enabled: true` in `config.yaml` to always use Telegram (no `--telegram` flag needed):

```bash
python -m stock_monitor -s NVDA -a NVDA:>:230   # Telegram auto-enabled via YAML
```

### 7. JSON export

```bash
python -m stock_monitor -s NVDA --json nvda_ticks.jsonl
```

### 8. Legacy entry point (backward compatible)

```bash
python nvda_realtime_scraper.py -s NVDA
```

---

## 配置说明 | Configuration

Create a `config.yaml` in the project directory (auto-detected), or specify with `-c`:

```yaml
# ── Stocks to monitor ──────────────────────────
# US stocks: NVDA, AAPL, TSLA, etc.
# A-shares:  600519.SH (茅台), 000333.SZ (美的)
symbols:
  - NVDA
  - AAPL

# ── Polling interval (seconds) ─────────────────
interval: 2.0

# ── Export paths ────────────────────────────────
csv_path: stock_ticks.csv
json_path: ""                  # disable JSON export

# ── Price Alerts ────────────────────────────────
alerts:
  - symbol: NVDA
    field: price
    operator: ">"
    threshold: 230.0
    cooldown_ticks: 5

  - symbol: NVDA
    field: price
    operator: "<"
    threshold: 210.0

  # A-share alert example (¥)
  # - symbol: 600519.SH
  #   field: price
  #   operator: ">"
  #   threshold: 1800.0
  #   cooldown_ticks: 5

# ── Telegram Bot notifications ─────────────────
telegram:
  bot_token: ""                # from @BotFather
  chat_id: ""                  # your Telegram chat ID
  enabled: false               # set to true or use --telegram flag
  cooldown_seconds: 60         # min seconds between alerts

# ── Data source priority ────────────────────────
source_order:
  - eastmoney
  - sina
  - yahoo

# ── Retry settings ──────────────────────────────
retry_max: 3
retry_base_delay: 1.0
retry_max_delay: 30.0

# ── Logging ─────────────────────────────────────
log_level: INFO
log_file: stock_monitor.log
```

### Configuration Priority

```
Hardcoded defaults  →  config.yaml  →  CLI arguments (highest)
```

---

## 命令行参考 | CLI Reference

```
usage: stock-monitor [-h] [-s SYMBOLS] [-i INTERVAL] [--csv CSV] [--json JSON]
                     [--no-color] [-c CONFIG] [-a SPEC]
                     [--log-level {DEBUG,INFO,WARNING,ERROR}]
                     [--log-file LOG_FILE] [--telegram] [--test-telegram]
                     [--version]

Options:
  -s, --symbols      Comma-separated stock symbols (e.g. NVDA,AAPL,TSLA)
  -i, --interval     Polling interval in seconds (default: 2.0)
  --csv              CSV output path (default: stock_ticks.csv)
  --json             JSON Lines output path (disabled by default)
  --no-color         Disable ANSI color output
  -c, --config       Path to YAML config file (auto-detects ./config.yaml)
  -a, --alert        Price alert spec: SYM:OP:THR or SYM:FLD:OP:THR
  --telegram         Enable Telegram alert notifications (credentials in config.yaml)
  --test-telegram    Send a test message via Telegram Bot, then exit
  --log-level        Console log level: DEBUG, INFO, WARNING, ERROR
  --log-file         Path to rotating log file (DEBUG level)
  --version          Show version and exit
  -h, --help         Show this help message
```

---

## 性能表现 | Performance

| Metric          | Value                    |
|-----------------|--------------------------|
| Avg fetch time  | 100-300ms (EastMoney)    |
| CPU usage       | < 1% (2s interval)       |
| Memory          | ~30 MB                   |
| CSV throughput  | ~1 write/tick (on change)|
| Backoff ceiling | 30s (configurable)       |

---

## 项目结构 | Project Structure

```
scraping_exam/
├── stock_monitor/                    # Core package (v2.1.0)
│   ├── __init__.py                   # Public API, __version__
│   ├── __main__.py                   # python -m stock_monitor
│   ├── cli.py                        # Argument parsing, entry point
│   ├── config.py                     # Dataclass config, YAML loader, merge
│   ├── monitor.py                    # StockMonitor orchestrator
│   ├── display.py                    # ANSI formatting, Display class
│   ├── alerts.py                     # AlertCondition, AlertManager
│   ├── tracker.py                    # SymbolTracker, SessionStats
│   ├── utils.py                      # safe_decode, fmt_*, retry_with_backoff
│   ├── logging_setup.py              # Console + rotating file logging
│   ├── sources/                      # Data source package
│   │   ├── __init__.py               # Source registry
│   │   ├── base.py                   # BaseSource ABC (template method)
│   │   ├── eastmoney.py              # EastMoneySource
│   │   ├── sina.py                   # SinaSource
│   │   └── yahoo.py                  # YahooSource (graceful yfinance fail)
│   ├── exporters/                    # Exporter package
│   │   ├── __init__.py
│   │   ├── base.py                   # BaseExporter ABC
│   │   ├── csv_exporter.py           # CsvExporter (csv.DictWriter)
│   │   └── json_exporter.py          # JsonExporter (JSON Lines)
│   └── notifiers/                    # Alert notification package
│       ├── __init__.py
│       └── telegram.py               # Telegram Bot notifier
├── config.example.yaml               # Example config template (safe to commit)
├── config.yaml                       # User configuration (gitignored)
├── nvda_realtime_scraper.py          # Backward-compatible shim
├── requirements.txt                  # Python dependencies
├── build_exe.bat                     # PyInstaller one-file packaging
├── .gitignore                        # Git ignore rules
├── LICENSE                           # MIT License
└── README.md                         # This file
```

---

## 打包为 EXE | Build EXE

### One-command build

```bat
build_exe.bat
```

This produces `dist\StockPulse-v2.1.0.exe` (single file, ~15 MB).

### Custom build

```bat
build_exe.bat 2.1.0                    # custom version
build_exe.bat --no-console            # hide console window
build_exe.bat --icon myicon.ico       # custom icon
```

### Manual PyInstaller

```bash
pip install pyinstaller
pyinstaller --onefile --name StockPulse-v2.1.0 --console stock_monitor/__main__.py
```

---

## TODO | Roadmap

- [x] Telegram Bot alert notifications (v2.1.0)
- [x] A-share (Shanghai/Shenzhen) support (v2.1.0)
- [ ] Interactive TUI mode (Textual) — real-time dashboard in terminal
- [ ] Web dashboard (Flask/FastAPI) — browser-based monitoring with charts
- [ ] SQLite / InfluxDB export — persistent storage for historical analysis
- [ ] Docker image — one-command headless deployment on VPS/NAS
- [ ] Plugin system — custom data sources via entry points
- [ ] pip package distribution — `pip install stockpulse`
- [ ] Hong Kong stock support (`.HK` suffix, HKEX)
- [ ] Desktop GUI tray app (Pyside6 / Tauri)

---

## 已知问题 | Known Issues

### Windows 控制台 GBK 编码

Windows 中文版的 `cmd.exe` 和 PowerShell 使用 GBK 编码，Unicode 字符 `¥`（U+00A5）可能无法正常显示。StockPulse v2.1.0 已使用全角 `￥`（U+FFE5）替代，但如果在某些旧版 Windows 终端上仍出现乱码，建议：

```bash
# 方案 1: 使用 Windows Terminal（推荐）
# 从 Microsoft Store 安装 "Windows Terminal"，天然支持 UTF-8

# 方案 2: 临时切换代码页
chcp 65001
python -m stock_monitor -s NVDA

# 方案 3: 使用 --no-color 禁用 ANSI 颜色
python -m stock_monitor -s NVDA --no-color
```

### Telegram 429 限流

Telegram Bot API 对同一聊天有频率限制（~30 条/秒/聊天）。如果短时间内多次触发告警，可能会收到 429 响应。StockPulse 内置了指数退避重试机制（最多 3 次），并支持通过 `cooldown_seconds` 配置告警冷却时间。

### yfinance 数据延迟

Yahoo Finance 作为兜底数据源时，美股实时数据可能有 15 分钟延迟（非美国交易所要求）。建议将 Yahoo 放在 `source_order` 的最后一位。

---

## GitHub 开源发布指南 | Open-Source Release Guide

### Step 1: 初始化 Git 仓库

```bash
cd scraping_exam
git init
git checkout -b main
```

### Step 2: 配置 .gitignore

项目已包含 `.gitignore`，确认以下文件不会被提交：
- `__pycache__/`、`*.pyc`
- `build/`、`dist/`、`*.spec`
- `*.csv`、`*.jsonl`、`*.log`
- `.env`、`venv/`

```bash
git status  # 检查待提交文件
```

### Step 3: 添加敏感信息保护

**重要：** 提交前移除 `config.yaml` 中的真实 Telegram 凭据！

项目已包含 `config.example.yaml`（模板）和 `.gitignore` 中的 `config.yaml` 规则。只需确认你的真实凭据在 `config.yaml` 中且不会被提交：

```bash
# config.yaml 已在 .gitignore 中，不会被提交
git status  # 确认 config.yaml 不在待提交列表中
```

### Step 4: 撰写提交

```bash
git add .
git commit -m "$(cat <<'EOF'
Initial commit: StockPulse v2.1.0

Real-time stock quote monitor with US + A-share support,
multi-source failover (EastMoney/Sina/Yahoo), Telegram alerts,
and CSV/JSON export.
EOF
)"
```

### Step 5: 推送到 GitHub

```bash
# 在 GitHub 上创建新仓库（不要勾选 README/LICENSE/.gitignore）

git remote add origin https://github.com/YOUR_USERNAME/StockPulse.git
git push -u origin main

# 打标签
git tag v2.1.0
git push --tags
```

### Step 6: 构建并发布 EXE

```bat
REM 构建 EXE
build_exe.bat

REM 验证
dist\StockPulse-v2.1.0.exe --version
```

在 GitHub Releases 页面：
1. 点击 **Draft a new release**
2. Tag: `v2.1.0`
3. Title: `StockPulse v2.1.0`
4. 上传 `dist\StockPulse-v2.1.0.exe`
5. Release notes:

```markdown
## What's New in v2.1.0

- Telegram Bot 实时告警通知（支持 Markdown 格式、冷却时间、重试机制）
- A股（沪深两市）实时行情支持（`.SH` 上海 / `.SZ` 深圳）
- `--test-telegram` 诊断命令
- 修复 dataclass default_factory 配置合并 Bug
- 完善 README 文档（双语）

## Installation

### 方式 1: 下载 EXE（Windows 用户）

下载 `StockPulse-v2.1.0.exe`，直接运行：

```bat
StockPulse-v2.1.0.exe -s NVDA -i 2
```

### 方式 2: pip + 源码

```bash
git clone https://github.com/YOUR_USERNAME/StockPulse.git
cd StockPulse
pip install -r requirements.txt
python -m stock_monitor -s NVDA
```
```

### Step 7: 发布到 PyPI（可选）

```bash
# 安装构建工具
pip install build twine

# 构建
python -m build

# 上传
twine upload dist/*
```

---

## 贡献 | Contributing

Contributions are welcome. Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

---

## 许可证 | License

Distributed under the MIT License. See [LICENSE](LICENSE) for details.

---

<div align="center">
  <sub>Built with Python · Powered by Scrapling · MIT Licensed</sub>
</div>
