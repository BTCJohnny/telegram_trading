# monitoring_trading.py --> trade_persistence.py

import sqlite3
import time
import logging
import threading
from datetime import datetime

# Assuming hyperliquid_bot.py is in the same directory and contains the necessary functions
from hyperliquid_bot import (
    acct_bal,
    get_position,
    ask_bid,
    pnl_close, # We will use its internal logic but control flow here
    kill_switch,
    LocalAccount
)

# Assuming additional_functions.py is in the same directory for calculate_trailing_stop_price
from additional_functions import (
    calculate_trailing_stop_price,
    DEFAULT_TRAILING_STOP_PERCENT,
    DEFAULT_PROFIT_TAKE_PERCENT,
    DEFAULT_MAX_LOSS_PERCENT
)

# You will need to import your configuration (do_not_share.py)
try:
    import do_not_share as config
except ImportError:
    logging.error("do_not_share.py not found. Please create it with your API keys and config.")
    # Exit or handle gracefully
    exit()

logger = logging.getLogger(__name__)

# --- Database Configuration ---
DB_NAME = "bot_trades.db"

# --- Monitoring Loop Configuration ---
MONITORING_INTERVAL_SECONDS = 60 # Check every 60 seconds (adjust as needed)

class TradeMonitorDB:
    """
    Manages the SQLite database for persistently storing and tracking bot-managed trades.
    """
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initializes the SQLite database and creates the 'monitored_trades' table."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monitored_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coin TEXT NOT NULL,
                is_long BOOLEAN NOT NULL,
                entry_sz REAL NOT NULL, -- Size (quantity) of the asset
                entry_px REAL NOT NULL, -- Actual entry price
                initial_pnl_target REAL, -- User-defined take profit target (e.g., 10.0 for 10%)
                initial_pnl_max_loss REAL, -- User-defined stop loss target (e.g., -5.0 for -5%)
                current_pnl REAL, -- Current PnL % from API
                current_price REAL, -- Current market price
                entry_timestamp TEXT NOT NULL,
                status TEXT NOT NULL, -- OPEN, CLOSED_PROFIT, CLOSED_LOSS, CLOSED_MANUAL, PENDING_ENTRY
                exit_timestamp TEXT,
                final_pnl REAL,
                # Fields for Trailing Stop
                highest_price REAL,  -- For long positions, tracks the peak price since entry
                lowest_price REAL,   -- For short positions, tracks the trough price since entry
                calculated_stop_px REAL -- The current calculated trailing stop price
            )
        ''')
        conn.commit()
        conn.close()
        logger.info(f"Database '{self.db_path}' initialized/checked.")

    def _get_db_connection(self):
        """Returns a database connection."""
        return sqlite3.connect(self.db_path)

    def add_trade(
        self, coin: str, is_long: bool, entry_sz: float, entry_px: float,
        initial_pnl_target: float, initial_pnl_max_loss: float
    ) -> int:
        """Adds a new trade to the database for monitoring."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        entry_timestamp = datetime.now().isoformat()
        status = "OPEN" # Assuming order creation means it's ready to monitor for fill/position

        # Initialize highest/lowest price for trailing stop based on entry price
        highest_price = entry_px if is_long else None
        lowest_price = entry_px if not is_long else None

        cursor.execute(f'''
            INSERT INTO monitored_trades (
                coin, is_long, entry_sz, entry_px, initial_pnl_target, initial_pnl_max_loss,
                entry_timestamp, status, highest_price, lowest_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (coin, is_long, entry_sz, entry_px, initial_pnl_target, initial_pnl_max_loss,
              entry_timestamp, status, highest_price, lowest_price))
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info(f"Trade added to DB: ID={trade_id} {coin} {'LONG' if is_long else 'SHORT'} @ {entry_px:.4f}")
        return trade_id

    def get_open_trades(self) -> list[dict]:
        """Retrieves all open trades from the database represented as dictionaries."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM monitored_trades WHERE status = 'OPEN'")
        # Get column names for dictionary conversion
        rows = cursor.fetchall()
        cols = [description[0] for description in cursor.description]
        trades = []
        for row in rows:
            trade = {col: row[idx] for idx, col in enumerate(cols)}
            # Convert boolean from int (SQLite stores booleans as 0 or 1)
            trade['is_long'] = bool(trade['is_long'])
            trades.append(trade)
        conn.close()
        return trades

    def update_trade_monitoring_data(
        self, trade_id: int, current_pnl: float, current_price: float,
        highest_price: float, lowest_price: float, calculated_stop_px: float
    ):
        """Updates monitoring data (PnL, prices, calculated stop) for an open trade."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE monitored_trades
            SET current_pnl = ?, current_price = ?,
                highest_price = ?, lowest_price = ?, calculated_stop_px = ?
            WHERE id = ?
        ''', (current_pnl, current_price, highest_price, lowest_price, calculated_stop_px, trade_id))
        conn.commit()
        conn.close()

    def update_trade_status(self, trade_id: int, new_status: str, final_pnl: float = None):
        """Updates the status of a trade (e.g., to CLOSED_PROFIT, CLOSED_LOSS, CLOSED_MANUAL)
        and records final PnL and exit timestamp."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        exit_timestamp = datetime.now().isoformat()
        cursor.execute('''
            UPDATE monitored_trades
            SET status = ?, exit_timestamp = ?, final_pnl = ?
            WHERE id = ?
        ''', (new_status, exit_timestamp, final_pnl, trade_id))
        conn.commit()
        conn.close()
        logger.info(f"Trade ID {trade_id} status updated to {new_status} with Final PnL: {final_pnl:.2f}%")

    def find_and_update_trade_by_coin_and_type(self, coin: str, position_type_str: str, final_pnl: float):
        """
        Attempts to find an OPEN trade by coin and type (Long/Short) and update its status to CLOSED_MANUAL.
        Used for Telegram-triggered exits.
        """
        conn = self._get_db_connection()
        cursor = conn.cursor()
        is_long_expected = (position_type_str.lower() == "long")
        # Find an open trade matching coin and expected long/short
        cursor.execute('''
            SELECT id FROM monitored_trades
            WHERE coin = ? AND is_long = ? AND status = 'OPEN'
            ORDER BY entry_timestamp DESC LIMIT 1
        ''', (coin, is_long_expected))
        result = cursor.fetchone()
        conn.close()

        if result:
            trade_id = result[0]
            self.update_trade_status(trade_id, "CLOSED_MANUAL", final_pnl)
            logger.info(f"Manually closed trade ID {trade_id} for {coin} ({position_type_str}) in DB.")
            return True
        else:
            logger.warning(f"Could not find an OPEN trade for {coin} ({position_type_str}) in DB for manual closure.")
            return False


class TradeMonitor:
    """
    Manages the continuous monitoring loop for open trades, performing PnL checks
    and triggering closures based on defined criteria.
    """
    def __init__(self, account: LocalAccount, db_manager: TradeMonitorDB):
        self.account = account
        self.db_manager = db_manager
        self._running = False
        self._monitor_thread = None

    def _monitor_loop(self):
        """The main loop for continuously monitoring open trades."""
        logger.info("Starting trade monitoring loop...")
        while self._running:
            try:
                open_trades = self.db_manager.get_open_trades()
                if not open_trades:
                    logger.info("No open trades to monitor. Sleeping...")
                
                for trade in open_trades:
                    coin = trade['coin']
                    trade_id = trade['id']
                    
                    # 1. Get current Hyperliquid position details
                    # If position data indicates a position of 0 sz, it means it's closed on HL
                    _, is_in_hyperliquid_position, actual_sz, pos_sym, _, pnl_perc, is_long_on_hl = get_position(coin, self.account)

                    if not is_in_hyperliquid_position or abs(actual_sz) < 1e-9: # Check for near zero size
                        logger.warning(f"Trade ID {trade_id} for {coin} is OPEN in DB but no active position found on Hyperliquid (sz={actual_sz}). Setting to CLOSED_MANUAL.")
                        self.db_manager.update_trade_status(trade_id, "CLOSED_MANUAL", pnl_perc)
                        continue # Skip to next trade as it's already closed

                    # Ensure the DB's `is_long` matches the actual Hyperliquid position
                    if trade['is_long'] != is_long_on_hl:
                        logger.error(f"DB mismatch for trade ID {trade_id} on {coin}: DB says {'Long' if trade['is_long'] else 'Short'}, HL says {'Long' if is_long_on_hl else 'Short'}. Please investigate and manually correct DB/position.")
                        continue # Skip this trade to prevent erroneous actions

                    # 2. Get current market price for calculations
                    current_ask, current_bid, _ = ask_bid(coin)
                    if current_ask == 0.0 or current_bid == 0.0:
                        logger.warning(f"Could not get current market prices for {coin}. Skipping PnL/stop checks for this cycle.")
                        continue

                    current_market_price = current_bid if is_long_on_hl else current_ask # Bid for long exit, Ask for short exit


                    # 3. Update highest/lowest price for trailing stop for this trade in DB
                    highest_price = trade['highest_price'] if trade['highest_price'] is not None else current_market_price
                    lowest_price = trade['lowest_price'] if trade['lowest_price'] is not None else current_market_price

                    if is_long_on_hl:
                        highest_price = max(highest_price, current_market_price)
                    else: # Short position
                        lowest_price = min(lowest_price, current_market_price)
                    
                    # 4. Calculate Trailing Stop Price
                    calculated_stop_px = calculate_trailing_stop_price(
                        coin, trade['entry_px'], is_long_on_hl, current_market_price,
                        highest_price, lowest_price, # Pass updated highest/lowest
                        DEFAULT_MAX_LOSS_PERCENT * -1, # Pass positive initial stop %
                        DEFAULT_TRAILING_STOP_PERCENT
                    )
                    
                    # 5. Check PnL Conditions & Execute Close
                    # Prioritize: 1. Fixed Take Profit, 2. Fixed Max Loss, 3. Trailing Stop Loss
                    
                    # Check fixed Take Profit
                    if pnl_perc >= trade['initial_pnl_target']:
                        logger.info(f"TAKE PROFIT for {coin} (ID: {trade_id})! PnL: {pnl_perc:.2f}% (Target: {trade['initial_pnl_target']}%)")
                        self.close_trade_and_update_db(trade_id, coin, "CLOSED_PROFIT", pnl_perc)
                        continue # Move to next trade after closing

                    # Check fixed Max Loss
                    if pnl_perc <= trade['initial_pnl_max_loss']:
                        logger.warning(f"FIXED STOP LOSS HIT for {coin} (ID: {trade_id})! PnL: {pnl_perc:.2f}% (Max Loss: {trade['initial_pnl_max_loss']}%)")
                        self.close_trade_and_update_db(trade_id, coin, "CLOSED_LOSS", pnl_perc)
                        continue # Move to next trade after closing

                    # Check Trailing Stop Loss
                    # For long: if current_market_price drops below the calculated_stop_px
                    # For short: if current_market_price rises above the calculated_stop_px
                    is_trailing_stop_hit = False
                    if is_long_on_hl and current_market_price <= calculated_stop_px:
                        is_trailing_stop_hit = True
                    elif not is_long_on_hl and current_market_price >= calculated_stop_px:
                        is_trailing_stop_hit = True

                    if is_trailing_stop_hit:
                        logger.warning(f"TRAILING STOP LOSS HIT for {coin} (ID: {trade_id})! Price: {current_market_price:.4f}, Stop: {calculated_stop_px:.4f}")
                        self.close_trade_and_update_db(trade_id, coin, "CLOSED_LOSS", pnl_perc)
                        continue # Move to next trade after closing
                    
                    # If not closed, update monitoring data in DB
                    self.db_manager.update_trade_monitoring_data(
                        trade_id, pnl_perc, current_market_price, highest_price, lowest_price, calculated_stop_px
                    )
                    logger.info(f"Monitoring {coin} (ID: {trade_id}): PnL={pnl_perc:.2f}%, CurrPx=${current_market_price:.4f}, Calculated SLPx=${calculated_stop_px:.4f}")

            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)
            finally:
                time.sleep(MONITORING_INTERVAL_SECONDS) # Always sleep to avoid hammering API

    def close_trade_and_update_db(self, trade_id: int, coin: str, status: str, final_pnl: float):
        """Safely closes a trade via kill_switch and updates its status in the database."""
        try:
            logger.info(f"Attempting to close trade {coin} (ID: {trade_id}) via kill_switch...")
            kill_switch(coin, self.account) # This function already logs its actions
            self.db_manager.update_trade_status(trade_id, status, final_pnl)
            logger.info(f"Trade {coin} (ID: {trade_id}) successfully closed and DB updated to {status}.")
        except Exception as e:
            logger.error(f"Critical error during kill_switch or DB update for trade {coin} (ID: {trade_id}): {e}", exc_info=True)
            # If kill_switch failed, don't update DB status immediately so it's retried on next loop.
            # You might want to add a retry mechanism here for kill_switch itself.

    def start_monitoring(self):
        """Starts the trade monitoring thread."""
        if not self._running:
            self._running = True
            logger.info("Starting trade monitoring thread...")
            self._monitor_thread = threading.Thread(target=self._monitor_loop)
            self._monitor_thread.daemon = True # Allows main program to exit even if thread is running
            self._monitor_thread.start()
        else:
            logger.info("Trade monitoring already running.")

    def stop_monitoring(self):
        """Stops the trade monitoring thread gracefully."""
        if self._running:
            self._running = False
            logger.info("Attempting to stop trade monitoring thread...")
            if self._monitor_thread and self._monitor_thread.is_alive():
                # Give the thread a chance to finish its current cycle
                self._monitor_thread.join(timeout=MONITORING_INTERVAL_SECONDS + 5)
                if self._monitor_thread.is_alive():
                    logger.warning("Monitoring thread did not stop gracefully within timeout.")
            logger.info("Trade monitoring stopped.")


# --- Example Usage (for testing monitoring_trading.py independently) ---
if __name__ == '__main__':
    # Initialize logging for standalone run
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

    # Re-initialize Hyperliquid account (similar to hyperliquid_bot.py start)
    _account = None
    if config.HYPERLIQUID_SECRET_KEY:
        try:
            _account = LocalAccount.from_private_key(config.HYPERLIQUID_SECRET_KEY)
            logger.info(f"Hyperliquid account initialized for trade monitoring: {_account.address}")
        except Exception as e:
            logger.error(f"Failed to initialize Hyperliquid account for monitoring: {e}")
            exit("Account initialization failed.")
    else:
        logger.error("HYPERLIQUID_SECRET_KEY not found in do_not_share.py or environment. Cannot run monitor.")
        exit("SECRET_KEY not found.")

    db_manager = TradeMonitorDB(DB_NAME)
    monitor = TradeMonitor(_account, db_manager)

    # --- Test adding a dummy trade
    # Note: For actual usage, trades are added by `telegram_listener.py`
    # after a successful order placement.
    logger.info("Checking for existing WIF position to monitor...")
    _, is_in_pos, size, _, entry_px, _, is_long = get_position("WIF", _account) # Check for WIF example
    
    if is_in_pos:
        logger.info(f"Found active WIF position on Hyperliquid: Size={size}, Entry={entry_px}, Long={is_long}.")
        # Check if it's already being monitored
        open_trades_in_db = db_manager.get_open_trades()
        if not any(t['coin'] == "WIF" and t['is_long'] == is_long and t['status'] == 'OPEN' for t in open_trades_in_db):
            logger.info("WIF position found on Hyperliquid but not in DB, adding for monitoring.")
            db_manager.add_trade("WIF", is_long, abs(size), entry_px, DEFAULT_PROFIT_TAKE_PERCENT, DEFAULT_MAX_LOSS_PERCENT)
        else:
            logger.info("WIF position already in DB for monitoring.")
    else:
        logger.info("No active WIF position found on Hyperliquid. To test monitoring, please open a position manually or via a signal.")
        # Example of how you would *add* a trade from a signal if you were telegram_listener.py
        # db_manager.add_trade("WIF", True, 0.1, 1.50, 10.0, -5.0) # Dummy Long 0.1 WIF @ $1.50

    monitor.start_monitoring()

    # Keep the main thread alive to let the monitoring thread run
    try:
        logger.info("Monitoring thread running. Press Ctrl+C to stop.")
        while True:
            time.sleep(1) # Main thread just sleeps, monitoring thread runs concurrently
    except KeyboardInterrupt:
        logger.info("Main thread interrupted. Stopping monitoring...")
        monitor.stop_monitoring()
        logger.info("Monitoring stopped. Exiting.")

