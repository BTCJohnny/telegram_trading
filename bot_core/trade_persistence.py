# bot_core/trade_persistence.py - Enhanced Database with Portfolio Tracking

import sqlite3
import time
import logging
import threading
import re
from datetime import datetime, date

from .hyperliquid_api import get_position, ask_bid, kill_switch, account
from .utils import setup_module_logger
import config

logger = setup_module_logger(__name__)

# Database configuration
DB_NAME = "bot_trades.db"
MONITORING_INTERVAL_SECONDS = 60

class TradeMonitorDB:
    """Enhanced database manager with portfolio tracking."""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """Initialize database with enhanced schema."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        # Existing trades table (enhanced)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS monitored_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                coin TEXT NOT NULL,
                is_long BOOLEAN NOT NULL,
                entry_sz REAL NOT NULL,
                entry_px REAL NOT NULL,
                initial_pnl_target REAL,
                initial_pnl_max_loss REAL,
                current_pnl REAL DEFAULT 0,
                current_price REAL DEFAULT 0,
                entry_timestamp TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'OPEN',
                exit_timestamp TEXT,
                final_pnl REAL,
                highest_price REAL,
                lowest_price REAL,
                calculated_stop_px REAL DEFAULT 0,
                signal_source TEXT DEFAULT 'telegram',
                original_entry_date TEXT,
                size_confidence TEXT
            )
        ''')
        
        # Portfolio snapshots table (daily portfolio data)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_date TEXT NOT NULL,
                portfolio_type TEXT NOT NULL,
                total_positions INTEGER,
                created_timestamp TEXT NOT NULL,
                UNIQUE(snapshot_date, portfolio_type)
            )
        ''')
        
        # Portfolio positions table (individual positions from snapshots)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS portfolio_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                snapshot_id INTEGER,
                coin TEXT NOT NULL,
                portfolio_type TEXT NOT NULL,
                entry_date TEXT NOT NULL,
                entry_price REAL NOT NULL,
                current_price REAL NOT NULL,
                pnl_percentage REAL NOT NULL,
                size_confidence TEXT NOT NULL,
                snapshot_date TEXT NOT NULL,
                created_timestamp TEXT NOT NULL,
                FOREIGN KEY(snapshot_id) REFERENCES portfolio_snapshots(id)
            )
        ''')
        
        # Signal history table (all processed signals)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS signal_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                signal_type TEXT NOT NULL,
                coin TEXT NOT NULL,
                direction TEXT NOT NULL,
                entry_price REAL,
                exit_price REAL,
                size_confidence TEXT,
                return_percentage REAL,
                signal_date TEXT NOT NULL,
                processed_timestamp TEXT NOT NULL,
                executed BOOLEAN DEFAULT 0,
                trade_id INTEGER,
                FOREIGN KEY(trade_id) REFERENCES monitored_trades(id)
            )
        ''')
        
        conn.commit()
        conn.close()
        logger.info(f"Enhanced database '{self.db_path}' initialized.")

    def _get_db_connection(self):
        """Returns a database connection."""
        return sqlite3.connect(self.db_path)

    # Existing trade methods (keeping existing functionality)
    def add_trade(self, coin: str, is_long: bool, entry_sz: float, entry_px: float,
                  initial_pnl_target: float, initial_pnl_max_loss: float, 
                  size_confidence: str = None, original_entry_date: str = None) -> int:
        """Add a trade with enhanced tracking."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        entry_timestamp = datetime.now().isoformat()
        
        highest_price = entry_px if is_long else None
        lowest_price = entry_px if not is_long else None

        cursor.execute('''
            INSERT INTO monitored_trades (
                coin, is_long, entry_sz, entry_px, initial_pnl_target, 
                initial_pnl_max_loss, entry_timestamp, status, 
                highest_price, lowest_price, size_confidence, original_entry_date
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (coin, is_long, entry_sz, entry_px, initial_pnl_target, 
              initial_pnl_max_loss, entry_timestamp, 'OPEN', 
              highest_price, lowest_price, size_confidence, original_entry_date))
        
        trade_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Trade added: ID={trade_id} {coin} {'LONG' if is_long else 'SHORT'} @ {entry_px:.4f} Size:{size_confidence}")
        return trade_id

    # Portfolio tracking methods (NEW)
    def add_portfolio_snapshot(self, snapshot_date: str, portfolio_type: str, positions: list) -> int:
        """Add a complete portfolio snapshot."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        created_timestamp = datetime.now().isoformat()
        
        try:
            # Insert or update snapshot
            cursor.execute('''
                INSERT OR REPLACE INTO portfolio_snapshots 
                (snapshot_date, portfolio_type, total_positions, created_timestamp)
                VALUES (?, ?, ?, ?)
            ''', (snapshot_date, portfolio_type, len(positions), created_timestamp))
            
            snapshot_id = cursor.lastrowid
            
            # Delete existing positions for this snapshot
            cursor.execute('''
                DELETE FROM portfolio_positions 
                WHERE snapshot_date = ? AND portfolio_type = ?
            ''', (snapshot_date, portfolio_type))
            
            # Insert all positions
            for position in positions:
                cursor.execute('''
                    INSERT INTO portfolio_positions (
                        snapshot_id, coin, portfolio_type, entry_date, entry_price,
                        current_price, pnl_percentage, size_confidence, 
                        snapshot_date, created_timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (snapshot_id, position['coin'], portfolio_type, position['entry_date'],
                      position['entry_price'], position['current_price'], position['pnl_percentage'],
                      position['size_confidence'], snapshot_date, created_timestamp))
            
            conn.commit()
            logger.info(f"Portfolio snapshot added: {portfolio_type} on {snapshot_date} with {len(positions)} positions")
            return snapshot_id
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error adding portfolio snapshot: {e}")
            return 0
        finally:
            conn.close()

    def add_signal_record(self, signal_type: str, coin: str, direction: str, 
                         entry_price: float = None, exit_price: float = None,
                         size_confidence: str = None, return_percentage: float = None,
                         executed: bool = False, trade_id: int = None) -> int:
        """Record a processed signal."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        signal_date = date.today().isoformat()
        processed_timestamp = datetime.now().isoformat()
        
        cursor.execute('''
            INSERT INTO signal_history (
                signal_type, coin, direction, entry_price, exit_price,
                size_confidence, return_percentage, signal_date, 
                processed_timestamp, executed, trade_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (signal_type, coin, direction, entry_price, exit_price,
              size_confidence, return_percentage, signal_date,
              processed_timestamp, executed, trade_id))
        
        signal_id = cursor.lastrowid
        conn.commit()
        conn.close()
        
        logger.info(f"Signal recorded: {signal_type} {direction} {coin} - Executed: {executed}")
        return signal_id

    def get_latest_portfolio(self, portfolio_type: str) -> list:
        """Get the most recent portfolio snapshot."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM portfolio_positions 
            WHERE portfolio_type = ? 
            ORDER BY snapshot_date DESC, created_timestamp DESC
            LIMIT 20
        ''', (portfolio_type,))
        
        rows = cursor.fetchall()
        cols = [description[0] for description in cursor.description]
        positions = []
        
        for row in rows:
            position = {col: row[idx] for idx, col in enumerate(cols)}
            positions.append(position)
        
        conn.close()
        return positions

    def get_portfolio_history(self, coin: str, portfolio_type: str) -> list:
        """Get historical portfolio data for a specific coin."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute('''
            SELECT * FROM portfolio_positions 
            WHERE coin = ? AND portfolio_type = ?
            ORDER BY snapshot_date DESC
        ''', (coin, portfolio_type))
        
        rows = cursor.fetchall()
        cols = [description[0] for description in cursor.description]
        history = []
        
        for row in rows:
            record = {col: row[idx] for idx, col in enumerate(cols)}
            history.append(record)
        
        conn.close()
        return history

    # Keep existing methods for backward compatibility
    def get_open_trades(self) -> list[dict]:
        """Get all open trades."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM monitored_trades WHERE status = 'OPEN'")
        
        rows = cursor.fetchall()
        cols = [description[0] for description in cursor.description]
        trades = []
        
        for row in rows:
            trade = {col: row[idx] for idx, col in enumerate(cols)}
            trade['is_long'] = bool(trade['is_long'])
            trades.append(trade)
        
        conn.close()
        return trades

    def update_trade_monitoring_data(self, trade_id: int, current_pnl: float, 
                                   current_price: float, highest_price: float, 
                                   lowest_price: float, calculated_stop_px: float):
        """Update monitoring data for a trade."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            UPDATE monitored_trades
            SET current_pnl = ?, current_price = ?, highest_price = ?, 
                lowest_price = ?, calculated_stop_px = ?
            WHERE id = ?
        ''', (current_pnl, current_price, highest_price, lowest_price, 
              calculated_stop_px, trade_id))
        conn.commit()
        conn.close()

    def update_trade_status(self, trade_id: int, new_status: str, final_pnl: float = None):
        """Update trade status when closed."""
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
        """Find and update trade status for manual exits."""
        conn = self._get_db_connection()
        cursor = conn.cursor()
        is_long_expected = (position_type_str.lower() == "long")
        
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
            logger.info(f"Manually closed trade ID {trade_id} for {coin} ({position_type_str})")
            return True
        else:
            logger.warning(f"Could not find OPEN trade for {coin} ({position_type_str})")
            return False


# Portfolio parsing helper functions
def parse_portfolio_position(position_text: str) -> dict:
    """Parse individual portfolio position from message text."""
    # Example: "  **ADA (B):**\n    - Entry Date: 2025-05-06\n    - Entry Price: $0.6785\n..."
    
    lines = position_text.strip().split('\n')
    if not lines:
        return None
    
    # Extract coin symbol
    coin_match = re.search(r'\*\*([A-Z0-9]+) \([B]\):\*\*', lines[0])
    if not coin_match:
        return None
    
    coin = coin_match.group(1)
    position_data = {'coin': coin}
    
    # Parse details from subsequent lines
    for line in lines[1:]:
        line = line.strip()
        
        if '- Entry Date:' in line:
            date_match = re.search(r'Entry Date: (\d{4}-\d{2}-\d{2})', line)
            if date_match:
                position_data['entry_date'] = date_match.group(1)
        
        elif '- Entry Price:' in line:
            price_match = re.search(r'Entry Price: \$([0-9,.]+)', line)
            if price_match:
                position_data['entry_price'] = float(price_match.group(1).replace(',', ''))
        
        elif '- Current Price:' in line:
            current_match = re.search(r'Current Price: \$([0-9,.]+) \(🟢([0-9.-]+)%\)', line)
            if current_match:
                position_data['current_price'] = float(current_match.group(1).replace(',', ''))
                position_data['pnl_percentage'] = float(current_match.group(2))
        
        elif '- Size:' in line:
            size_match = re.search(r'Size: (\d+/\d+)', line)
            if size_match:
                position_data['size_confidence'] = size_match.group(1)
    
    return position_data if len(position_data) > 1 else None


# Keep existing TradeMonitor class (unchanged)
class TradeMonitor:
    """Manages continuous monitoring of open trades."""
    
    def __init__(self, db_manager: TradeMonitorDB):
        self.db_manager = db_manager
        self._running = False
        self._monitor_thread = None

    def _monitor_loop(self):
        """Main monitoring loop."""
        logger.info("Starting trade monitoring loop...")
        
        while self._running:
            try:
                open_trades = self.db_manager.get_open_trades()
                if not open_trades:
                    logger.info("No open trades to monitor.")
                
                for trade in open_trades:
                    self._monitor_single_trade(trade)
                    
            except Exception as e:
                logger.error(f"Error in monitoring loop: {e}", exc_info=True)
            finally:
                time.sleep(MONITORING_INTERVAL_SECONDS)

    def _monitor_single_trade(self, trade):
        """Monitor a single trade for PnL and stop conditions."""
        coin = trade['coin']
        trade_id = trade['id']
        
        # Get current position from Hyperliquid
        _, is_in_position, actual_sz, pos_sym, _, pnl_perc, is_long_on_hl = get_position(coin)

        # Check if position still exists
        if not is_in_position or abs(actual_sz) < 1e-9:
            logger.warning(f"Trade ID {trade_id} for {coin} is OPEN in DB but no position on Hyperliquid")
            self.db_manager.update_trade_status(trade_id, "CLOSED_MANUAL", pnl_perc)
            return

        # Verify position type matches
        if trade['is_long'] != is_long_on_hl:
            logger.error(f"Position type mismatch for trade ID {trade_id} on {coin}")
            return

        # Get current market price
        current_ask, current_bid, _ = ask_bid(coin)
        if current_ask == 0.0 or current_bid == 0.0:
            logger.warning(f"Could not get market prices for {coin}")
            return

        current_market_price = current_bid if is_long_on_hl else current_ask

        # Update price tracking
        highest_price = trade['highest_price'] or current_market_price
        lowest_price = trade['lowest_price'] or current_market_price

        if is_long_on_hl:
            highest_price = max(highest_price, current_market_price)
        else:
            lowest_price = min(lowest_price, current_market_price)

        # Check exit conditions
        if pnl_perc >= trade['initial_pnl_target']:
            logger.info(f"TAKE PROFIT for {coin} (ID: {trade_id})! PnL: {pnl_perc:.2f}%")
            self._close_trade_and_update_db(trade_id, coin, "CLOSED_PROFIT", pnl_perc)
            return

        if pnl_perc <= trade['initial_pnl_max_loss']:
            logger.warning(f"STOP LOSS for {coin} (ID: {trade_id})! PnL: {pnl_perc:.2f}%")
            self._close_trade_and_update_db(trade_id, coin, "CLOSED_LOSS", pnl_perc)
            return

        # Update monitoring data
        self.db_manager.update_trade_monitoring_data(
            trade_id, pnl_perc, current_market_price, 
            highest_price, lowest_price, 0
        )
        
        logger.info(f"Monitoring {coin} (ID: {trade_id}): PnL={pnl_perc:.2f}%, Price=${current_market_price:.4f}")

    def _close_trade_and_update_db(self, trade_id: int, coin: str, status: str, final_pnl: float):
        """Close trade and update database."""
        try:
            logger.info(f"Closing trade {coin} (ID: {trade_id}) via kill_switch...")
            kill_switch(coin)
            self.db_manager.update_trade_status(trade_id, status, final_pnl)
            logger.info(f"Trade {coin} (ID: {trade_id}) closed successfully")
        except Exception as e:
            logger.error(f"Error closing trade {coin} (ID: {trade_id}): {e}", exc_info=True)

    def start_monitoring(self):
        """Start the monitoring thread."""
        if not self._running:
            self._running = True
            logger.info("Starting trade monitoring thread...")
            self._monitor_thread = threading.Thread(target=self._monitor_loop)
            self._monitor_thread.daemon = True
            self._monitor_thread.start()
        else:
            logger.info("Trade monitoring already running.")

    def stop_monitoring(self):
        """Stop the monitoring thread."""
        if self._running:
            self._running = False
            logger.info("Stopping trade monitoring...")
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_thread.join(timeout=MONITORING_INTERVAL_SECONDS + 5)
            logger.info("Trade monitoring stopped.")