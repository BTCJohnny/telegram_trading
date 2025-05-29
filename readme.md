# Hyperliquid Telegram Signal Trading Bot

<!-- Project introduction -->

This project provides a Python-based trading bot designed to automate trade execution on the Hyperliquid decentralized exchange by reading signals from a designated Telegram channel. It uses a predefined risk management approach to size trades based on the confidence level provided in the Telegram messages.

## Features

- **Telegram Message Parsing:** Automatically reads and interprets specific Telegram messages containing bullish entry signals (symbol, entry price, size confidence).
- **Dynamic Trade Sizing:** Translates "Size: X/Y" confidence levels from Telegram into concrete trade sizes (`sz`) for Hyperliquid, based on a configurable USD allocation per unit.
- **Limit Order Execution:** Places limit buy orders on Hyperliquid for detected signals.
- **PnL-based Position Management:** Includes functions for taking profit (`target_pnl`) and stopping losses (`max_loss_pnl`) on open positions.
- **Emergency Kill Switch:** A robust function to immediately close any open position for a given symbol by aggressively market-trading out.
- **Comprehensive Logging:** Provides detailed logging for all actions and statuses, helping you monitor and debug the bot's operations.
- **Separation of Concerns:** Clearly separates sensitive API keys and configuration from the core bot logic.

## Prerequisites

Before you begin, ensure you have the following:

1. **Python 3.8+:** The bot is developed in Python.
2. **Hyperliquid Account:** An active account on Hyperliquid.
3. **Hyperliquid API Secret Key:** You'll need your secret key for programmatic trading. This key should be kept **highly confidential**.
4. **Telegram Account:** To create your bot and designate a channel for signals.
5. **Understanding of Hyperliquid Trading:** Familiarity with concepts like `sz` (lot size) and limit orders.

## Project Structure

```
├── do_not_share.py         # CRITICAL: Your sensitive API keys and configuration.
├── hyperliquid_bot.py      # Core Hyperliquid trading functions (asks, bids, orders, positions).
├── telegram_listener.py    # (To be created) The script that listens to Telegram and calls hyperliquid_bot.
├── requirements.txt        # List of Python dependencies.
└── README.md               # This documentation file.
```

## Setup

Follow these steps to set up your trading bot:

### 1. Clone the Repository

(If you have this as a fresh project, simply create the files in a new directory.)

```bash
git clone <your-repo-url>
cd <your-repo-directory>
```

### 2. Install Dependencies

Install all required Python libraries using pip:

```bash
pip install -r requirements.txt
```

### 3. Create and Configure do_not_share.py

This file holds your sensitive credentials and trading parameters. **NEVER share this file or commit it to a public repository.**

Create a file named `do_not_share.py` in the same directory as your bot scripts, and fill it with the following content:

<!-- Instructions for getting Telegram Bot Token and Channel ID -->

**How to get your Telegram Bot Token:**

1. Open Telegram and search for @BotFather.
2. Start a chat and send `/newbot`.
3. Follow the instructions to name your bot and choose a username.
4. BotFather will give you an HTTP API Token. Copy this token.

**How to get your Telegram Channel ID:**

1. Add your newly created bot as an administrator to the Telegram channel you want to monitor.
2. Send any message in that channel (e.g., "test").
3. Open your web browser and go to:
   `https://api.telegram.org/bot<YOUR_BOT_TOKEN>/getUpdates` (replace `<YOUR_BOT_TOKEN>` with your actual token).
4. Look for the `"chat"` object in the JSON response. The `"id"` field inside it is your CHAT_ID. It will likely be a negative number if it's a channel (e.g., -1001234567890).

### 4. Create telegram_listener.py (Main Bot Entry Point)

Based on the previous discussion, you'll need a file that acts as the main entry point for your Telegram bot, importing and utilizing the functions from `hyperliquid_bot.py`. This script will contain the Updater and MessageHandler logic for python-telegram-bot.

(Please refer to the Phase 1: Telegram Integration section of our previous conversation for the detailed code for `telegram_listener.py`. It should import `hyperliquid_bot.py` and call its functions.)

## How to Test the hyperliquid_bot.py Utilities

The `hyperliquid_bot.py` file contains an `if __name__ == '__main__':` block that allows you to test individual functions.

> **IMPORTANT SAFETY WARNING:**
>
> - **ALWAYS** start with Hyperliquid Testnet if possible (adjust `constants.MAINNET_API_URL` to `constants.TESTNET_API_URL` in `hyperliquid_bot.py`).
> - **NEVER** use significant capital when testing. Start with the absolute minimum allowed trade sizes.
> - **BE CAREFUL** with `limit_order` and `kill_switch` when uncommenting their test lines, as these execute real trades.

To run the individual function tests:

```bash
python hyperliquid_bot.py
```

Observe the console output (logging messages) to ensure functions like `acct_bal`, `get_sz_px_decimals`, `ask_bid`, and `get_position` are working correctly.

## How to Run the Trading Bot

Once `telegram_listener.py` is fully implemented and configured (as discussed in previous steps), it will be the main script you run.

- Ensure `do_not_share.py` is correctly configured.
- Make sure `telegram_listener.py` is ready (it will import `hyperliquid_bot.py`).

Start the bot:

```bash
python telegram_listener.py
```

The bot will then start polling Telegram for new messages in the specified channel. When a message matching the "Today's Bullish Entries" pattern arrives, it will parse the signal and attempt to place a trade on Hyperliquid.

## Running the Bot Continuously (24/7)

For continuous operation, you'll want to run the bot in the background:

**Using tmux or screen (Linux/macOS):** These utilities allow you to run processes in detached sessions.

```bash
# Example using tmux
 tmux new -s hyperliquid_bot        # Create a new tmux session named 'hyperliquid_bot'
 python telegram_listener.py        # Start your bot script
 Ctrl+B, D                         # Detach from the session (the bot keeps running)

# To reattach later:
 tmux attach -t hyperliquid_bot
```

**Using systemd (Linux):** For more robust, production-like deployments, create a systemd service unit to manage your bot script, ensuring it starts on boot and restarts if it crashes. (This requires more advanced Linux system administration knowledge.)

---

## Important Considerations and Disclaimer

> **Risk Management:** The bot uses the `FUNDING_PER_1_5_UNIT` parameter to size trades. It is crucial to set this value appropriately based on your total capital and risk tolerance. Automated trading carries significant financial risk, and you can lose capital.
>
> **Network Stability:** Ensure the machine running the bot has a stable internet connection. Disconnections can lead to missed signals or failed order placements.
>
> **API Rate Limits:** Be mindful of Hyperliquid's API rate limits. The current implementation should generally be fine for signal-based trading, but excessive API calls could lead to temporary bans.
>
> **Error Handling:** While the bot includes basic error handling, unexpected API responses or network issues can occur. Monitor the logs regularly.
>
> **No Position Management (yet):** This bot currently focuses on entering trades from Telegram signals. While it has `pnl_close` and `kill_switch` functions, they are not automatically triggered by Telegram exit signals or continuously monitored by the bot itself out of the box in the `telegram_listener.py` as provided for initial entry. You would need to implement:
> - Scheduled PnL Monitoring: A separate process or a job_queue (if using python-telegram-bot's advanced features) to run `pnl_close` on active positions at regular intervals.
> - Telegram Exit Signal Parsing: Additional logic in `telegram_listener.py` to detect and handle 'exit' messages, calling `kill_switch` accordingly.
>
> **Security:** Your Hyperliquid secret key grants full trading access. Protect your `do_not_share.py` file and use environment variables.
>
> **Test on Testnet First:** Always test any changes or new features on the Hyperliquid Testnet before deploying to mainnet.

---

> **DISCLAIMER:**
>
> By using this software, you acknowledge and accept all associated risks, including but not limited to the risk of financial loss. The developers are not responsible for any losses incurred while using this bot.