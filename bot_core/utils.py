# config.py - Centralized Configuration with .env file loading
import os
import logging
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

# --- Hyperliquid API Configuration ---
HYPERLIQUID_SECRET_KEY = os.getenv("HYPERLIQUID_SECRET_KEY")
if not HYPERLIQUID_SECRET_KEY or HYPERLIQUID_SECRET_KEY.startswith("0x..."):
    logging.warning("HYPERLIQUID_SECRET_KEY not properly set in .env file!")

# --- Telegram Bot Configuration ---
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
if not TELEGRAM_BOT_TOKEN or "your_bot_token" in TELEGRAM_BOT_TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN not properly set in .env file!")
    raise ValueError("TELEGRAM_BOT_TOKEN is required and must be a real token")

# Parse TELEGRAM_CHANNEL_ID safely
try:
    TELEGRAM_CHANNEL_ID = int(os.getenv("TELEGRAM_CHANNEL_ID", "0"))
    if TELEGRAM_CHANNEL_ID == 0:
        logging.error("TELEGRAM_CHANNEL_ID not set in .env file!")
        raise ValueError("TELEGRAM_CHANNEL_ID is required")
except ValueError as e:
    logging.error(f"TELEGRAM_CHANNEL_ID must be a valid integer: {e}")
    raise

# --- Telegram API Configuration (for forwarder - optional for now) ---
try:
    telegram_api_id_str = os.getenv("TELEGRAM_API_ID", "0")
    if telegram_api_id_str and not telegram_api_id_str.startswith("your_api"):
        TELEGRAM_API_ID = int(telegram_api_id_str)
    else:
        TELEGRAM_API_ID = None
        logging.info("TELEGRAM_API_ID not set - forwarder features disabled")
except ValueError:
    TELEGRAM_API_ID = None
    logging.warning("TELEGRAM_API_ID has invalid format - forwarder features disabled")

TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
if TELEGRAM_API_HASH.startswith("your_api_hash"):
    TELEGRAM_API_HASH = None
    logging.info("TELEGRAM_API_HASH not set - forwarder features disabled")

TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")
if TELEGRAM_PHONE.startswith("+1234567890"):
    TELEGRAM_PHONE = None
    logging.info("TELEGRAM_PHONE not set - forwarder features disabled")

# --- Trading Strategy Parameters ---
FUNDING_PER_1_5_UNIT = float(os.getenv("FUNDING_PER_1_5_UNIT", "100"))
MAX_ENTRY_SLIPPAGE_PERCENT = float(os.getenv("MAX_ENTRY_SLIPPAGE_PERCENT", "0.5"))
DEFAULT_TRAILING_STOP_PERCENT = float(os.getenv("DEFAULT_TRAILING_STOP_PERCENT", "5.0"))
DEFAULT_PROFIT_TAKE_PERCENT = float(os.getenv("DEFAULT_PROFIT_TAKE_PERCENT", "10.0"))
DEFAULT_MAX_LOSS_PERCENT = float(os.getenv("DEFAULT_MAX_LOSS_PERCENT", "-5.0"))

# --- API Configuration ---
USE_TESTNET = os.getenv("USE_TESTNET", "true").lower() == "true"

logging.info(f"Configuration loaded from .env file. Using {'TESTNET' if USE_TESTNET else 'MAINNET'}")