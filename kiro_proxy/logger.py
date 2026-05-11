"""Centralized logging module using loguru.

Replaces raw print() calls throughout the project with structured,
level-aware logging. Supports file output and rotation.
"""

import os
import sys
from loguru import logger

# Remove default handler
logger.remove()

# Log level from environment
LOG_LEVEL = os.getenv("KIRO_LOG_LEVEL", "INFO").upper()

# Console handler with color
logger.add(
    sys.stderr,
    level=LOG_LEVEL,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    colorize=True,
)

# File handler (optional)
LOG_FILE = os.getenv("KIRO_LOG_FILE", "").strip()
if LOG_FILE:
    LOG_MAX_SIZE = os.getenv("KIRO_LOG_MAX_SIZE", "10 MB")
    LOG_RETENTION = os.getenv("KIRO_LOG_RETENTION", "7 days")
    logger.add(
        LOG_FILE,
        level=LOG_LEVEL,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
        rotation=LOG_MAX_SIZE,
        retention=LOG_RETENTION,
        compression="gz",
    )

# Debug mode: off/errors/all
DEBUG_MODE = os.getenv("KIRO_DEBUG_MODE", "off").lower()
if DEBUG_MODE not in ("off", "errors", "all"):
    DEBUG_MODE = "off"


def get_logger(name: str = "kiro_proxy"):
    """Get a named logger instance."""
    return logger.bind(name=name)
