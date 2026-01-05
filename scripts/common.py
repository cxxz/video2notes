"""
Common utilities shared across Video2Notes scripts.

This module provides standardized logging setup and other shared utilities
to reduce code duplication across standalone scripts.
"""
import logging
import sys


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Set up standardized logging configuration for scripts.

    Args:
        level: Logging level (default: logging.INFO)

    Returns:
        Configured logger instance
    """
    logging.basicConfig(
        level=level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)


# Pre-configured logger for simple imports
logger = setup_logging()
