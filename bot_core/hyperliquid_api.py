#monitoring_trading.py-->hyperliquid_api.py

import json
import time
import requests
import os
import logging

from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# Load sensitive configurations (API keys, etc.)
# Make sure your do_not_share.py is in the same directory or accessible via PYTHONPATH
try:
    from dotenv import load_dotenv
    load_dotenv()
    HYPERLIQUID_SECRET_KEY = os.getenv("HYPERLIQUID_SECRET_KEY")

except ImportError:
    logging.error(".env not found. Please create it with your API keys.")
    exit()

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Hyperliquid Account Initialization ---
# Initialize the Hyperliquid account using the secret key from do_not_share.
# This object will be passed to functions that interact with the exchange.
account = None
if HYPERLIQUID_SECRET_KEY:
    try:
        account = Account.from_key(HYPERLIQUID_SECRET_KEY)
        logger.info(f"Hyperliquid account initialized for address: {account.address}")
    except Exception as e:
        logger.error(f"Failed to initialize Hyperliquid account: {e}")
else:
    logger.error("HYPERLIQUID_SECRET_KEY not found in do_not_share.py or environment variables. Exiting.")
    exit()

# Caching for szDecimals and pxDecimals as they are static for a coin
_DECIMAL_CACHE = {}

# ─────────────────────────────────────────────────────────────────────────────
#  1. FETCHING ASK/BID AND L2 DATA
# ─────────────────────────────────────────────────────────────────────────────
def ask_bid(coin: str) -> tuple[float, float, list]:
    """
    Fetches the current best ask and bid price for the given coin from Hyperliquid
    by requesting level 2 (L2) order book data.

    :param coin: The trading pair symbol (e.g., 'WIF').
    :return: A tuple (ask, bid, l2_data), where:
        - ask = float, best ask (lowest sell price)
        - bid = float, best bid (highest buy price)
        - l2_data = complete L2 order book levels (raw response)
    """
    url = constants.MAINNET_API_URL # Using the constant for API URL
    headers = {'Content-Type': 'application/json'}
    data = {
        'type': 'l2Book',
        'coin': coin
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status() # Raise an HTTPError for bad responses (4xx or 5xx)
        l2_data = response.json()['levels']

        # L2 order book format: l2_data[0] is the bid side, l2_data[1] is the ask side
        bid = float(l2_data[0][0]['px'])
        ask = float(l2_data[1][0]['px'])

        return ask, bid, l2_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching L2 book for {coin}: {e}")
        return 0.0, 0.0, []
    except (KeyError, IndexError, ValueError) as e:
        logger.error(f"Failed to parse L2 book data for {coin}: {e}, Response: {response.text if 'response' in locals() else 'N/A'}")
        return 0.0, 0.0, []

# ─────────────────────────────────────────────────────────────────────────────
#  2. GET SIZE & PRICE DECIMALS (with caching)
# ─────────────────────────────────────────────────────────────────────────────
def get_sz_px_decimals(coin: str) -> tuple[int, int]:
    """
    Fetches the size and price decimal precision for the given coin.
    Uses cached values if available. If not, requests 'meta' data from Hyperliquid,
    identifies the coin's entry, and deduces price decimals from a sample ask price.

    :param coin: The symbol for which decimals are fetched.
    :return: A tuple (sz_decimals, px_decimals), representing
             the size decimals and price decimals, respectively.
    """
    if coin in _DECIMAL_CACHE:
        return _DECIMAL_CACHE[coin]

    url = constants.MAINNET_API_URL
    headers = {'Content-Type': 'application/json'}
    data = {'type': 'meta'}

    sz_decimals = 0
    px_decimals = 0

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        meta_data = response.json()
        symbols = meta_data['universe']

        # Find the matching symbol dictionary
        symbol_info = next((s for s in symbols if s['name'] == coin), None)
        if symbol_info:
            sz_decimals = symbol_info['szDecimals']
        else:
            logger.warning(f"Symbol '{coin}' not found in Hyperliquid meta data.")
            # Default to reasonable values if not found, or raise an error
            sz_decimals = 2 # Common default
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching meta data for {coin}: {e}")
    except (KeyError, ValueError) as e:
        logger.error(f"Failed to parse meta data: {e}, Response: {response.text if 'response' in locals() else 'N/A'}")

    # Using ask_bid() to guess the number of decimals in the price
    # This might sometimes be inaccurate for very round numbers (e.g., 100.0 vs 100)
    ask, _, _ = ask_bid(coin)
    ask_str = str(ask)
    if '.' in ask_str:
        px_decimals = len(ask_str.split('.')[1])
    else:
        px_decimals = 0

    logger.info(f"Decimals for {coin}: Size={sz_decimals}, Price={px_decimals}")
    _DECIMAL_CACHE[coin] = (sz_decimals, px_decimals)
    return sz_decimals, px_decimals

# ─────────────────────────────────────────────────────────────────────────────
#  3. PLACING A LIMIT ORDER
# ─────────────────────────────────────────────────────────────────────────────
def limit_order(coin: str, is_buy: bool, sz: float, limit_px: float, reduce_only: bool, account: Account):
    """
    Places a limit order (buy or sell) on Hyperliquid via the provided account.

    :param coin: The symbol to trade (e.g., 'WIF').
    :param is_buy: Boolean, True if buy order, False if sell.
    :param sz: Position size (float).
    :param limit_px: The limit price (float).
    :param reduce_only: Boolean, True if the order should only reduce an existing position.
    :param account: A LocalAccount object used for authentication.
    :return: The raw result from the exchange's order placement API call.
    """
    exchange = Exchange(account, constants.MAINNET_API_URL)

    # Get size decimals to ensure order size is rounded correctly
    sz_decimals, _ = get_sz_px_decimals(coin)
    sz_rounded = round(sz, sz_decimals)

    logger.info(f"Placing limit order for {coin}: {'BUY' if is_buy else 'SELL'} {sz_rounded} @ {limit_px} (Reduce Only: {reduce_only})")

    try:
        order_result = exchange.order(
            coin,
            is_buy,
            sz_rounded,
            limit_px,
            {"limit": {"tif": 'Gtc'}}, # Good-Til-Cancelled order
            reduce_only=reduce_only
        )

        if order_result and 'response' in order_result and order_result['response']['data']['statuses'][0]:
            status = order_result['response']['data']['statuses'][0]
            logger.info(f"Order placed successfully: Status={status}")
        else:
            logger.error(f"Order placement failed or returned unexpected response: {order_result}")
        return order_result
    except Exception as e:
        logger.error(f"Error placing order for {coin}: {e}")
        return {"error": str(e)}

# ─────────────────────────────────────────────────────────────────────────────
#  4. CHECK ACCOUNT BALANCE
# ─────────────────────────────────────────────────────────────────────────────
def acct_bal(account: Account) -> float:
    """
    Retrieves and prints the current account value (e.g., margin/collateral)
    from the Hyperliquid User State endpoint.

    :param account: An account object with .address attribute.
    :return: Account value (float), 0.0 if unable to retrieve.
    """
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    try:
        user_state = info.user_state(account.address)
        acct_value = float(user_state["marginSummary"]["accountValue"])
        logger.info(f"Current account value: {acct_value}")
        return acct_value
    except Exception as e:
        logger.error(f"Error fetching account balance for {account.address}: {e}")
        return 0.0

# ─────────────────────────────────────────────────────────────────────────────
#  5. GET POSITION DETAILS
# ─────────────────────────────────────────────────────────────────────────────
def get_position(coin: str, account: Account) -> tuple:
    """
    Retrieves position info for a specific coin from the user's account.
    Determines if a position is open, whether it's long or short, and
    calculates PnL as a percentage (return on equity).

    :param coin: The symbol to check (e.g., 'WIF').
    :param account: Account object with .address.
    :return: A tuple (matching_positions, is_in_position, size, position_symbol,
                       entry_price, pnl_percentage, is_long):
        - matching_positions: A list of matching positions (can be empty)
        - is_in_position: Boolean, True if a position is open for the given coin
        - size: float, the position size (positive for long, negative for short)
        - position_symbol: The symbol for the position if found, else None
        - entry_price: The average entry price, else 0
        - pnl_percentage: Return on equity percentage * 100, else 0
        - is_long: Boolean, True if long, False if short, None if no position
    """
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    try:
        user_state = info.user_state(account.address)
        # logger.debug(f"Full user state: {json.dumps(user_state, indent=2)}")

        matching_positions = []
        is_in_position = False
        size = 0.0
        position_symbol = None
        entry_price = 0.0
        pnl_percentage = 0.0
        is_long = None

        # Iterate through all asset positions, looking for one matching this coin
        for asset_position in user_state.get("assetPositions", []):
            position = asset_position.get("position", {})
            if (position.get("coin") == coin) and float(position.get("szi", 0)) != 0:
                matching_positions.append(position)
                is_in_position = True
                size = float(position["szi"])       # Negative if short
                position_symbol = position["coin"]
                entry_price = float(position["entryPx"])
                pnl_percentage = float(position["returnOnEquity"]) * 100
                logger.info(f"Position found for {coin}: Size={size}, EntryPx={entry_price}, PnL%={pnl_percentage:.2f}%")
                break # Assuming only one position per coin is managed
        else:
            logger.info(f"No active position found for {coin}.")

        # Determine if the position is long or short based on size sign
        if size > 0:
            is_long = True
        elif size < 0:
            is_long = False
        # If size is 0, is_long remains None

        return matching_positions, is_in_position, size, position_symbol, entry_price, pnl_percentage, is_long
    except Exception as e:
        logger.error(f"Error fetching position for {coin} for account {account.address}: {e}")
        return [], False, 0.0, None, 0.0, 0.0, None

# ─────────────────────────────────────────────────────────────────────────────
#  6. CANCEL ALL ORDERS
# ─────────────────────────────────────────────────────────────────────────────
def cancel_all_orders(account: Account):
    """
    Fetches all open orders for the account and cancels them.
    Useful before adjusting positions, to avoid leftover orders.

    :param account: Account object with .address for authentication.
    """
    exchange = Exchange(account, constants.MAINNET_API_URL)
    info = Info(constants.MAINNET_API_URL, skip_ws=True)

    try:
        open_orders = info.open_orders(account.address)
        if not open_orders:
            logger.info("No open orders to cancel.")
            return

        logger.info(f"Attempting to cancel {len(open_orders)} open orders.")
        for order in open_orders:
            # Cancel each open order by coin and order ID
            cancel_result = exchange.cancel(order['coin'], order['oid'])
            if cancel_result and 'response' in cancel_result and 'statuses' in cancel_result['response']['data'] and cancel_result['response']['data']['statuses'][0]:
                logger.info(f"Cancelled order {order['oid']} for {order['coin']}.")
            else:
                logger.warning(f"Failed to cancel order {order['oid']} for {order['coin']}: {cancel_result}")
    except Exception as e:
        logger.error(f"Error cancelling all orders for {account.address}: {e}")

# ─────────────────────────────────────────────────────────────────────────────
#  7. KILL SWITCH (IMMEDIATE POSITION EXIT)
# ─────────────────────────────────────────────────────────────────────────────
def kill_switch(coin: str, account: Account):
    """
    Closes any open position on the specified coin by canceling
    all open orders first, then placing a marketable order in
    the opposite direction. Continues until position is zero.
    This is an emergency function to quickly exit a trade.

    :param coin: The symbol to close (e.g., 'WIF').
    :param account: Authentication/account object for trade actions.
    """
    logger.info(f"Activating kill switch for {coin}...")

    # Loop until the position is completely closed
    while True:
        _, is_in_position, pos_size, pos_sym, _, _, is_long = get_position(coin, account)

        if not is_in_position or abs(pos_size) < 1e-9: # Check for near zero size due to float precision
            logger.info(f"Position for {coin} successfully closed.")
            break

        logger.info(f"Current position for {coin}: Size={pos_size}, Long={is_long}. Attempting to close...")

        # Cancel existing open orders for this coin to clear the way
        # NOTE: cancel_all_orders would cancel ALL orders. You might need to refine
        # it to cancel orders only for the specific 'coin' if you have other open orders.
        # For simplicity here, calling global cancel_all_orders.
        cancel_all_orders(account) # This should actually be refined to cancel for THIS coin only

        # Get current best ask/bid from the order book
        ask, bid, _ = ask_bid(coin)
        if ask == 0.0 or bid == 0.0:
            logger.error(f"Could not get market prices for {coin}. Retrying kill switch.")
            time.sleep(5)
            continue

        # Make pos_size positive for the trade execution
        abs_pos_size = abs(pos_size)

        # If currently long, sell at best bid (market sell effectively)
        if is_long:
            logger.info(f"Kill switch: Selling {abs_pos_size} {coin} at {bid} to close long position.")
            limit_order(coin, False, abs_pos_size, bid, True, account)
        # If currently short, buy at best ask (market buy effectively)
        elif is_long is False:
            logger.info(f"Kill switch: Buying {abs_pos_size} {coin} at {ask} to close short position.")
            limit_order(coin, True, abs_pos_size, ask, True, account)
        else: # Should not happen if is_in_position is True but size is 0 or error
            logger.warning(f"Unexpected state in kill switch for {coin}: in position but is_long is None.")
            break

        # Give some time for the order to fill
        time.sleep(5)

# ─────────────────────────────────────────────────────────────────────────────
#  8. PNL-BASED POSITION CLOSING
# ─────────────────────────────────────────────────────────────────────────────
def pnl_close(coin: str, target_pnl: float, max_loss_pnl: float, account: Account):
    """
    Monitors the open position's PnL percentage (pnl_perc).
    - If pnl_perc > target_pnl, closes the position (take profit).
    - If pnl_perc <= max_loss_pnl, closes the position (stop loss).
    - Otherwise, does nothing.

    :param coin: The symbol to monitor (e.g., 'WIF').
    :param target_pnl: Float, PnL percentage threshold to take profit (e.g., 20.0 for 20%).
    :param max_loss_pnl: Float, PnL percentage threshold to trigger a stop loss (e.g., -5.0 for -5%).
    :param account: Authentication/account object for trade actions.
    """
    logger.info(f"Monitoring PnL for {coin} (Target: {target_pnl}%, Max Loss: {max_loss_pnl}%)")
    _, is_in_position, _, pos_sym, _, pnl_percentage, _ = get_position(coin, account)

    if not is_in_position:
        logger.info(f"No active position for {coin}. PnL monitoring skipped.")
        return

    # Check if current PnL is above target => close for profit
    if pnl_percentage >= target_pnl:
        logger.info(f"PnL for {coin} ({pnl_percentage:.2f}%) >= target ({target_pnl}%). Closing position for profit.")
        kill_switch(pos_sym, account)
    # If current PnL is below or equal to max_loss => close to prevent further losses
    elif pnl_percentage <= max_loss_pnl:
        logger.warning(f"PnL for {coin} ({pnl_percentage:.2f}%) <= max loss ({max_loss_pnl}%). Closing position as stop loss.")
        kill_switch(pos_sym, account)
    # Otherwise, keep position open
    else:
        logger.info(f"PnL for {coin} is {pnl_percentage:.2f}%. Within limits. Not closing position.")

# ─────────────────────────────────────────────────────────────────────────────
#  Example Usage / Main Execution Block (for testing functions individually)
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    # This block is for testing individual functions or running the bot in a
    # standalone scheduled manner (as your original bot likely did).
    # For Telegram integration, the telegram_listener.py will import and
    # call these functions based on messages.

    test_coin = 'WIF' # Example coin for testing
    test_target_pnl = 10.0 # 10% profit target
    test_max_loss_pnl = -5.0 # -5% stop loss

    logger.info(f"--- Testing Hyperliquid Bot Functions for {test_coin} ---")

    # 1. Check Account Balance
    current_balance = acct_bal(account)
    if current_balance > 0:
        logger.info(f"Account balance is healthy: ${current_balance:.2f}")
    else:
        logger.error("Account balance is zero or could not be fetched. Cannot proceed with testing trades.")
        exit()

    # 2. Get Decimals
    sz_dec, px_dec = get_sz_px_decimals(test_coin)
    logger.info(f"'{test_coin}' has size decimals: {sz_dec}, price decimals: {px_dec}")

    # 3. Get Current Market Prices
    ask, bid, _ = ask_bid(test_coin)
    logger.info(f"'{test_coin}' Ask: {ask}, Bid: {bid}")

    # 4. (Optional) Place a test limit order (uncomment to test)
    # Requires careful handling: this will place a real order!
    # test_size_usd = 10 # $10 worth of WIF
    # test_sz = test_size_usd / ask # Calculate size based on current ask
    # logger.info(f"Attempting to place a test BUY order for {test_coin} size {test_sz} @ {ask}")
    # try:
    #     limit_order_result = limit_order(test_coin, True, test_sz, ask, False, account)
    #     logger.info(f"Limit order result: {limit_order_result}")
    #     time.sleep(5) # Wait for order to potentially fill/process
    # except Exception as e:
    #     logger.error(f"Failed to place test limit order: {e}")

    # 5. Check position after potential trade
    _, is_in_pos, size, pos_sym, entry_px, pnl_perc, is_long = get_position(test_coin, account)
    if is_in_pos:
        logger.info(f"Currently in position for {pos_sym}: Size={size}, Entry={entry_px}, PnL={pnl_perc:.2f}%")
        # 6. Test PnL-based closing
        pnl_close(test_coin, test_target_pnl, test_max_loss_pnl, account)
        # 7. (Optional) Test kill switch if still in position after PnL close (uncomment to test)
        # _, is_in_pos_after_pnl, _, _, _, _, _ = get_position(test_coin, account)
        # if is_in_pos_after_pnl:
        #     logger.info("Still in position after PnL close, invoking kill switch...")
        #     kill_switch(test_coin, account)
    else:
        logger.info(f"No active position for {test_coin}.")

    logger.info("--- Hyperliquid Bot Functions Test Complete ---")

