#!/usr/bin/env python3
"""
Test Trade Script - BTC Long Position
Tests the full trading pipeline: open position -> wait -> close position
"""

import time
import json
import logging
from eth_account import Account
import requests

from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
import config as d

# --- Configuration -----------------------------------------------------------
# Use the TESTNET endpoint for safety
API_URL = constants.TESTNET_API_URL  # Reverted to testnet for safety

# Instantiate your account from your private key\account: Account = Account.from_key(d.HYPERLIQUID_SECRET_KEY)
account = Account.from_key(d.HYPERLIQUID_SECRET_KEY)

# Set up logging
tlogging = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Trading utility functions -----------------------------------------------
def ask_bid(symbol):
    """
    Fetches the current ask and bid for the symbol from Hyperliquid.
    Returns (ask, bid, full_l2_book).
    """
    url = f"{API_URL}/info"
    headers = {'Content-Type': 'application/json'}
    payload = {'type': 'l2Book', 'coin': symbol}

    logger.info(f"ask_bid: hitting URL → {url}")

    resp = requests.post(url, headers=headers, data=json.dumps(payload))

    # --- Error handling starts here ---
    # Check if the response from the API is successful (HTTP 200)
    if resp.status_code == 200:
        try:
            # Try to parse the response as JSON
            json_data = resp.json()
        except Exception as e:
            # Log an error if JSON parsing fails
            logger.error(f"Failed to parse JSON: {e}, response text: {resp.text}")
            return 0, 0, []
        # Ensure json_data is not None before checking for 'levels'
        if not json_data or 'levels' not in json_data:
            logger.error(f"'levels' not in response: {json_data}")
            return 0, 0, []
        data = json_data['levels']
        try:
            # Try to extract bid and ask prices from the data
            bid = float(data[0][0]['px'])
            ask = float(data[1][0]['px'])
        except Exception as e:
            # Log an error if extraction fails
            logger.error(f"Error extracting ask/bid: {e}, data: {data}")
            return 0, 0, data
        return ask, bid, data
    else:
        # Log an error if the API did not return a successful response
        logger.error(f"Error from API: {resp.status_code}, response: {resp.text}")
        return 0, 0, []


def get_sz_px_decimals(coin):
    """
    Retrieves the size and price decimals for the coin via the /info meta endpoint.
    """
    url = f"{API_URL}/info"
    headers = {'Content-Type': 'application/json'}
    payload = {'type': 'meta'}
    resp = requests.post(url, headers=headers, data=json.dumps(payload))
    meta = resp.json().get('meta', [])

    # Find entry in meta list
    for entry in meta:
        if entry.get('symbol') == coin:
            sz_decimals = entry['sizeDecimals']
            break
    else:
        sz_decimals = 0

    # Estimate price decimals via string parsing
    ask_price = ask_bid(coin)[0]
    ask_str = str(ask_price)
    px_decimals = len(ask_str.split('.')[1]) if '.' in ask_str else 0
    return sz_decimals, px_decimals


def limit_order(coin, is_buy, sz, limit_px, reduce_only, account):
    """
    Places a limit order on Hyperliquid.
    """
    exchange = Exchange(account, API_URL)
    sz_decimals, _ = get_sz_px_decimals(coin)
    sz = round(sz, sz_decimals)

    result = exchange.order(
        coin,
        is_buy,
        sz,
        limit_px,
        {'limit': {'tif': 'Gtc'}},
        reduce_only=reduce_only
    )

    status = result['response']['data']['statuses'][0]
    side = 'BUY' if is_buy else 'SELL'
    logger.info(f"Limit {side} order placed: {status}")
    return result


def acct_bal(account):
    """
    Returns current account value (margin/collateral) as float.
    """
    info = Info(API_URL, skip_ws=True)
    state = info.user_state(account.address)
    val = float(state['marginSummary']['accountValue'])
    logger.info(f"Account value: ${val}")
    return val


def get_position(symbol, account):
    """
    Retrieves open positions for symbol.
    Returns (positions, in_pos, size, sym, entry_px, pnl_perc, is_long)
    """
    info = Info(API_URL, skip_ws=True)
    state = info.user_state(account.address)

    positions = []
    in_pos = False
    size = 0
    pos_sym = None
    entry_px = 0
    pnl_perc = 0

    for pos in state['assetPositions']:
        p = pos['position']
        if p['coin'] == symbol and float(p['szi']) != 0:
            positions.append(p)
            in_pos = True
            size = float(p['szi'])
            pos_sym = p['coin']
            entry_px = float(p['entryPx'])
            pnl_perc = float(p['returnOnEquity']) * 100
            break

    is_long = True if size > 0 else False if size < 0 else None
    logger.info(f"Position check - In pos: {in_pos}, Size: {size}, PnL%: {pnl_perc}")
    return positions, in_pos, size, pos_sym, entry_px, pnl_perc, is_long


def cancel_all_orders(account):
    """
    Cancels all open orders.
    """
    exchange = Exchange(account, API_URL)
    info = Info(API_URL, skip_ws=True)
    open_orders = info.open_orders(account.address)
    for o in open_orders:
        exchange.cancel(o['coin'], o['oid'])
        logger.info(f"Canceled order {o['oid']} on {o['coin']}")


def kill_switch(symbol, account):
    """
    Force-close any open position for symbol.
    """
    _, in_pos, pos_size, _, _, _, is_long = get_position(symbol, account)
    while in_pos:
        cancel_all_orders(account)
        ask, bid, _ = ask_bid(symbol)
        qty = abs(pos_size)
        if is_long:
            limit_order(symbol, False, qty, ask, True, account)
        else:
            limit_order(symbol, True, qty, bid, True, account)
        time.sleep(5)
        _, in_pos, pos_size, _, _, _, is_long = get_position(symbol, account)
    logger.info("Position closed via kill switch.")


def pnl_close(symbol, target, max_loss, account):
    """
    Close position based on PnL thresholds.
    """
    _, in_pos, _, _, _, pnl, _ = get_position(symbol, account)
    if pnl > target:
        logger.info(f"Take profit: PnL {pnl}% > {target}%")
        kill_switch(symbol, account)
    elif pnl <= max_loss:
        logger.info(f"Stop loss: PnL {pnl}% <= {max_loss}%")
        kill_switch(symbol, account)
    else:
        logger.info(f"PnL {pnl}% within thresholds.")

# --- Test script logic -------------------------------------------------------

def pre_trade_checks():
    """Run safety checks before executing the test trade."""
    logger.info("🔍 Running pre-trade safety checks...")
    if "testnet" not in API_URL.lower():
        logger.error("❌ NOT ON TESTNET! Aborting for safety.")
        return False
    logger.info("✅ Confirmed on TESTNET")
    balance = acct_bal(account)
    if balance < 20:
        logger.error(f"❌ Insufficient balance: ${balance}. Need at least $20 for test.")
        return False
    logger.info(f"✅ Sufficient balance: ${balance}")
    return True


def test_btc_trade():
    """Execute a test BTC long trade: open -> wait -> close."""
    coin = "BTC"
    test_size_usd = 20
    wait_seconds = 10

    logger.info("🚀 Starting BTC Test Trade")
    logger.info("=" * 50)

    # Step 1: Balance check
    logger.info("📊 Step 1: Checking account balance...")
    if acct_bal(account) <= 0:
        logger.error("❌ Account balance is $0. Please fund testnet.")
        return False

    # Step 2: Market data
    logger.info("📈 Step 2: Getting market data...")
    ask, bid, _ = ask_bid(coin)
    if ask == 0 or bid == 0:
        logger.error(f"❌ Could not fetch prices for {coin}")
        return False
    mid = (ask + bid) / 2
    trade_size = round(test_size_usd / mid, get_sz_px_decimals(coin)[0])

    # Step 3: Ensure no existing position
    _, in_pos, _, _, _, _, _ = get_position(coin, account)
    if in_pos:
        logger.warning("⚠️ Existing position found. Closing first.")
        kill_switch(coin, account)
        time.sleep(3)

    # Step 4: Place long
    logger.info("📈 Step 4: Placing BTC LONG order...")
    entry_price = ask + 0.01
    result = limit_order(coin, True, trade_size, entry_price, False, account)
    if not result or 'error' in result:
        logger.error(f"❌ Failed to place long order: {result}")
        return False
    logger.info("✅ Long order placed.")

    # Step 5: Wait for fill
    logger.info("⏳ Step 5: Waiting for fill...")
    time.sleep(wait_seconds)

    # Step 6: Verify position
    _, in_pos, sz, _, entry, pnl, _ = get_position(coin, account)
    if not in_pos:
        logger.error("❌ Position did not open as expected.")
        return False
    logger.info(f"✅ Position open: Size={sz}, Entry=${entry:.2f}, PnL={pnl:.2f}%")

    # Step 7: Final PnL report
    logger.info("📊 Step 7: Checking final PnL...")
    _, _, _, _, _, final_pnl, _ = get_position(coin, account)
    logger.info(f"📈 Final PnL: {final_pnl:.2f}%")

    # Step 8: Close position
    logger.info("🔒 Step 8: Closing position...")
    kill_switch(coin, account)

    # Step 9: Confirm closure
    time.sleep(3)
    _, in_pos, _, _, _, _, _ = get_position(coin, account)
    if not in_pos:
        logger.info("✅ Position successfully closed!")
        return True
    logger.error("❌ Position still open after kill switch.")
    return False


if __name__ == "__main__":
    # --- Quick ask_bid test ------------------------------------------------------
    # This block tests the ask_bid function and exits immediately after.
    try:
        ask, bid, book = ask_bid("BTC-USD")
        logger.info(f"🔍 ask_bid Test → Ask: {ask}, Bid: {bid}")
    except Exception as e:
        logger.error(f"ask_bid test failed: {e}")
    # Exit immediately after test
    exit(0)

    logger.info("🧪 BTC Test Trade Script Starting...")
    if not pre_trade_checks():
        logger.error("❌ Pre-trade checks failed. Exiting.")
        exit(1)

    try:
        success = test_btc_trade()
        if success:
            logger.info("🎉 Test completed! Your bot can trade successfully.")
        else:
            logger.error("❌ Test failed. Check logs for details.")
    except Exception as e:
        logger.exception(f"❌ Test failed with exception: {e}")
    logger.info("🧪 Test script finished.")
