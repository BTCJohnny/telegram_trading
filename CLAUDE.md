# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Telegram Signal Trading Bot for the Hyperliquid decentralized exchange. The bot automatically reads trading signals from Telegram channels, parses them using regex patterns, and executes trades with dynamic position sizing and risk management.

## Key Architecture

The project uses a modular Python package structure with clear separation of concerns:

```
telegram_trading/
├── main.py                     # Single entry point - orchestrates bot startup
├── config.py                   # Centralized configuration from environment variables
├── bot_core/                   # Core trading logic package
│   ├── hyperliquid_api.py      # Direct Hyperliquid API interaction
│   ├── strategy_manager.py     # Trading logic and signal processing
│   ├── trade_persistence.py    # SQLite database and monitoring threads
│   ├── telegram_interface.py   # Telegram message parsing and handling
│   └── utils.py                # Shared utilities
├── tests/                      # Test files (ignored in .gitignore)
└── backup_code/                # Legacy code versions
```

## Common Development Commands

### Running the Bot
```bash
# Run the main trading bot
python main.py

# Test configuration only
python main.py test-config

# Test database connectivity
python main.py test-db

# Run all tests
python main.py test-all
```

### Testing Individual Components
```bash
# Test specific functionality files
python test_trade.py                    # Trade execution tests
python test_parsing.py                  # Message parsing tests
python standalone_telegram_trader.py    # Standalone bot version
python debug_message_parser.py          # Debug message parsing
```

### Development Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Set up environment (copy .envexample to .env and configure)
cp .envexample .env
```

## Critical Configuration

The bot operates in two modes controlled by `USE_TESTNET` in config.py:
- **TESTNET**: Safe testing environment (recommended for development)
- **MAINNET**: Live trading with real money (production only)

All configuration is environment-driven through `.env` file. The `config.py` file validates required settings and provides detailed logging of the current configuration.

## Core Components

### Hyperliquid Integration (`bot_core/hyperliquid_api.py`)
- Handles all direct API calls to Hyperliquid exchange
- Manages account initialization using eth_account
- Provides functions: `ask_bid`, `limit_order`, `get_position`, `kill_switch`, etc.
- Uses caching for static data like decimal precision

### Trading Logic (`bot_core/strategy_manager.py`)
- Implements dynamic position sizing based on signal confidence levels
- Handles bullish/bearish entry signals with slippage control
- Manages trailing stops and profit taking
- Calculates trade sizes using `FUNDING_PER_1_5_UNIT` parameter

### Data Persistence (`bot_core/trade_persistence.py`)
- SQLite database for trade tracking and portfolio history
- Background monitoring thread for continuous PnL tracking
- Automatic position management (stop-loss, take-profit)
- Database includes: `monitored_trades`, `portfolio_history`, `signal_history` tables

### Telegram Interface (`bot_core/telegram_interface.py`)
- Regex-based signal parsing from Telegram messages
- Handles multiple signal types: bullish entry, bearish entry, exit signals
- Integrates with python-telegram-bot v20+ for message handling

## Database Schema

The bot maintains persistent state in SQLite:
- **monitored_trades**: Active and historical trade records with PnL tracking
- **portfolio_history**: Daily portfolio value snapshots
- **signal_history**: All parsed Telegram signals for analysis

Database file: `bot_trades.db` (created automatically)

## Security and Risk Management

- API keys are environment-only (never hardcoded)
- `config.py` is git-ignored to prevent key exposure
- Built-in slippage protection and emergency kill switch functionality
- Comprehensive logging for all trading actions and errors
- Automatic position monitoring with configurable risk parameters

## Testing Strategy

The project includes multiple test files for different components:
- Signal parsing and message interpretation
- Trade execution simulation
- Database operations
- Configuration validation

All initial testing should be performed on TESTNET before any mainnet deployment.

## Important Files to Never Commit

- `config.py` - Contains sensitive API keys
- `*.db` - Database files with trading history
- `*.log` - Log files with potentially sensitive data
- `session.session` - Telegram session files