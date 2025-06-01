#!/usr/bin/env python3
"""
Standalone Test Trade Script - No Config Dependencies
Tests the hyperliquid API functions directly without relying on config.py
"""

import sys
import os
import time
import logging
import json
import requests
from hyperliquid.utils import constants
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from eth_account import Account
from dotenv import load_dotenv

# ═══════════════════════════════════════════════════════════════════════════════
# 🚨 SAFETY FLAG: SET TO TRUE FOR TESTNET, FALSE FOR MAINNET 🚨
# ═══════════════════════════════════════════════════════════════════════════════
USE_TESTNET = True  # 🔄 CHANGE THIS TO False FOR MAINNET (NOT RECOMMENDED!)
# ═══════════════════════════════════════════════════════════════════════════════

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
HYPERLIQUID_SECRET_KEY = os.getenv("HYPERLIQUID_SECRET_KEY")

if not HYPERLIQUID_SECRET_KEY:
    logger.error("❌ HYPERLIQUID_SECRET_KEY not found in .env file")
    exit(1)

# Initialize account
account = Account.from_key(HYPERLIQUID_SECRET_KEY)
logger.info(f"Account initialized: {account.address}")

# Set API URL based on testnet flag
API_URL = constants.TESTNET_API_URL if USE_TESTNET else constants.MAINNET_API_URL

# ═══════════════════════════════════════════════════════════════════════════════
# 🔒 SAFETY CHECKS
# ═══════════════════════════════════════════════════════════════════════════════

if not USE_TESTNET:
    print("❌ DANGER: USE_TESTNET is False - this would trade on MAINNET!")
    print("❌ Set USE_TESTNET = True at the top of this file.")
    exit(1)

if "testnet" not in API_URL.lower():
    logger.error("❌ CRITICAL: API URL does not contain 'testnet' - ABORTING!")
    exit(1)

logger.info("🛡️  SAFETY CONFIRMATION:")
logger.info(f"   USE_TESTNET: {USE_TESTNET}")
logger.info(f"   API URL: {API_URL}")
logger.info(f"   Account: {account.address}")
logger.info("✅ Safety checks passed - confirmed TESTNET usage")

# ═══════════════════════════════════════════════════════════════════════════════
# 🔧 TRADING FUNCTIONS (Standalone versions)
# ═══════════════════════════════════════════════════════════════════════════════

def ask_bid(coin: str) -> tuple[float, float, list]:
    """Get current ask/bid prices"""
    url = f"{API_URL}/info"
    headers = {'Content-Type': 'application/json'}
    data = {'type': 'l2Book', 'coin': coin}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        l2_data = response.json()['levels']

        bid = float(l2_data[0][0]['px'])
        ask = float(l2_data[1][0]['px'])
        return ask, bid, l2_data
    except Exception as e:
        logger.error(f"Error fetching L2 book for {coin}: {e}")
        return 0.0, 0.0, []

def get_sz_px_decimals(coin: str) -> tuple[int, int]:
    """Get size and price decimals"""
    url = f"{API_URL}/info"
    headers = {'Content-Type': 'application/json'}
    data = {'type': 'meta'}

    try:
        response = requests.post(url, headers=headers, data=json.dumps(data))
        response.raise_for_status()
        meta_data = response.json()
        symbols = meta_data['universe']

        symbol_info = next((s for s in symbols if s['name'] == coin), None)
        sz_decimals = symbol_info['szDecimals'] if symbol_info else 2

        ask, _, _ = ask_bid(coin)
        ask_str = str(ask)
        px_decimals = len(ask_str.split('.')[1]) if '.' in ask_str else 0

        return sz_decimals, px_decimals
    except Exception as e:
        logger.error(f"Error fetching decimals for {coin}: {e}")
        return 2, 2

def limit_order(coin: str, is_buy: bool, sz: float, limit_px: float, reduce_only: bool):
    """Place a limit order"""
    exchange = Exchange(account, API_URL)
    sz_decimals, _ = get_sz_px_decimals(coin)
    sz_rounded = round(sz, sz_decimals)

    logger.info(f"Placing {'BUY' if is_buy else 'SELL'} {sz_rounded} {coin} @ ${limit_px} (reduce_only={reduce_only})")

    try:
        result = exchange.order(
            coin, is_buy, sz_rounded, limit_px,
            {"limit": {"tif": 'Gtc'}}, reduce_only=reduce_only
        )
        status = result['response']['data']['statuses'][0]
        logger.info(f"Order placed: {status}")
        return result
    except Exception as e:
        logger.error(f"Error placing order: {e}")
        return {"error": str(e)}

def acct_bal() -> float:
    """Get account balance"""
    info = Info(API_URL, skip_ws=True)
    try:
        user_state = info.user_state(account.address)
        balance = float(user_state["marginSummary"]["accountValue"])
        logger.info(f"Account balance: ${balance}")
        return balance
    except Exception as e:
        logger.error(f"Error fetching balance: {e}")
        return 0.0

def get_position(coin: str) -> tuple:
    """Get position info"""
    info = Info(API_URL, skip_ws=True)
    try:
        user_state = info.user_state(account.address)
        
        for asset_position in user_state.get("assetPositions", []):
            position = asset_position.get("position", {})
            if (position.get("coin") == coin) and float(position.get("szi", 0)) != 0:
                size = float(position["szi"])
                entry_price = float(position["entryPx"])
                pnl_percentage = float(position["returnOnEquity"]) * 100
                is_long = size > 0
                logger.info(f"Position: {coin} size={size}, entry=${entry_price}, PnL={pnl_percentage:.2f}%")
                return True, size, entry_price, pnl_percentage, is_long
        
        logger.info(f"No position found for {coin}")
        return False, 0.0, 0.0, 0.0, None
    except Exception as e:
        logger.error(f"Error fetching position: {e}")
        return False, 0.0, 0.0, 0.0, None

def cancel_all_orders():
    """Cancel all open orders"""
    exchange = Exchange(account, API_URL)
    info = Info(API_URL, skip_ws=True)
    
    try:
        open_orders = info.open_orders(account.address)
        for order in open_orders:
            exchange.cancel(order['coin'], order['oid'])
            logger.info(f"Cancelled order {order['oid']} for {order['coin']}")
    except Exception as e:
        logger.error(f"Error cancelling orders: {e}")

def kill_switch(coin: str):
    """Close any open position"""
    logger.info(f"Activating kill switch for {coin}...")
    
    while True:
        is_in_position, pos_size, _, _, is_long = get_position(coin)
        
        if not is_in_position or abs(pos_size) < 1e-9:
            logger.info(f"Position for {coin} successfully closed")
            break
            
        cancel_all_orders()
        ask, bid, _ = ask_bid(coin)
        abs_pos_size = abs(pos_size)
        
        if is_long:
            logger.info(f"Selling {abs_pos_size} {coin} at {ask}")
            limit_order(coin, False, abs_pos_size, ask, True)
        else:
            logger.info(f"Buying {abs_pos_size} {coin} at {bid}")
            limit_order(coin, True, abs_pos_size, bid, True)
            
        time.sleep(5)

# ═══════════════════════════════════════════════════════════════════════════════
# 🧪 TEST TRADE EXECUTION
# ═══════════════════════════════════════════════════════════════════════════════

def test_btc_trade():
    """Execute test BTC trade"""
    coin = "BTC"
    size_usd = 20
    
    logger.info("🚀 Starting Standalone BTC Test Trade")
    logger.info("=" * 60)
    
    # Check balance
    balance = acct_bal()
    if balance < 20:
        logger.error(f"❌ Insufficient balance: ${balance}")
        return False
    
    # Get market data
    ask, bid, _ = ask_bid(coin)
    if ask == 0 or bid == 0:
        logger.error(f"❌ Could not get prices for {coin}")
        return False
    
    mid_price = (ask + bid) / 2
    sz_decimals, _ = get_sz_px_decimals(coin)
    trade_size = round(size_usd / mid_price, sz_decimals)
    
    logger.info(f"BTC prices: Ask=${ask}, Bid=${bid}")
    logger.info(f"Trade size: {trade_size} BTC")
    
    # Close any existing position
    is_in_pos, _, _, _, _ = get_position(coin)
    if is_in_pos:
        logger.info("Closing existing position...")
        kill_switch(coin)
        time.sleep(3)
    
    # Place buy order
    logger.info("Placing BUY order...")
    buy_result = limit_order(coin, True, trade_size, bid, False)
    if "error" in buy_result:
        logger.error(f"❌ Buy order failed: {buy_result}")
        return False
    
    # Wait
    logger.info("Waiting 10 seconds...")
    time.sleep(10)
    
    # Check position
    is_in_pos, size, entry, pnl, is_long = get_position(coin)
    if is_in_pos:
        logger.info(f"✅ Position opened: {size} BTC @ ${entry}, PnL={pnl:.2f}%")
    
    # Place sell order
    logger.info("Placing SELL order...")
    sell_result = limit_order(coin, False, trade_size, ask, True)
    
    # Wait and cleanup
    time.sleep(5)
    logger.info("Running kill switch for cleanup...")
    kill_switch(coin)
    
    logger.info("✅ Test trade completed!")
    return True

if __name__ == "__main__":
    logger.info("🧪 Standalone Test Trade Starting...")
    
    # Test API connection first
    try:
        ask, bid, _ = ask_bid("BTC")
        logger.info(f"✅ API test successful: BTC Ask=${ask}, Bid=${bid}")
    except Exception as e:
        logger.error(f"❌ API test failed: {e}")
        exit(1)
    
    # Confirm with user
    print("\n" + "="*60)
    print("⚠️  STANDALONE TEST TRADE")
    print("   🟢 TESTNET (Safe)")
    print("   📊 $20 BTC buy → wait → sell → cleanup")
    print("="*60)
    
    confirm = input("Continue? (y/N): ")
    if confirm.lower() != 'y':
        exit(0)
    
    # Run test
    try:
        success = test_btc_trade()
        if success:
            logger.info("🎉 Standalone test completed successfully!")
        else:
            logger.error("❌ Test failed")
    except Exception as e:
        logger.exception(f"❌ Test failed: {e}")