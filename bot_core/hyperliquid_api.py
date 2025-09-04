# bot_core/hyperliquid_api.py - Fixed with working logic from bot_with_comments.py

import json
import time
import requests
import os
import logging
import config

from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Hyperliquid Account Initialization ---
account = None
if config.HYPERLIQUID_SECRET_KEY:
    try:
        account = Account.from_key(config.HYPERLIQUID_SECRET_KEY)
        logger.info(f"Hyperliquid account initialized for address: {account.address}")
    except Exception as e:
        logger.error(f"Failed to initialize Hyperliquid account: {e}")
        exit()
else:
    logger.error("HYPERLIQUID_SECRET_KEY not found in config. Exiting.")
    exit()

# Caching for szDecimals and pxDecimals as they are static for a coin
_DECIMAL_CACHE = {}

# ─────────────────────────────────────────────────────────────────────────────
#  1. FETCHING ASK/BID AND L2 DATA (FIXED with working logic)
# ─────────────────────────────────────────────────────────────────────────────
def ask_bid(coin: str) -> tuple[float, float, list]:
    """
    Fetches the current best ask and bid price for the given coin from Hyperliquid
    by requesting level 2 (L2) order book data.
    """
    # Use local API_URL definition like working version
    API_URL = constants.TESTNET_API_URL if config.USE_TESTNET else constants.MAINNET_API_URL
    url = f"{API_URL}/info"  # 🔧 FIXED: Add /info endpoint like working version
    headers = {'Content-Type': 'application/json'}

    data = {
        'type': 'l2Book',
        'coin': coin
    }

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        
        # Debug output like working version
        logger.debug(f"Ask/Bid API Status: {response.status_code}")
        
        response.raise_for_status()
        l2_data = response.json()['levels']

        # L2 order book format: l2_data[0] is the bid side, l2_data[1] is the ask side
        bid = float(l2_data[0][0]['px'])
        ask = float(l2_data[1][0]['px'])

        return ask, bid, l2_data
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching L2 book for {coin}: {e}")
        return 0.0, 0.0, []
    except (KeyError, IndexError, ValueError) as e:
        logger.error(f"Failed to parse L2 book data for {coin}: {e}")
        return 0.0, 0.0, []

# ─────────────────────────────────────────────────────────────────────────────
#  2. GET SIZE & PRICE DECIMALS (FIXED with working logic)
# ─────────────────────────────────────────────────────────────────────────────
def get_sz_px_decimals(coin: str) -> tuple[int, int]:
    """
    Fetches the size and price decimal precision for the given coin.
    """
    if coin in _DECIMAL_CACHE:
        return _DECIMAL_CACHE[coin]

    # Use local API_URL definition like working version
    API_URL = constants.TESTNET_API_URL if config.USE_TESTNET else constants.MAINNET_API_URL
    url = f"{API_URL}/info"  # 🔧 FIXED: Add /info endpoint
    headers = {'Content-Type': 'application/json'}
    data = {'type': 'meta'}

    sz_decimals = 0
    px_decimals = 0

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        
        if response.status_code == 200:
            meta_data = response.json()
            symbols = meta_data['universe']

            # Find the matching symbol dictionary
            symbol_info = next((s for s in symbols if s['name'] == coin), None)
            if symbol_info:
                sz_decimals = symbol_info['szDecimals']
            else:
                logger.warning(f"Symbol '{coin}' not found in Hyperliquid meta data.")
                sz_decimals = 2  # Common default
        else:
            logger.error(f'Error fetching meta: {response.status_code}')
            sz_decimals = 0
            
    except requests.exceptions.RequestException as e:
        logger.error(f"Network error fetching meta data for {coin}: {e}")
    except (KeyError, ValueError) as e:
        logger.error(f"Failed to parse meta data: {e}")

    # Using ask_bid() to guess the number of decimals in the price
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
#  3. PLACING A LIMIT ORDER (FIXED with working logic)
# ─────────────────────────────────────────────────────────────────────────────
def limit_order(coin: str, is_buy: bool, sz: float, limit_px: float, reduce_only: bool, account: Account):
    """
    Places a limit order (buy or sell) on Hyperliquid via the provided account.
    """
    # Use local API_URL definition like working version
    API_URL = constants.TESTNET_API_URL if config.USE_TESTNET else constants.MAINNET_API_URL
    exchange = Exchange(account, API_URL)

    # Get size decimals and round like working version
    sz_decimals, _ = get_sz_px_decimals(coin)
    sz_rounded = round(sz, sz_decimals)

    # Debug output like working version
    logger.info(f'coin: {coin}, type: {type(coin)}')
    logger.info(f'is_buy: {is_buy}, type: {type(is_buy)}')
    logger.info(f'sz: {sz_rounded}, type: {type(sz_rounded)}')
    logger.info(f'limit_px: {limit_px}, type: {type(limit_px)}')
    logger.info(f'reduce_only: {reduce_only}, type: {type(reduce_only)}')

    logger.info(f'Placing limit order for {coin}: {"BUY" if is_buy else "SELL"} {sz_rounded} @ {limit_px} (Reduce Only: {reduce_only})')

    try:
        order_result = exchange.order(
            coin,
            is_buy,
            sz_rounded,
            limit_px,
            {"limit": {"tif": 'Gtc'}},  # Good-Til-Cancelled order
            reduce_only=reduce_only
        )

        # Enhanced response handling like working version
        if order_result and 'response' in order_result:
            if is_buy:
                logger.info(f"Limit BUY order placed: {order_result['response']['data']['statuses'][0]}")
            else:
                logger.info(f"Limit SELL order placed: {order_result['response']['data']['statuses'][0]}")
        else:
            logger.error(f"Order placement failed or returned unexpected response: {order_result}")
            
        return order_result
    except Exception as e:
        logger.error(f"Error placing order for {coin}: {e}")
        return {"error": str(e)}

# ─────────────────────────────────────────────────────────────────────────────
#  4. CHECK ACCOUNT BALANCE (FIXED with working logic)
# ─────────────────────────────────────────────────────────────────────────────
def acct_bal(account: Account) -> float:
    """
    Retrieves and prints the current account value from Hyperliquid.
    """
    # Use local API_URL definition like working version
    API_URL = constants.TESTNET_API_URL if config.USE_TESTNET else constants.MAINNET_API_URL
    info = Info(API_URL, skip_ws=True)
    
    try:
        user_state = info.user_state(account.address)
        
        # Enhanced debugging like working version
        logger.debug("All margin summary fields: %s", user_state["marginSummary"])
        
        acct_value = float(user_state["marginSummary"]["accountValue"])
        logger.info(f"Current account value: {acct_value}")
        return acct_value
    except Exception as e:
        logger.error(f"Error fetching account balance for {account.address}: {e}")
        return 0.0

# ─────────────────────────────────────────────────────────────────────────────
#  5. GET POSITION DETAILS (FIXED with working logic)
# ─────────────────────────────────────────────────────────────────────────────
def get_position(coin: str, account: Account) -> tuple:
    """
    Retrieves position info for a specific coin from the user's account.
    """
    # Use local API_URL definition like working version
    API_URL = constants.TESTNET_API_URL if config.USE_TESTNET else constants.MAINNET_API_URL
    info = Info(API_URL, skip_ws=True)
    
    try:
        user_state = info.user_state(account.address)

        # Enhanced debugging like working version
        logger.debug(f"Current account value: {user_state['marginSummary']['accountValue']}")
        logger.debug(f"Checking symbol: {coin}")
        logger.debug(f"Asset positions: {user_state['assetPositions']}")

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
                break
        else:
            logger.info(f"No active position found for {coin}.")

        # Determine if the position is long or short based on size sign
        if size > 0:
            is_long = True
        elif size < 0:
            is_long = False

        return matching_positions, is_in_position, size, position_symbol, entry_price, pnl_percentage, is_long
    except Exception as e:
        logger.error(f"Error fetching position for {coin} for account {account.address}: {e}")
        return [], False, 0.0, None, 0.0, 0.0, None

# ─────────────────────────────────────────────────────────────────────────────
#  6. CANCEL ALL ORDERS (FIXED with working logic)
# ─────────────────────────────────────────────────────────────────────────────
def cancel_all_orders(account: Account):
    """
    Fetches all open orders for the account and cancels them.
    """
    # Use local API_URL definition like working version
    API_URL = constants.TESTNET_API_URL if config.USE_TESTNET else constants.MAINNET_API_URL
    exchange = Exchange(account, API_URL)
    info = Info(API_URL, skip_ws=True)

    try:
        open_orders = info.open_orders(account.address)
        
        logger.info(f"Open orders to cancel: {len(open_orders)}")
        
        if not open_orders:
            logger.info("No open orders to cancel.")
            return

        for order in open_orders:
            # Cancel each open order by coin and order ID
            cancel_result = exchange.cancel(order['coin'], order['oid'])
            logger.info(f"Cancelled order {order['oid']} for {order['coin']}")
            
    except Exception as e:
        logger.error(f"Error cancelling all orders for {account.address}: {e}")

# ─────────────────────────────────────────────────────────────────────────────
#  7. KILL SWITCH (FIXED with working logic)
# ─────────────────────────────────────────────────────────────────────────────
def kill_switch(coin: str, account: Account):
    """
    Closes any open position on the specified coin using working logic.
    """
    logger.info(f"Activating kill switch for {coin}...")

    # Use the working version's approach
    matching_positions, is_in_position, pos_size, pos_sym, entry_px, pnl_perc, is_long = get_position(coin, account)

    # If currently in a position, keep trying to close it (like working version)
    while is_in_position:
        # Cancel existing open orders
        cancel_all_orders(account)

        # Get current best ask/bid from the order book
        ask, bid, _ = ask_bid(coin)
        if ask == 0.0 or bid == 0.0:
            logger.error(f"Could not get market prices for {coin}. Retrying kill switch.")
            time.sleep(5)
            continue

        # Make pos_size positive for the trade (like working version)
        abs_pos_size = abs(pos_size)

        # If currently long, sell at best ask (like working version)
        if is_long:
            logger.info(f"Kill switch: Selling {abs_pos_size} {coin} at {ask} to close long position.")
            limit_order(coin, False, abs_pos_size, ask, True, account)
            logger.info('Kill switch - SELL TO CLOSE SUBMITTED')
            time.sleep(5)
        # If currently short, buy at best bid (like working version)
        elif is_long is False:
            logger.info(f"Kill switch: Buying {abs_pos_size} {coin} at {bid} to close short position.")
            limit_order(coin, True, abs_pos_size, bid, True, account)
            logger.info('Kill switch - BUY TO CLOSE SUBMITTED')
            time.sleep(5)
        else:
            logger.warning(f"Unexpected state in kill switch for {coin}: in position but is_long is None.")
            break

        # Re-check position to see if fully closed yet (like working version)
        matching_positions, is_in_position, pos_size, pos_sym, entry_px, pnl_perc, is_long = get_position(coin, account)

    logger.info('Position successfully closed in the kill switch')

# ─────────────────────────────────────────────────────────────────────────────
#  8. PNL-BASED POSITION CLOSING (FIXED with working logic)
# ─────────────────────────────────────────────────────────────────────────────
def pnl_close(coin: str, target_pnl: float, max_loss_pnl: float, account: Account):
    """
    Monitors the open position's PnL percentage using working logic.
    """
    logger.info(f"Starting PnL close for {coin} (Target: {target_pnl}%, Max Loss: {max_loss_pnl}%)")
    
    # Use working version's approach
    matching_positions, is_in_position, pos_size, pos_sym, entry_px, pnl_percentage, is_long = get_position(coin, account)

    if not is_in_position:
        logger.info(f"No active position for {coin}. PnL monitoring skipped.")
        return

    # Check if current PnL is above target => close for profit (like working version)
    if pnl_percentage > target_pnl:
        logger.info(f"PnL gain is {pnl_percentage:.2f}% and target is {target_pnl}% - closing position WIN")
        kill_switch(pos_sym, account)
    # If current PnL is below or equal to max_loss => close to prevent further losses
    elif pnl_percentage <= max_loss_pnl:
        logger.warning(f"PnL loss is {pnl_percentage:.2f}% and max loss is {max_loss_pnl}% - closing position LOSS")
        kill_switch(pos_sym, account)
    # Otherwise, keep position open
    else:
        logger.info(f"PnL is {pnl_percentage:.2f}% (target: {target_pnl}%, max loss: {max_loss_pnl}%) - not closing position")

    logger.info('Finished with PnL close')

# ─────────────────────────────────────────────────────────────────────────────
#  Example Usage / Main Execution Block
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    test_coin = 'BTC'  # Changed to BTC for testing
    test_target_pnl = 10.0  # 10% profit target
    test_max_loss_pnl = -5.0  # -5% stop loss

    logger.info(f"--- Testing Hyperliquid Bot Functions for {test_coin} ---")
    logger.info(f"Using {'TESTNET' if config.USE_TESTNET else 'MAINNET'}")

    # 1. Check Account Balance
    current_balance = acct_bal(account)
    if current_balance > 0:
        logger.info(f"Account balance is healthy: ${current_balance:.2f}")
    else:
        logger.error("Account balance is zero or could not be fetched.")

    # 2. Get Decimals
    sz_dec, px_dec = get_sz_px_decimals(test_coin)
    logger.info(f"'{test_coin}' has size decimals: {sz_dec}, price decimals: {px_dec}")

    # 3. Get Current Market Prices
    ask, bid, _ = ask_bid(test_coin)
    logger.info(f"'{test_coin}' Ask: {ask}, Bid: {bid}")

    # 4. Check position
    _, is_in_pos, size, pos_sym, entry_px, pnl_perc, is_long = get_position(test_coin, account)
    if is_in_pos:
        logger.info(f"Currently in position for {pos_sym}: Size={size}, Entry={entry_px}, PnL={pnl_perc:.2f}%")
    else:
        logger.info(f"No active position for {test_coin}.")

    logger.info("--- Hyperliquid Bot Functions Test Complete ---")