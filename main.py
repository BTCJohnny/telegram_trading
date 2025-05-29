# main.py - Simple Entry Point for Trading Bot

import logging
from telegram.ext import Application, MessageHandler, filters

# Import configuration and core modules
import config
from bot_core.telegram_interface import handle_telegram_message
from bot_core.trade_persistence import TradeMonitorDB, TradeMonitor

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def main():
    """Main function to start the trading bot."""
    logger.info("Starting Hyperliquid Telegram Trading Bot...")
    logger.info(f"Using {'TESTNET' if config.USE_TESTNET else 'MAINNET'}")
    
    # Initialize database and trade monitor
    db_manager = TradeMonitorDB("bot_trades.db")
    trade_monitor = TradeMonitor(db_manager)
    
    # Start trade monitoring in background
    trade_monitor.start_monitoring()
    
    # Setup Telegram bot (new v20+ syntax)
    app = Application.builder().token(config.TELEGRAM_BOT_TOKEN).build()
    
    # Register message handler
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_telegram_message))
    
    # Start the bot
    logger.info("🚀 Bot is now operational! Waiting for messages...")
    
    try:
        await app.run_polling()
    except KeyboardInterrupt:
        logger.info("Shutting down bot...")
        trade_monitor.stop_monitoring()
        logger.info("Bot stopped.")

def test_configuration():
    """Simple configuration test."""
    try:
        logger.info(f"✅ Bot token: {config.TELEGRAM_BOT_TOKEN[:10]}...")
        logger.info(f"✅ Channel ID: {config.TELEGRAM_CHANNEL_ID}")
        logger.info(f"✅ Hyperliquid key: {config.HYPERLIQUID_SECRET_KEY[:10]}...")
        logger.info(f"✅ Using {'TESTNET' if config.USE_TESTNET else 'MAINNET'}")
        logger.info("✅ Configuration looks good!")
        return True
    except Exception as e:
        logger.error(f"❌ Configuration error: {e}")
        return False

def test_database():
    """Simple database test."""
    try:
        db_manager = TradeMonitorDB("test_trades.db")
        logger.info("✅ Database test passed!")
        return True
    except Exception as e:
        logger.error(f"❌ Database error: {e}")
        return False

if __name__ == '__main__':
    import sys
    import asyncio
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "test-config":
            test_configuration()
        elif sys.argv[1] == "test-db":
            test_database()
        elif sys.argv[1] == "test-all":
            if test_configuration() and test_database():
                logger.info("🎉 All tests passed!")
            else:
                logger.error("❌ Some tests failed.")
        else:
            logger.error("Usage: python main.py [test-config|test-db|test-all]")
    else:
        # Run the async main function
        asyncio.run(main())