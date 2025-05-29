# bot_core/telegram_interface.py - Enhanced Telegram Message Processing

import re
import logging
from datetime import datetime, date

from .hyperliquid_api import get_position, ask_bid, account
from .strategy_manager import (
    handle_bullish_entry_signal,
    handle_bearish_entry_signal,
    handle_telegram_exit_signal
)
from .trade_persistence import TradeMonitorDB, parse_portfolio_position
from .utils import setup_module_logger
import config

logger = setup_module_logger(__name__)

class TelegramMessageProcessor:
    """Enhanced message processor for AITA trading signals."""
    
    def __init__(self, db_manager: TradeMonitorDB):
        self.db_manager = db_manager
        self._setup_regex_patterns()

    def _setup_regex_patterns(self):
        """Setup regex patterns for different message types."""
        
        # Entry Signal Patterns
        self.bullish_entry_pattern = re.compile(
            r'🪙\s*\*\*([A-Z0-9]+)\*\*:\s*Entry\s*@\s*\$([0-9.,]+),\s*Size:\s*(\d+)/(\d+)',
            re.IGNORECASE
        )
        
        self.bearish_entry_pattern = re.compile(
            r'🪙\s*\*\*([A-Z0-9]+)\*\*:\s*Entry\s*@\s*\$([0-9.,]+),\s*Size:\s*(\d+)/(\d+)',
            re.IGNORECASE
        )
        
        # Exit Signal Patterns
        self.exit_signal_pattern = re.compile(
            r'🟢\s*\*\*([A-Z0-9]+)\*\*:\s*Closed\s*@\s*\$([0-9.,]+)\s*\(Entry:\s*\$([0-9.,]+)\),\s*Return:\s*([0-9.-]+)%',
            re.IGNORECASE
        )
        
        # Portfolio Section Patterns
        self.bullish_portfolio_pattern = re.compile(
            r'💼\s*\*\*Current Bullish Portfolio.*?\*\*',
            re.DOTALL | re.IGNORECASE
        )
        
        self.bearish_portfolio_pattern = re.compile(
            r'💼\s*\*\*Current Bearish Portfolio.*?\*\*',
            re.DOTALL | re.IGNORECASE
        )
        
        # Individual portfolio position pattern
        self.portfolio_position_pattern = re.compile(
            r'\*\*([A-Z0-9]+)\s*\([B]\):\*\*\s*\n\s*-\s*Entry Date:\s*(\d{4}-\d{2}-\d{2})\s*\n\s*-\s*Entry Price:\s*\$([0-9.,]+)\s*\n\s*-\s*Current Price:\s*\$([0-9.,]+)\s*\(🟢([0-9.-]+)%\)\s*\n\s*-\s*Size:\s*(\d+/\d+)',
            re.MULTILINE | re.IGNORECASE
        )
        
        # Trade Summary Section Patterns
        self.bullish_entries_section = re.compile(
            r'✅\s*\*\*Today\'s Bullish Entries:\*\*\s*(.*?)(?=❌|\n\n|$)',
            re.DOTALL | re.IGNORECASE
        )
        
        self.bearish_entries_section = re.compile(
            r'✅\s*\*\*Today\'s Bearish Entries:\*\*\s*(.*?)(?=❌|\n\n|$)',
            re.DOTALL | re.IGNORECASE
        )
        
        self.bullish_exits_section = re.compile(
            r'❌\s*\*\*Today\'s Bullish Exits:\*\*\s*(.*?)(?=💼|\n\n|$)',
            re.DOTALL | re.IGNORECASE
        )
        
        self.bearish_exits_section = re.compile(
            r'❌\s*\*\*Today\'s Bearish Exits:\*\*\s*(.*?)(?=💼|\n\n|$)',
            re.DOTALL | re.IGNORECASE
        )

    def process_message(self, message_text: str) -> dict:
        """Main message processing function."""
        logger.info(f"Processing message: {message_text[:100]}...")
        
        results = {
            'entries_processed': 0,
            'exits_processed': 0,
            'portfolios_updated': 0,
            'signals_recorded': 0,
            'errors': []
        }
        
        try:
            # Check for different message types and process accordingly
            
            # 1. Process Entry Signals
            results.update(self._process_entry_signals(message_text))
            
            # 2. Process Exit Signals  
            results.update(self._process_exit_signals(message_text))
            
            # 3. Process Portfolio Updates
            results.update(self._process_portfolio_updates(message_text))
            
            logger.info(f"Message processing complete: {results}")
            return results
            
        except Exception as e:
            logger.error(f"Error processing message: {e}", exc_info=True)
            results['errors'].append(str(e))
            return results

    def _process_entry_signals(self, message_text: str) -> dict:
        """Process bullish and bearish entry signals."""
        results = {'entries_processed': 0, 'signals_recorded': 0}
        
        # Check for bullish entries section
        bullish_section = self.bullish_entries_section.search(message_text)
        if bullish_section:
            entries_text = bullish_section.group(1)
            if "No Bullish entries today" not in entries_text:
                results.update(self._process_bullish_entries(entries_text))
        
        # Check for bearish entries section
        bearish_section = self.bearish_entries_section.search(message_text)
        if bearish_section:
            entries_text = bearish_section.group(1)
            if "No Bearish entries today" not in entries_text:
                results.update(self._process_bearish_entries(entries_text))
        
        return results

    def _process_bullish_entries(self, entries_text: str) -> dict:
        """Process bullish entry signals."""
        results = {'entries_processed': 0, 'signals_recorded': 0}
        
        for match in self.bullish_entry_pattern.finditer(entries_text):
            try:
                symbol = match.group(1).strip()
                entry_price = float(match.group(2).replace(',', ''))
                size_numerator = int(match.group(3))
                size_denominator = int(match.group(4))
                size_confidence = f"{size_numerator}/{size_denominator}"
                
                logger.info(f"Found bullish entry signal: {symbol} @ ${entry_price:.4f}, Size: {size_confidence}")
                
                # Record the signal
                signal_id = self.db_manager.add_signal_record(
                    'entry', symbol, 'bullish', entry_price, 
                    size_confidence=size_confidence
                )
                results['signals_recorded'] += 1
                
                # Check if we should execute this trade
                if self._should_execute_trade(symbol, True):
                    trade_result = handle_bullish_entry_signal(
                        symbol, entry_price, size_numerator, size_denominator,
                        account, self.db_manager.add_trade
                    )
                    
                    if trade_result.get('status') == 'success':
                        # Update signal record with execution info
                        trade_id = trade_result.get('trade_id')
                        if trade_id:
                            # Update signal record to mark as executed
                            conn = self.db_manager._get_db_connection()
                            cursor = conn.cursor()
                            cursor.execute(
                                'UPDATE signal_history SET executed = 1, trade_id = ? WHERE id = ?',
                                (trade_id, signal_id)
                            )
                            conn.commit()
                            conn.close()
                        
                        results['entries_processed'] += 1
                        logger.info(f"Successfully executed bullish entry for {symbol}")
                    else:
                        logger.warning(f"Failed to execute bullish entry for {symbol}: {trade_result.get('reason')}")
                else:
                    logger.info(f"Skipping bullish entry for {symbol} - already have position or other condition")
                
            except Exception as e:
                logger.error(f"Error processing bullish entry signal: {e}")
        
        return results

    def _process_bearish_entries(self, entries_text: str) -> dict:
        """Process bearish entry signals."""
        results = {'entries_processed': 0, 'signals_recorded': 0}
        
        for match in self.bearish_entry_pattern.finditer(entries_text):
            try:
                symbol = match.group(1).strip()
                entry_price = float(match.group(2).replace(',', ''))
                size_numerator = int(match.group(3))
                size_denominator = int(match.group(4))
                size_confidence = f"{size_numerator}/{size_denominator}"
                
                logger.info(f"Found bearish entry signal: {symbol} @ ${entry_price:.4f}, Size: {size_confidence}")
                
                # Record the signal
                signal_id = self.db_manager.add_signal_record(
                    'entry', symbol, 'bearish', entry_price,
                    size_confidence=size_confidence
                )
                results['signals_recorded'] += 1
                
                # Check if we should execute this trade
                if self._should_execute_trade(symbol, False):
                    trade_result = handle_bearish_entry_signal(
                        symbol, entry_price, size_numerator, size_denominator,
                        account, self.db_manager.add_trade
                    )
                    
                    if trade_result.get('status') == 'success':
                        # Update signal record with execution info
                        trade_id = trade_result.get('trade_id')
                        if trade_id:
                            conn = self.db_manager._get_db_connection()
                            cursor = conn.cursor()
                            cursor.execute(
                                'UPDATE signal_history SET executed = 1, trade_id = ? WHERE id = ?',
                                (trade_id, signal_id)
                            )
                            conn.commit()
                            conn.close()
                        
                        results['entries_processed'] += 1
                        logger.info(f"Successfully executed bearish entry for {symbol}")
                    else:
                        logger.warning(f"Failed to execute bearish entry for {symbol}: {trade_result.get('reason')}")
                else:
                    logger.info(f"Skipping bearish entry for {symbol} - already have position or other condition")
                
            except Exception as e:
                logger.error(f"Error processing bearish entry signal: {e}")
        
        return results

    def _process_exit_signals(self, message_text: str) -> dict:
        """Process exit signals from both bullish and bearish sections."""
        results = {'exits_processed': 0, 'signals_recorded': 0}
        
        # Check bullish exits section
        bullish_exits = self.bullish_exits_section.search(message_text)
        if bullish_exits:
            exits_text = bullish_exits.group(1)
            if "No Bullish exits today" not in exits_text:
                exit_results = self._process_exit_signals_in_text(exits_text, 'bullish')
                results['exits_processed'] += exit_results['exits_processed']
                results['signals_recorded'] += exit_results['signals_recorded']
        
        # Check bearish exits section
        bearish_exits = self.bearish_exits_section.search(message_text)
        if bearish_exits:
            exits_text = bearish_exits.group(1)
            if "No Bearish exits today" not in exits_text:
                exit_results = self._process_exit_signals_in_text(exits_text, 'bearish')
                results['exits_processed'] += exit_results['exits_processed']
                results['signals_recorded'] += exit_results['signals_recorded']
        
        return results

    def _process_exit_signals_in_text(self, exits_text: str, direction: str) -> dict:
        """Process exit signals in given text."""
        results = {'exits_processed': 0, 'signals_recorded': 0}
        
        for match in self.exit_signal_pattern.finditer(exits_text):
            try:
                symbol = match.group(1).strip()
                exit_price = float(match.group(2).replace(',', ''))
                entry_price = float(match.group(3).replace(',', ''))
                return_pct = float(match.group(4))
                
                logger.info(f"Found {direction} exit signal: {symbol} closed @ ${exit_price:.4f}, Return: {return_pct:.2f}%")
                
                # Record the exit signal
                signal_id = self.db_manager.add_signal_record(
                    'exit', symbol, direction, entry_price, exit_price,
                    return_percentage=return_pct
                )
                results['signals_recorded'] += 1
                
                # Attempt to close our position if we have one
                position_type_str = "long" if direction == 'bullish' else "short"
                exit_result = handle_telegram_exit_signal(
                    symbol, position_type_str, account,
                    self.db_manager.find_and_update_trade_by_coin_and_type
                )
                
                if exit_result.get('status') == 'success':
                    results['exits_processed'] += 1
                    logger.info(f"Successfully executed {direction} exit for {symbol}")
                else:
                    logger.info(f"Exit signal for {symbol} processed but no position to close: {exit_result.get('reason')}")
                
            except Exception as e:
                logger.error(f"Error processing {direction} exit signal: {e}")
        
        return results

    def _process_portfolio_updates(self, message_text: str) -> dict:
        """Process portfolio snapshot updates."""
        results = {'portfolios_updated': 0}
        
        try:
            # Extract date from message (assuming it's in the format)
            date_match = re.search(r'(\d{4}-\d{2}-\d{2})', message_text)
            snapshot_date = date_match.group(1) if date_match else date.today().isoformat()
            
            # Process bullish portfolio
            if "Current Bullish Portfolio" in message_text:
                bullish_positions = self._extract_portfolio_positions(message_text, 'bullish')
                if bullish_positions:
                    snapshot_id = self.db_manager.add_portfolio_snapshot(
                        snapshot_date, 'bullish', bullish_positions
                    )
                    if snapshot_id > 0:
                        results['portfolios_updated'] += 1
                        logger.info(f"Updated bullish portfolio: {len(bullish_positions)} positions")
            
            # Process bearish portfolio
            if "Current Bearish Portfolio" in message_text:
                bearish_positions = self._extract_portfolio_positions(message_text, 'bearish')
                if bearish_positions:
                    snapshot_id = self.db_manager.add_portfolio_snapshot(
                        snapshot_date, 'bearish', bearish_positions
                    )
                    if snapshot_id > 0:
                        results['portfolios_updated'] += 1
                        logger.info(f"Updated bearish portfolio: {len(bearish_positions)} positions")
        
        except Exception as e:
            logger.error(f"Error processing portfolio updates: {e}")
        
        return results

    def _extract_portfolio_positions(self, message_text: str, portfolio_type: str) -> list:
        """Extract individual positions from portfolio section."""
        positions = []
        
        try:
            # Find the portfolio section
            if portfolio_type == 'bullish':
                section_match = re.search(
                    r'💼\s*\*\*Current Bullish Portfolio.*?\*\*:(.*?)(?=💼|📅|$)', 
                    message_text, re.DOTALL | re.IGNORECASE
                )
            else:
                section_match = re.search(
                    r'💼\s*\*\*Current Bearish Portfolio.*?\*\*:(.*?)(?=💼|📅|$)', 
                    message_text, re.DOTALL | re.IGNORECASE
                )
            
            if not section_match:
                return positions
            
            portfolio_text = section_match.group(1)
            
            # Find all individual position blocks
            position_blocks = re.findall(
                r'\*\*([A-Z0-9]+)\s*\([B]\):\*\*\s*(.*?)(?=\*\*[A-Z0-9]+|\Z)',
                portfolio_text, re.DOTALL
            )
            
            for coin, position_details in position_blocks:
                try:
                    # Parse position details
                    entry_date_match = re.search(r'Entry Date:\s*(\d{4}-\d{2}-\d{2})', position_details)
                    entry_price_match = re.search(r'Entry Price:\s*\$([0-9.,]+)', position_details)
                    current_price_match = re.search(r'Current Price:\s*\$([0-9.,]+)', position_details)
                    pnl_match = re.search(r'🟢([0-9.-]+)%', position_details)
                    size_match = re.search(r'Size:\s*(\d+/\d+)', position_details)
                    
                    if all([entry_date_match, entry_price_match, current_price_match, pnl_match, size_match]):
                        position = {
                            'coin': coin,
                            'entry_date': entry_date_match.group(1),
                            'entry_price': float(entry_price_match.group(1).replace(',', '')),
                            'current_price': float(current_price_match.group(1).replace(',', '')),
                            'pnl_percentage': float(pnl_match.group(1)),
                            'size_confidence': size_match.group(1)
                        }
                        positions.append(position)
                        logger.debug(f"Parsed {portfolio_type} position: {coin} @ ${position['entry_price']:.4f}")
                    else:
                        logger.warning(f"Could not parse all details for {coin} in {portfolio_type} portfolio")
                        
                except Exception as e:
                    logger.error(f"Error parsing position for {coin}: {e}")
                    continue
        
        except Exception as e:
            logger.error(f"Error extracting {portfolio_type} portfolio positions: {e}")
        
        return positions

    def _should_execute_trade(self, symbol: str, is_long: bool) -> bool:
        """Determine if we should execute a trade based on current positions and settings."""
        try:
            # Check if we already have an open trade for this symbol and direction
            open_trades = self.db_manager.get_open_trades()
            for trade in open_trades:
                if trade['coin'] == symbol and trade['is_long'] == is_long:
                    logger.info(f"Already have open {('long' if is_long else 'short')} position for {symbol}")
                    return False
            
            # Check if we have a position on Hyperliquid that conflicts
            _, is_in_position, size, _, _, _, is_long_on_hl = get_position(symbol, account)
            if is_in_position:
                if is_long_on_hl == is_long:
                    logger.info(f"Already have {('long' if is_long else 'short')} position for {symbol} on Hyperliquid")
                    return False
                else:
                    logger.warning(f"Conflicting position for {symbol}: Want {('long' if is_long else 'short')}, have {('long' if is_long_on_hl else 'short')}")
                    return False
            
            # Additional checks could be added here:
            # - Account balance checks
            # - Risk management rules
            # - Position size limits
            # - Blacklisted symbols
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking if should execute trade for {symbol}: {e}")
            return False

async def handle_telegram_message(update, context):
    """Main handler function for incoming Telegram messages (for python-telegram-bot v20+)."""
    try:
        # Ensure message is from the configured channel
        if update.effective_chat.id != config.TELEGRAM_CHANNEL_ID:
            logger.warning(f"Message from unauthorized chat: {update.effective_chat.id}")
            return
        
        message_text = update.message.text
        logger.info(f"Received message from authorized channel")
        
        # Initialize database and processor
        db_manager = TradeMonitorDB(DB_NAME)
        processor = TelegramMessageProcessor(db_manager)
        
        # Process the message
        results = processor.process_message(message_text)
        
        # Log summary
        logger.info(f"Message processing summary: "
                   f"Entries: {results.get('entries_processed', 0)}, "
                   f"Exits: {results.get('exits_processed', 0)}, "
                   f"Portfolios: {results.get('portfolios_updated', 0)}, "
                   f"Signals: {results.get('signals_recorded', 0)}")
        
        if results.get('errors'):
            logger.error(f"Processing errors: {results['errors']}")
        
    except Exception as e:
        logger.error(f"Error in handle_telegram_message: {e}", exc_info=True)

# For backward compatibility and direct testing
def process_test_message(message_text: str):
    """Function for testing message processing directly."""
    db_manager = TradeMonitorDB(DB_NAME)
    processor = TelegramMessageProcessor(db_manager)
    return processor.process_message(message_text)


# Module constants
DB_NAME = "bot_trades.db"