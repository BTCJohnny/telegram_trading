# config.py - Updated with forwarder support and prominent testnet configuration
import os
import logging
from dotenv import load_dotenv

load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# ═══════════════════════════════════════════════════════════════════════════════
# 🚨 CRITICAL: TESTNET/MAINNET CONFIGURATION 🚨
# ═══════════════════════════════════════════════════════════════════════════════
# This setting determines whether the bot trades on testnet (safe) or mainnet (real money)
# 
# SET IN YOUR .env FILE:
#   USE_TESTNET=true   ← For safe testing (RECOMMENDED)
#   USE_TESTNET=false  ← For live trading with real money (BE CAREFUL!)
#
USE_TESTNET = os.getenv("USE_TESTNET", "true").lower() == "true"

# Safety validation
if USE_TESTNET:
    logging.info("🟢 TESTNET MODE: Safe for testing - no real money at risk")
else:
    logging.warning("🔴 MAINNET MODE: LIVE TRADING - REAL MONEY AT RISK!")
    logging.warning("🔴 Make sure this is intentional!")

# ═══════════════════════════════════════════════════════════════════════════════

# --- Hyperliquid API Configuration ---
HYPERLIQUID_SECRET_KEY = os.getenv("HYPERLIQUID_SECRET_KEY")
if not HYPERLIQUID_SECRET_KEY:
    raise ValueError("HYPERLIQUID_SECRET_KEY is required")

# --- Trading Bot Configuration (YOUR channel) ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID", "0"))  # Your private channel

# Validation for required Telegram settings
if not TELEGRAM_BOT_TOKEN:
    raise ValueError("TELEGRAM_BOT_TOKEN is required")
if TELEGRAM_CHANNEL_ID == 0:
    raise ValueError("TELEGRAM_CHANNEL_ID is required")

# --- Forwarder Configuration (Optional) ---
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")

# --- Trading Strategy Parameters ---
FUNDING_PER_1_5_UNIT = float(os.getenv("FUNDING_PER_1_5_UNIT", "100"))
MAX_ENTRY_SLIPPAGE_PERCENT = float(os.getenv("MAX_ENTRY_SLIPPAGE_PERCENT", "0.5"))
DEFAULT_TRAILING_STOP_PERCENT = float(os.getenv("DEFAULT_TRAILING_STOP_PERCENT", "5.0"))
DEFAULT_PROFIT_TAKE_PERCENT = float(os.getenv("DEFAULT_PROFIT_TAKE_PERCENT", "10.0"))
DEFAULT_MAX_LOSS_PERCENT = float(os.getenv("DEFAULT_MAX_LOSS_PERCENT", "-5.0"))

# --- Configuration Summary ---
logging.info("=" * 60)
logging.info("🔧 TRADING BOT CONFIGURATION LOADED")
logging.info("=" * 60)
logging.info(f"🌐 Network: {'🟢 TESTNET' if USE_TESTNET else '🔴 MAINNET'}")
logging.info(f"💰 Funding per 1/5 unit: ${FUNDING_PER_1_5_UNIT}")
logging.info(f"📊 Max slippage: {MAX_ENTRY_SLIPPAGE_PERCENT}%")
logging.info(f"🎯 Default profit target: {DEFAULT_PROFIT_TAKE_PERCENT}%")
logging.info(f"🛑 Default max loss: {DEFAULT_MAX_LOSS_PERCENT}%")
logging.info(f"📱 Telegram channel: {TELEGRAM_CHANNEL_ID}")
logging.info("=" * 60)

# Export the USE_TESTNET for easy access by other modules
__all__ = [
    'USE_TESTNET',
    'HYPERLIQUID_SECRET_KEY',
    'TELEGRAM_BOT_TOKEN', 
    'TELEGRAM_CHANNEL_ID',
    'FUNDING_PER_1_5_UNIT',
    'MAX_ENTRY_SLIPPAGE_PERCENT',
    'DEFAULT_TRAILING_STOP_PERCENT',
    'DEFAULT_PROFIT_TAKE_PERCENT',
    'DEFAULT_MAX_LOSS_PERCENT'
]