# bot_core/utils.py - Common Utility Functions

import logging
import sys

def setup_module_logger(module_name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Set up a logger for a specific module with consistent formatting.
    
    :param module_name: Usually __name__ from the calling module
    :param level: Logging level (default: INFO)
    :return: Configured logger instance
    """
    logger = logging.getLogger(module_name)
    
    # Avoid adding multiple handlers if logger already exists
    if not logger.handlers:
        # Create console handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(level)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        console_handler.setFormatter(formatter)
        
        # Add handler to logger
        logger.addHandler(console_handler)
        logger.setLevel(level)
    
    return logger

def format_price(price: float, decimals: int = 4) -> str:
    """Format price with specified decimal places."""
    return f"${price:.{decimals}f}"

def format_percentage(percentage: float, decimals: int = 2) -> str:
    """Format percentage with specified decimal places."""
    return f"{percentage:.{decimals}f}%"

def safe_float_conversion(value: str, default: float = 0.0) -> float:
    """Safely convert string to float with fallback."""
    try:
        return float(value.replace(',', ''))
    except (ValueError, AttributeError):
        return default

def safe_int_conversion(value: str, default: int = 0) -> int:
    """Safely convert string to int with fallback."""
    try:
        return int(value.replace(',', ''))
    except (ValueError, AttributeError):
        return default