# bot_core/strategy_manager.py - Enhanced Trading Logic

import logging
import math

from .hyperliquid_api import (
    ask_bid,
    limit_order,
    get_position,
    acct_bal,
    kill_switch,
    account
)
import config

logger = logging.getLogger(__name__)

def calculate_dynamic_sz(entry_price: float, size_numerator: int, size_denominator: int) -> float:
    """
    Calculates the trade size (sz) dynamically based on a per-unit funding allocation
    and the confidence level (size_numerator/size_denominator).
    """
    if entry_price <= 0:
        logger.error(f"Invalid entry price {entry_price} for dynamic size calculation. Must be positive.")
        return 0.0

    current_account_value = acct_bal(account)
    if current_account_value <= 0:
        logger.error("Account balance is zero or could not be fetched. Cannot calculate dynamic size.")
        return 0.0

    if size_denominator == 0:
        logger.warning("Size denominator is zero. Cannot calculate dynamic size to avoid division by zero.")
        return 0.0

    trade_usd_allocation = size_numerator * config.FUNDING_PER_1_5_UNIT
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
    max_slippage_percent: float = None
) -> dict:
    """
    Places a limit order with slippage control.
    """
    if max_slippage_percent is None:
        max_slippage_percent = config.MAX_ENTRY_SLIPPAGE_PERCENT
        
    current_ask, current_bid, _ = ask_bid(coin)

    if current_ask == 0.0 or current_bid == 0.0:
        logger.error(f"Could not get current market prices for {coin}. Skipping slippage check and order placement.")
        return {"error": "Failed to get market prices"}

    market_price = current_ask if is_buy else current_bid
    
    if market_price == 0:
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
    add_to_monitor_db_callback: callable
) -> dict:
    """
    Processes a bullish entry signal (buy order).
    """
    logger.info(f"Processing Bullish Entry Signal: {coin}, Entry: ${entry_price:.4f}, Size: {size_numerator}/{size_denominator}")

    # 1. Calculate Dynamic Size
    calculated_sz = calculate_dynamic_sz(entry_price, size_numerator, size_denominator)
    if calculated_sz <= 0:
        logger.error(f"Calculated trade size is zero or invalid for {coin}. Aborting entry.")
        return {"status": "failed", "reason": "Invalid calculated size"}

    # 2. Place Order with slippage control
    order_result = place_slippage_controlled_order(
        coin, True, calculated_sz, entry_price, False
    )

    if order_result and "error" not in order_result:
        logger.info(f"Bullish entry order initiated for {coin}.")
        # 3. Add to Persistent Monitoring Database
        trade_id = add_to_monitor_db_callback(
            coin, True, calculated_sz, entry_price,
            config.DEFAULT_PROFIT_TAKE_PERCENT, config.DEFAULT_MAX_LOSS_PERCENT
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
    add_to_monitor_db_callback: callable
) -> dict:
    """
    Processes a bearish entry signal (sell/short order).
    """
    logger.info(f"Processing Bearish Entry Signal: {coin}, Entry: ${entry_price:.4f}, Size: {size_numerator}/{size_denominator}")

    # 1. Calculate Dynamic Size
    calculated_sz = calculate_dynamic_sz(entry_price, size_numerator, size_denominator)
    if calculated_sz <= 0:
        logger.error(f"Calculated trade size is zero or invalid for {coin}. Aborting entry.")
        return {"status": "failed", "reason": "Invalid calculated size"}

    # 2. Place Order with slippage control
    order_result = place_slippage_controlled_order(
        coin, False, calculated_sz, entry_price, False
    )

    if order_result and "error" not in order_result:
        logger.info(f"Bearish entry order initiated for {coin}.")
        # 3. Add to Persistent Monitoring Database
        trade_id = add_to_monitor_db_callback(
            coin, False, calculated_sz, entry_price,
            config.DEFAULT_PROFIT_TAKE_PERCENT, config.DEFAULT_MAX_LOSS_PERCENT
        )
        return {"status": "success", "order_result": order_result, "trade_id": trade_id}
    else:
        logger.error(f"Failed to place bearish entry order for {coin}: {order_result.get('error', 'Unknown error')}")
        return {"status": "failed", "reason": order_result.get('error', 'Unknown order placement error')}

def handle_telegram_exit_signal(
    coin: str,
    position_type_str: str,
    update_monitor_db_callback: callable = None
) -> dict:
    """
    Processes a Telegram exit signal to close an existing position using the kill_switch.
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
        update_monitor_db_callback(coin, position_type_str, pnl_perc)
        logger.info(f"Attempted to update DB status for {coin} exit.")

    return {"status": "success", "message": f"Kill switch activated for {coin}."}

def calculate_trailing_stop_price(
    coin: str,
    entry_price: float,
    is_long: bool,
    current_market_price: float,
    highest_price_reached: float,
    lowest_price_reached: float,
    initial_stop_percentage: float = None,
    trailing_percentage: float = None
) -> float:
    """
    Calculates a dynamic trailing stop price for a position.
    """
    if initial_stop_percentage is None:
        initial_stop_percentage = config.DEFAULT_MAX_LOSS_PERCENT * -1
    if trailing_percentage is None:
        trailing_percentage = config.DEFAULT_TRAILING_STOP_PERCENT
        
    # Defensive programming
    if initial_stop_percentage < 0 or trailing_percentage < 0:
        logger.error("Initial stop and trailing percentages must be positive values for calculation.")
        return 0.0

    if is_long:
        initial_px_stop = entry_price * (1 - initial_stop_percentage / 100)
        trailing_px_stop = highest_price_reached * (1 - trailing_percentage / 100)
        calculated_stop_px = max(initial_px_stop, trailing_px_stop)
        return calculated_stop_px
    else:
        initial_px_stop = entry_price * (1 + initial_stop_percentage / 100)
        trailing_px_stop = lowest_price_reached * (1 + trailing_percentage / 100)
        calculated_stop_px = min(initial_px_stop, trailing_px_stop)
        return calculated_stop_px