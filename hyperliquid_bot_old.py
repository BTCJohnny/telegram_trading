import do_not_share as d
import eth_account
import json
import time
import ccxt
import pandas as pd
import datetime
import schedule
import requests

from eth_account.signers import LocalAccount
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants

# Symbol to trade/monitor
symbol = 'WIF'

# ─────────────────────────────────────────────────────────────────────────────
#  1. FETCHING ASK/BID AND L2 DATA
# ─────────────────────────────────────────────────────────────────────────────
def ask_bid(symbol):
    """
    Fetches the current ask and bid price for the given symbol from Hyperliquid
    by requesting level 2 (L2) order book data.
    
    :param symbol: The trading pair (e.g., 'WIF') without 'USDT'
    :return: A tuple (ask, bid, l2_data), where:
        - ask = float, best ask (lowest sell price)
        - bid = float, best bid (highest buy price)
        - l2_data = complete L2 order book levels
    """
    url = 'https://api.hyperliquid.xyz/info'
    headers = {'Content-Type': 'application/json'}

    data = {
        'type': 'l2Book',
        'coin': symbol
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))
    l2_data = response.json()['levels']

    # L2 order book format: l2_data[0] is the bid side, l2_data[1] is the ask side
    bid = float(l2_data[0][0]['px'])
    ask = float(l2_data[1][0]['px'])

    return ask, bid, l2_data

# ─────────────────────────────────────────────────────────────────────────────
#  2. GET SIZE & PRICE DECIMALS
# ─────────────────────────────────────────────────────────────────────────────
def get_sz_px_decimals(coin):
    """
    Fetches the size and price decimal precision for the given coin. 
    Uses the 'meta' data from Hyperliquid, identifies the coin's entry,
    and deduces the price decimals from a sample ask price.
    
    :param coin: The symbol for which decimals are fetched.
    :return: A tuple (sz_decimals, px_decimals), representing
             the size decimals and price decimals, respectively.
    """
    url = 'https://api.hyperliquid.xyz/info'
    headers = {'Content-Type': 'application/json'}
    data = {'type': 'meta'}

    response = requests.post(url, headers=headers, data=json.dumps(data))

    if response.status_code == 200:
        data = response.json()
        symbols = data['universe']
        # Find the matching symbol dictionary
        symbol_info = next((s for s in symbols if s['name'] == symbol), None)
        if symbol_info:
            sz_decimals = symbol_info['szDecimals']
        else:
            print('symbol not found')
    else:
        print('Error:', response.status_code)
        # Provide a default if request fails
        sz_decimals = 0
    
    # Using ask_bid() to guess the number of decimals in the price
    ask = ask_bid(symbol)[0]
    ask_str = str(ask)
    if '.' in ask_str:
        px_decimals = len(ask_str.split('.')[1])
    else:
        px_decimals = 0

    print(f'{symbol} this is the price {sz_decimals} decimals')
    return sz_decimals, px_decimals

# ─────────────────────────────────────────────────────────────────────────────
#  3. PLACING A LIMIT ORDER
# ─────────────────────────────────────────────────────────────────────────────
def limit_order(coin, is_buy, sz, limit_px, reduce_only, account):
    """
    Places a limit order (buy or sell) on Hyperliquid via the provided account.

    :param coin: The symbol to trade (e.g., 'WIF').
    :param is_buy: Boolean, True if buy order, False if sell.
    :param sz: Position size (float).
    :param limit_px: The limit price (float).
    :param reduce_only: Boolean, True if the order should only reduce an existing position.
    :param account: A LocalAccount object or similar used for authentication.
    :return: The raw result from the exchange's order placement.
    """
    exchange = Exchange(account, constants.MAINNET_API_URL)

    # Round the size to the allowed decimal places
    rounding = get_sz_px_decimals(coin)[0]
    sz = round(sz, rounding)

    print(f'coin: {coin}, type: {type(coin)}')
    print(f'is_buy: {is_buy}, type: {type(coin)}')
    print(f'sz: {sz}, type: {type(limit_px)}')
    print(f'reduce_only: {reduce_only}, type: {type(reduce_only)}')

    print(f'placing limit order for {coin} {sz} @ {limit_px}')
    order_result = exchange.order(
        coin, 
        is_buy, 
        sz, 
        limit_px, 
        {"limit": {"tif": 'Gtc'}}, 
        reduce_only=reduce_only
    )

    # Print response for debugging
    if is_buy:
        print(f"limit BUY order placed thanks moon dev, resting: {order_result['response']['data']['statuses'][0]}")
    else:
        print(f"limit SELL order placed thanks moon dev, resting: {order_result['response']['data']['statuses'][0]}")

    return order_result

# ─────────────────────────────────────────────────────────────────────────────
#  4. CHECK ACCOUNT BALANCE
# ─────────────────────────────────────────────────────────────────────────────
def acct_bal(account):
    """
    Retrieves and prints the current account value (e.g., margin/collateral)
    from the Hyperliquid Info endpoint.

    :param account: An account object with .address attribute.
    :return: Account value (float).
    """
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    user_state = info.user_state(account.address)

    print(f'this is current account value: {user_state["marginSummary"]["accountValue"]}')
    acct_value = user_state["marginSummary"]["accountValue"]
    return acct_value

# ─────────────────────────────────────────────────────────────────────────────
#  5. GET POSITION DETAILS
# ─────────────────────────────────────────────────────────────────────────────
def get_position(symbol, account):
    """
    Retrieves position info for a specific symbol from the user's account.
    Determines if a position is open, whether it's long or short, and 
    calculates PnL as a percentage (return on equity).

    :param symbol: The symbol to check (e.g., 'WIF').
    :param account: Account object with .address.
    :return: A tuple (positions, im_in_pos, size, pos_sym, entry_px, pnl_perc, long):
        - positions: A list of matching positions
        - im_in_pos: Boolean, True if a position is open
        - size: float, the position size (positive for long, negative for short)
        - pos_sym: The symbol for the position
        - entry_px: The average entry price
        - pnl_perc: Return on equity percentage * 100
        - long: Boolean, True if long, False if short, None if no position
    """
    info = Info(constants.MAINNET_API_URL, skip_ws=True)
    user_state = info.user_state(account.address)

    print(f'this is current account value: {user_state["marginSummary"]["accountValue"]}')
    print(f'this is the symbol {symbol}')
    print(user_state["assetPositions"])

    positions = []
    # Iterate through all positions, looking for one matching this symbol
    for position in user_state["assetPositions"]:
        if (position["position"]["coin"] == symbol) and float(position["position"]["szi"]) != 0:
            positions.append(position["position"])
            in_pos = True
            size = float(position["position"]["szi"])       # Negative if short
            pos_sym = position["position"]["coin"]
            entry_px = float(position["position"]["entryPx"])
            pnl_perc = float(position["position"]["returnOnEquity"]) * 100
            print(f'this is the pnl perc {pnl_perc}')
            break
    else:
        # If no matching position found, default values
        in_pos = False
        size = 0
        pos_sym = None
        entry_px = 0
        pnl_perc = 0

    # Determine if the position is long or short based on size sign
    if size > 0:
        long = True
    elif size < 0:
        long = False
    else:
        long = None

    return positions, in_pos, size, pos_sym, entry_px, pnl_perc, long

# ─────────────────────────────────────────────────────────────────────────────
#  6. CANCEL ALL ORDERS
# ─────────────────────────────────────────────────────────────────────────────
def cancel_all_orders(account):
    """
    Fetches all open orders for the account and cancels them.
    Useful before adjusting positions, to avoid leftover orders.

    :param account: Account object with .address for authentication.
    """
    exchange = Exchange(account, constants.MAINNET_API_URL)
    info = Info(constants.MAINNET_API_URL, skip_ws=True)

    open_orders = info.open_orders(account.address)

    print('above are the open orders... need to cancel any...')
    for open_order in open_orders:
        # Cancel each open order by ID
        exchange.cancel(open_order['coin'], open_order['oid'])

# ─────────────────────────────────────────────────────────────────────────────
#  7. KILL SWITCH (IMMEDIATE POSITION EXIT)
# ─────────────────────────────────────────────────────────────────────────────
def kill_switch(symbol, account):
    """
    Closes any open position on the specified symbol by canceling 
    all open orders first, then placing a marketable order in 
    the opposite direction. Continues until position is zero.

    :param symbol: The symbol to close (e.g., 'WIF').
    :param account: Account object used for placing trades and cancellations.
    """
    position, im_in_pos, pos_size, pos_sym, entry_px, pnl_perc, long = get_position(symbol, account)

    # If currently in a position, keep trying to close it
    while im_in_pos:
        # Cancel existing open orders
        cancel_all_orders(account)

        # Get current best ask/bid from the order book
        ask, bid, l2 = ask_bid(symbol)

        # Make pos_size positive for the trade
        pos_size = abs(pos_size)

        # If currently long, sell at best ask
        if long:
            limit_order(pos_sym, False, pos_size, ask, True, account)
            print('kill switch - SELL TO CLOSE SUBMITTED ')
            time.sleep(5)
        # If currently short, buy at best bid
        elif long == False:
            limit_order(pos_sym, True, pos_size, bid, True, account)
            print('kill switch - BUY TO CLOSE SUBMITTED ')
            time.sleep(5)

        # Re-check position to see if fully closed yet
        position, im_in_pos, pos_size, pos_sym, entry_px, pnl_perc, long = get_position(symbol, account)

    print('position successfully closed in the kill switch')

# ─────────────────────────────────────────────────────────────────────────────
#  8. PNL-BASED POSITION CLOSING
# ─────────────────────────────────────────────────────────────────────────────
def pnl_close(symbol, target, max_loss, account):
    """
    Monitors the open position's PnL percentage (pnl_perc).
    - If pnl_perc > target, closes the position (take profit).
    - If pnl_perc <= max_loss, closes the position (stop loss).
    - Otherwise, does nothing.

    :param symbol: The symbol to monitor (e.g., 'WIF').
    :param target: Float, PnL percentage threshold to take profit.
    :param max_loss: Float, PnL percentage threshold to trigger a stop loss.
    :param account: Authentication/account object for trade actions.
    """
    print('starting pnl close')
    position, im_in_pos, pos_size, pos_sym, entry_px, pnl_perc, long = get_position(symbol, account)

    # Check if current PnL is above target => close for profit
    if pnl_perc > target:
        print(f'pnl gain is {pnl_perc} and target is {target}... closing position WIN')
        kill_switch(pos_sym, account)

    # If current PnL is below or equal to max_loss => close to prevent further losses
    elif pnl_perc <= max_loss:
        print(f'pnl loss is {pnl_perc} and max loss is {max_loss}... closing position LOSS')
        kill_switch(pos_sym, account)

    # Otherwise, keep position open
    else:
        print(f'pnl loss is {pnl_perc} and max loss is {max_loss} and target {target}... not closing position')

    print('finished with pnl close')
