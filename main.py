# main.py

import logging
import config # Import your config file
from bot_core.telegram_interface import start_telegram_bot_polling, handle_telegram_message # A function to start polling
from bot_core.trade_persistence import trade_monitor # Assuming trade_monitor is exposed or a method to start it
from telegram.ext import Updater, MessageHandler, filters # Necessary for main.py to set up handlers

# Setup basic logging for main.py
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    logger.info("Initializing bot services...")

    # Initialize Telegram Updater and Dispatcher
    updater = Updater(config.TELEGRAM_BOT_TOKEN, use_context=True)
    dispatcher = updater.dispatcher

    # Register the message handler with the specific interface function
    dispatcher.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_telegram_message))

    # Start the trade monitoring service
    trade_monitor.start_monitoring() # Assuming trade_monitor is an imported instance

    # Start the Telegram bot's polling loop
    updater.start_polling()
    logger.info("Bot fully operational. Waiting for Telegram messages...")

    # Keep the main thread alive until Ctrl+C is pressed
    try:
        updater.idle()
    except KeyboardInterrupt:
        logger.info("KeyboardInterrupt detected. Shutting down bot gracefully.")
    finally:
        # Graceful shutdown process
        trade_monitor.stop_monitoring()
        updater.stop()
        logger.info("All bot services stopped. Exiting.")

if __name__ == '__main__':
    main()
