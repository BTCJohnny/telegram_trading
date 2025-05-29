# telegram_listener.py --> main.py

import re
import logging
import time
import os # For environment variables, if used in do_not_share.py

# --- Internal Bot Imports ---
# Configure your sensitive data and Hyperliquid account
try:
    import do_not_share as config
    # The `account` object should be initialized in hyperliquid_bot.py or passed explicitly.
    # For simplicity, we assume hyperliquid_bot.py initializes a global `account` and we import it.
    from hyperliquid_bot import account, get_position, ask_bid # Import necessary functions/objects
except ImportError:
    logging.error("do_not_share.py not found. Please create it first.")
    exit()
except Exception as e:
    logging.error(f"Error importing from hyperliquid_bot.py or initializing account: {e}. Ensure API key is correct.")
    exit()

# Import enhanced trading logic functions
from additional_functions import (
    handle_bullish_entry_signal,
    handle_bearish_entry_signal,
    handle_telegram_exit_signal
)

# Import monitoring and persistence components
from monitoring_trading import TradeMonitor, TradeMonitorDB, DB_NAME

# --- Telegram Bot API Imports ---
from telegram.ext import Updater, MessageHandler, filters, CallbackContext
from telegram import Update

# -----------------------------------------------------------------------------
#  1. GLOBAL CONFIGURATION & INITIALIZATION
# -----------------------------------------------------------------------------

# Setup logging for the main listener script
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Verify Telegram bot token and channel ID are set
if not config.TELEGRAM_BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN not set in do_not_share.py or environment. Exiting.")
    exit()
if not config.TELEGRAM_CHANNEL_ID:
    logger.error("TELEGRAM_CHANNEL_ID not set in do_not_share.py or environment. Exiting.")
    exit()

# Initialize Database and Trade Monitor
trade_db_manager = TradeMonitorDB(DB_NAME)
trade_monitor = TradeMonitor(account, trade_db_manager)

# -----------------------------------------------------------------------------
#  2. TELEGRAM MESSAGE PARSING REGEX
# -----------------------------------------------------------------------------
# These regex patterns are designed to extract information from the messages.
# Adjust them if your signal provider changes their message format.

# Bullish Entry Examples:
# "TRB: Entry @ $50.7240, Size: 1/5"
# "LONG ETH: Entry @ $2562.4300, Size: 5/5"
BULLISH_ENTRY_PATTERN = re.compile(
    r"(?:LONG\s+)?(?P<symbol>[A-Z0-9]+):\s+Entry @ \$(?P<entry_price>\d+\.?\d*),\s+Size:\s+(?P<size_numerator>\d+)/(?P<size_denominator>\d+)"
)

# Bearish Entry Examples:
# "SHORT WIF: Entry @ $0.5, Size: 3/5"
# "BCHBEAR: Entry @ $150, Size: 2/5" (assuming 'BEAR' suffix implies bearish)
BEARISH_ENTRY_PATTERN = re.compile(
    r"(?:(?:SHORT|SELL)\s+)?(?P<symbol>[A-Z0-9]+(?:BEAR)?):\s+Entry @ \$(?P<entry_price>\d+\.?\d*),\s+Size:\s+(?P<size_numerator>\d+)/(?P<size_denominator>\d+)"
)

# Exit Signal Examples: (Requires explicit "Long" or "Short" for safety)
# "Close TRB Long"
# "Exit BTC Short Position"
# "Exit AAVE Long"
EXIT_SIGNAL_PATTERN = re.compile(
    r"(?:Exit|Close)\s+(?P<symbol>[A-Z0-9]+)\s+(?P<position_type>(?:Long|Short))(?:\s+position)?"
)

# -----------------------------------------------------------------------------
#  3. TELEGRAM MESSAGE HANDLER
# -----------------------------------------------------------------------------
def handle_telegram_message(update: Update, context: CallbackContext):
    """
    Main handler for incoming Telegram messages.
    Parses messages for trade signals and dispatches to appropriate functions.
    """
    # Ensure message is from the configured channel ID
    if update.effective_chat.id != config.TELEGRAM_CHANNEL_ID:
        logger.warning(
            f"Received message from unauthorized chat ID: {update.effective_chat.id}. "
            f"Expected: {config.TELEGRAM_CHANNEL_ID}. Message: {update.message.text}"
        )
        return

    message_text = update.message.text
    logger.info(f"Received message from channel: {message_text}")

    signal_processed = False # Flag to track if any signal pattern was matched

    # --- Attempt to process Bullish Entry Signals ---
    for match in BULLISH_ENTRY_PATTERN.finditer(message_text):
        signal_processed = True
        symbol = match.group('symbol').strip()
        entry_price = float(match.group('entry_price'))
        size_numerator = int(match.group('size_numerator'))
        size_denominator = int(match.group('size_denominator'))

        # Check if bot already has an OPEN Long position for this symbol in its DB
        # This prevents re-entering the same long trade from duplicate signals or restarts.
        # This check relies on the `monitoring_trading` database.
        if not any(
            t['coin'] == symbol and t['is_long'] == True and t['status'] == 'OPEN'
            for t in trade_db_manager.get_open_trades()
        ):
            logger.info(f"Detected NEW Bullish Signal for {symbol}.")
            handle_bullish_entry_signal(
                symbol, entry_price, size_numerator, size_denominator, account,
                trade_db_manager.add_trade # Callback to add trade to DB
            )
        else:
            logger.info(f"Skipping Bullish Signal for {symbol}: An active Long position for this coin is already being monitored by the bot.")

    # --- Attempt to process Bearish Entry Signals ---
    for match in BEARISH_ENTRY_PATTERN.finditer(message_text):
        signal_processed = True
        symbol = match.group('symbol').strip()
        entry_price = float(match.group('entry_price'))
        size_numerator = int(match.group('size_numerator'))
        size_denominator = int(match.group('size_denominator'))

        # Check if bot already has an OPEN Short position for this symbol in its DB
        if not any(
            t['coin'] == symbol and t['is_long'] == False and t['status'] == 'OPEN'
            for t in trade_db_manager.get_open_trades()
        ):
            logger.info(f"Detected NEW Bearish Signal for {symbol}.")
            handle_bearish_entry_signal(
                symbol, entry_price, size_numerator, size_denominator, account,
                trade_db_manager.add_trade # Callback to add trade to DB
            )
        else:
            logger.info(f"Skipping Bearish Signal for {symbol}: An active Short position for this coin is already being monitored by the bot.")

    # --- Attempt to process Exit Signals ---
    for match in EXIT_SIGNAL_PATTERN.finditer(message_text):
        signal_processed = True
        symbol = match.group('symbol').strip()
        position_type = match.group('position_type').strip() # "Long" or "Short"

        logger.info(f"Detected Exit Signal for {symbol} ({position_type}). Attempting to close position.")
        handle_telegram_exit_signal(
            symbol, position_type, account,
            trade_db_manager.find_and_update_trade_by_coin_and_type # Callback to update DB
        )

    if not signal_processed:
        logger.info("No recognized trading signal found in the message.")

# -----------------------------------------------------------------------------
#  4. MAIN BOT EXECUTION LOGIC
# -----------------------------------------------------------------------------
def main():
    """Starts the Telegram bot and the trade monitoring service."""
    logger.info("Starting Telegram Listener Bot...")

    # Initialize the Telegram Updater and Dispatcher
    # For long-running bots, it's generally recommended to run the polling
    # in a separate thread/process provided by Updater.
    updater = Updater(config.TELEGRAM_BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Register the message handler: processes all text messages that are not commands
    dispatcher.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_telegram_message))

    # Start the continuous trade monitoring in a separate thread
    trade_monitor.start_monitoring()

    # Start the Telegram Bot's polling loop
    updater.start_polling()
    logger.info("Telegram Bot polling started. Waiting for messages...")

    # Keep the main thread alive until Ctrl+C is pressed or a stop signal is received
    try:
        updater.idle() # Blocks until the bot is stopped
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt detected. Shutting down bot gracefully.")
    finally:
        # Graceful shutdown:
        trade_monitor.stop_monitoring() # Stop the trade monitoring thread
        updater.stop() # Stop the Telegram bot's polling
        logger.info("Telegram Listener Bot and Trade Monitor stopped.")

if __name__ == '__main__':
    main()

