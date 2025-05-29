# additional_functions.py --> strategy_manager.py

import re
import time
import logging
import math

# Assuming hyperliquid_bot.py is in the same directory and structured as provided
# and `account` is passed or initialized globally.
from hyperliquid_bot import (
    ask_bid,
    limit_order,
    get_position,
    acct_bal,
    kill_switch,
    LocalAccount  # Assuming LocalAccount is exposed or imported from hyperliquid_bot context
)

# You will need to import your configuration (do_not_share.py)
try:
    import do_not_share as config
except ImportError:
    logging.error("do_not_share.py not found. Please create it with your API keys and config.")
    # Exit or handle gracefully if you want bot to still run without trade functions
    exit()

logger = logging.getLogger(__name__)

# --- Re-usable constants (can be moved to config.py for easier tuning) ---
MAX_ENTRY_SLIPPAGE_PERCENT = 0.5 # Max 0.5% deviation from signal price for entry
DEFAULT_TRAILING_STOP_PERCENT = 5.0 # Trailing stop percentage (e.g., 5% below peak for long)
DEFAULT_PROFIT_TAKE_PERCENT = 10.0 # Default profit target for new trades (e.g., 10%)
DEFAULT_MAX_LOSS_PERCENT = -5.0 # Default max loss for new trades (e.g., -5%)

# --- Functions for Enhanced Trading Logic & Strategy ---

def calculate_dynamic_sz(
    account: LocalAccount,
    entry_price: float,
    size_numerator: int,
    size_denominator: int
) -> float:
    """
    Calculates the trade size (sz) dynamically based on a per-unit funding allocation
    and the confidence level (size_numerator/size_denominator).

    :param account: The Hyperliquid account object.
    :param entry_price: The proposed entry price for the trade.
    :param size_numerator: The numerator of the size (e.g., 1 from 1/5).
    :param size_denominator: The denominator of the size (e.g., 5 from 1/5).
    :return: Calculated trade size in base asset units (sz), or 0.0 if unable to calculate.
    """
    if entry_price <= 0:
        logger.error(f"Invalid entry price {entry_price} for dynamic size calculation. Must be positive.")
        return 0.0

    current_account_value = acct_bal(account)
    if current_account_value <= 0:
        logger.error("Account balance is zero or could not be fetched. Cannot calculate dynamic size.")
        return 0.0

    # `config.FUNDING_PER_1_5_UNIT` defines the base USD value for a '1/5' unit.
    # We multiply this by the `size_numerator` to get the total USD allocation.
    # This design assumes the denominator is primarily 5 as per your example,
    # and `FUNDING_PER_1_5_UNIT` scales with the numerator (1/5, 2/5, etc.).
    if size_denominator == 0:
        logger.warning("Size denominator is zero. Cannot calculate dynamic size to avoid division by zero.")
        return 0.0

    trade_usd_allocation = size_numerator * config.FUNDING_PER_1_5_UNIT

    # Convert USD allocation to the number of base asset units (sz = USD_value / Price_per_unit)
    sz = trade_usd_allocation / entry_price
    logger.info(f"Dynamic sizing: Account Value=${current_account_value:.2f}, Signal Confidence={size_numerator}/{size_denominator}")
    logger.info(f"Allocating ${trade_usd_allocation:.2f} for trade. Calculated sz: {sz:.4f} units at ${entry_price:.4f}.")
    return sz

def place_slippage_controlled_order(
    coin: str,
    is_buy: bool,
    sz: float,
    limit_px: float,
    reduce_only: bool,
    account: LocalAccount,
    max_slippage_percent: float = MAX_ENTRY_SLIPPAGE_PERCENT
) -> dict:
    """
    Places a limit order with slippage control. The order is only placed if the
    proposed limit price from the signal is within a certain percentage of the
    current market price.

    :param coin: The symbol to trade (e.g., 'WIF').
    :param is_buy: Boolean, True for buy order, False for sell order.
    :param sz: Position size in base asset units.
    :param limit_px: The proposed limit price from the signal.
    :param reduce_only: Boolean, True if the order should only reduce an existing position.
    :param account: The Hyperliquid account.
    :param max_slippage_percent: Maximum allowed percentage difference from market price.
    :return: Order result dictionary from Hyperliquid (success or error).
    """
    current_ask, current_bid, _ = ask_bid(coin)

    if current_ask == 0.0 or current_bid == 0.0:
        logger.error(f"Could not get current market prices for {coin}. Skipping slippage check and order placement.")
        return {"error": "Failed to get market prices"}

    # For a buy order, compare signal price to current ask. For a sell order, compare to current bid.
    market_price = current_ask if is_buy else current_bid
    
    # Calculate percentage slippage
    if market_price == 0: # Avoid division by zero
        logger.error(f"Market price for {coin} is 0. Cannot perform slippage check.")
        return {"error": "Market price is zero for slippage check."}

    slippage_abs = abs((limit_px - market_price) / market_price) * 100

    if slippage_abs > max_slippage_percent:
        logger.warning(
            f"Slippage for {coin} is too high ({slippage_abs:.2f}%). "
            f"Signal Price: ${limit_px:.4f}, Market Price: ${market_price:.4f}. "
            f"Max allowed: {max_slippage_percent}%. Order not placed."
        )
        return {"error": f"Slippage too high ({slippage_abs:.2f}%)"}
    
    logger.info(f"Slippage for {coin} ({slippage_abs:.2f}%) is within acceptable limits. Placing order.")
    return limit_order(coin, is_buy, sz, limit_px, reduce_only, account)


def handle_bullish_entry_signal(
    coin: str,
    entry_price: float,
    size_numerator: int,
    size_denominator: int,
    account: LocalAccount,
    add_to_monitor_db_callback: callable # Callback to add trade to DB
) -> dict: # Returns dict of success/fail, potentially trade_id
    """
    Processes a bullish entry signal (buy order).
    Calculates dynamic size, places an order with slippage control,
    and adds the trade to the monitoring database.

    :param coin: Trading pair symbol.
    :param entry_price: Signal entry price.
    :param size_numerator: Confidence numerator.
    :param size_denominator: Confidence denominator.
    :param account: Hyperliquid account.
    :param add_to_monitor_db_callback: A function reference to add the trade to the persistent DB.
    :return: Dictionary containing order result and potentially trade ID if added to monitor.
    """
    logger.info(f"Processing Bullish Entry Signal: {coin}, Entry: ${entry_price:.4f}, Size: {size_numerator}/{size_denominator}")

    # 1. Calculate Dynamic Size
    calculated_sz = calculate_dynamic_sz(account, entry_price, size_numerator, size_denominator)
    if calculated_sz <= 0:
        logger.error(f"Calculated trade size is zero or invalid for {coin}. Aborting entry.")
        return {"status": "failed", "reason": "Invalid calculated size"}

    # 2. Place Order with slippage control
    order_result = place_slippage_controlled_order(
        coin, True, calculated_sz, entry_price, False, account, # True for is_buy (long)
        max_slippage_percent=MAX_ENTRY_SLIPPAGE_PERCENT
    )

    if order_result and "error" not in order_result:
        logger.info(f"Bullish entry order initiated for {coin}.")
        # 3. Add to Persistent Monitoring Database
        # pass relevant parameters to the callback
        trade_id = add_to_monitor_db_callback(
            coin, True, calculated_sz, entry_price,
            DEFAULT_PROFIT_TAKE_PERCENT, DEFAULT_MAX_LOSS_PERCENT
        )
        return {"status": "success", "order_result": order_result, "trade_id": trade_id}
    else:
        logger.error(f"Failed to place bullish entry order for {coin}: {order_result.get('error', 'Unknown error')}")
        return {"status": "failed", "reason": order_result.get('error', 'Unknown order placement error')}


def handle_bearish_entry_signal(
    coin: str,
    entry_price: float,
    size_numerator: int,
    size_denominator: int,
    account: LocalAccount,
    add_to_monitor_db_callback: callable # Callback to add trade to DB
) -> dict: # Returns dict of success/fail, potentially trade_id
    """
    Processes a bearish entry signal (sell/short order).
    Calculates dynamic size, places an order with slippage control,
    and adds the trade to the monitoring database.

    :param coin: Trading pair symbol.
    :param entry_price: Signal entry price.
    :param size_numerator: Confidence numerator.
    :param size_denominator: Confidence denominator.
    :param account: Hyperliquid account.
    :param add_to_monitor_db_callback: A function reference to add the trade to the persistent DB.
    :return: Dictionary containing order result and potentially trade ID if added to monitor.
    """
    logger.info(f"Processing Bearish Entry Signal: {coin}, Entry: ${entry_price:.4f}, Size: {size_numerator}/{size_denominator}")

    # 1. Calculate Dynamic Size (same logic as bullish, but for short exposure)
    calculated_sz = calculate_dynamic_sz(account, entry_price, size_numerator, size_denominator)
    if calculated_sz <= 0:
        logger.error(f"Calculated trade size is zero or invalid for {coin}. Aborting entry.")
        return {"status": "failed", "reason": "Invalid calculated size"}

    # 2. Place Order with slippage control (is_buy=False for short)
    order_result = place_slippage_controlled_order(
        coin, False, calculated_sz, entry_price, False, account, # False for is_buy to short
        max_slippage_percent=MAX_ENTRY_SLIPPAGE_PERCENT
    )

    if order_result and "error" not in order_result:
        logger.info(f"Bearish entry order initiated for {coin}.")
        # 3. Add to Persistent Monitoring Database
        trade_id = add_to_monitor_db_callback(
            coin, False, calculated_sz, entry_price, # False for is_long (short)
            DEFAULT_PROFIT_TAKE_PERCENT, DEFAULT_MAX_LOSS_PERCENT # Use default PnL targets for shorts
        )
        return {"status": "success", "order_result": order_result, "trade_id": trade_id}
    else:
        logger.error(f"Failed to place bearish entry order for {coin}: {order_result.get('error', 'Unknown error')}")
        return {"status": "failed", "reason": order_result.get('error', 'Unknown order placement error')}


def handle_telegram_exit_signal(
    coin: str,
    position_type_str: str, # "Long" or "Short"
    account: LocalAccount,
    update_monitor_db_callback: callable = None # Callback to update trade status in DB
) -> dict:
    """
    Processes a Telegram exit signal to close an existing position using the kill_switch.

    :param coin: The symbol of the position to close.
    :param position_type_str: Specifies if it's a "Long" or "Short" exit. Case-insensitive.
    :param account: Hyperliquid account.
    :param update_monitor_db_callback: Optional function reference to update the trade status in the persistent DB.
    :return: Dictionary indicating the outcome of the exit attempt.
    """
    logger.info(f"Processing Exit Signal: {coin}, Position Type: {position_type_str}")

    _, is_in_position, size, pos_sym, _, pnl_perc, is_long_position = get_position(coin, account)

    if not is_in_position or pos_sym != coin:
        logger.warning(f"Exit signal for {coin} received, but no active position found for this coin on Hyperliquid. Nothing to close.")
        return {"status": "failed", "reason": "No active position on Hyperliquid for this coin."}
        
    # Verify the type of position to close matches the signal
    if position_type_str.lower() == "long" and not is_long_position:
        logger.warning(f"Exit signal for {coin} (Long) received, but current position is Short. Not closing to avoid mis-trade.")
        return {"status": "failed", "reason": "Position type mismatch (Expected Long, found Short)."}
    elif position_type_str.lower() == "short" and is_long_position:
        logger.warning(f"Exit signal for {coin} (Short) received, but current position is Long. Not closing to avoid mis-trade.")
        return {"status": "failed", "reason": "Position type mismatch (Expected Short, found Long)."}

    # Call kill_switch to close the position
    logger.info(f"Executing kill_switch for {coin} as per Telegram exit signal. Current PnL: {pnl_perc:.2f}%")
    kill_switch(coin, account)

    # If successful, try to update the monitoring database
    if update_monitor_db_callback:
        # Find the trade in the DB and update its status.
        # This requires the callback to correctly find the trade by coin and position type.
        # The monitoring_trading.py code will need to expose a method for this.
        update_monitor_db_callback(coin, position_type_str, pnl_perc) # Pass all info to updater
        logger.info(f"Attempted to update DB status for {coin} exit.")

    return {"status": "success", "message": f"Kill switch activated for {coin}."}


def calculate_trailing_stop_price(
    coin: str,
    entry_price: float,
    is_long: bool,
    current_market_price: float,
    highest_price_reached: float, # Peak for long, trough for short
    lowest_price_reached: float, # Peak for short, trough for long
    initial_stop_percentage: float = DEFAULT_MAX_LOSS_PERCENT * -1, # Convert to positive for calculation
    trailing_percentage: float = DEFAULT_TRAILING_STOP_PERCENT
) -> float:
    """
    Calculates a dynamic trailing stop price for a position.
    This function *calculates* the price; it does not place orders.
    The monitoring loop would use this to determine if a stop needs to be placed or adjusted.

    :param coin: The symbol.
    :param entry_price: The average entry price of the position.
    :param is_long: True if the position is long, False if short.
    :param current_market_price: The current price of the asset.
    :param highest_price_reached: The highest price reached since entry (for long positions).
    :param lowest_price_reached: The lowest price reached since entry (for short positions).
    :param initial_stop_percentage: The initial static stop loss percentage based on entry price (e.g., 5 for 5%).
    :param trailing_percentage: The percentage to trail the peak profit (e.g., 5 for 5%).
    :return: The calculated trailing stop price.
    """
    # Defensive programming
    if initial_stop_percentage < 0 or trailing_percentage < 0:
        logger.error("Initial stop and trailing percentages must be positive values for calculation.")
        return 0.0 # Indicate error or invalid calculation

    if is_long:
        # For a long position, stop trails the highest price reached
        # A. Calculate the initial static stop loss price (based on entry)
        initial_px_stop = entry_price * (1 - initial_stop_percentage / 100)
        
        # B. Calculate the trailing stop price (based on highest price reached)
        trailing_px_stop = highest_price_reached * (1 - trailing_percentage / 100)
        
        # The active stop price is the maximum of the initial stop and the trailing stop.
        # This ensures the stop moves up with price, but never drops below the initial hard stop.
        calculated_stop_px = max(initial_px_stop, trailing_px_stop)
        
        # Ensure the stop is always below the current market price for a long,
        # unless it has been hit.
        # Or, more robustly, ensure it doesn't move back up unnecessarily if price dips.
        # This function provides the *calculation*. The monitoring loop will compare it.
        return calculated_stop_px
    else: # Short position
        # For a short position, stop trails the lowest price reached
        # A. Calculate the initial static stop loss price (based on entry)
        initial_px_stop = entry_price * (1 + initial_stop_percentage / 100)
        
        # B. Calculate the trailing stop price (based on lowest price reached)
        trailing_px_stop = lowest_price_reached * (1 + trailing_percentage / 100)
        
        # The active stop price is the minimum of the initial stop and the trailing stop.
        # This ensures the stop moves down with price, but never rises above the initial hard stop.
        calculated_stop_px = min(initial_px_stop, trailing_px_stop)

        # Ensure the stop is always above the current market price for a short,
        # unless it has been hit.
        return calculated_stop_px

# This module adds functions to be imported and used by telegram_listener.py
# and monitoring_trading.py
