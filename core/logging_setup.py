"""
Structured logging, configured once at process start.

Rule (spec section 22): never log secrets, API keys, or raw
sensitive user content. Callers should pass short summaries
(e.g. "42 chars of user speech"), not full transcripts, into INFO
logs unless DEBUG is explicitly enabled.
"""

from __future__ import annotations

import sys

from loguru import logger

from core.config import get_config

_CONFIGURED = False


def setup_logging() -> "logger":
    global _CONFIGURED
    if _CONFIGURED:
        return logger

    cfg = get_config()
    logger.remove()  # drop the default stderr handler so we control format/level

    logger.add(
        sys.stderr,
        level=cfg.logging.level,
        format=(
            "<green>{time:HH:mm:ss}</green> "
            "<level>{level: <7}</level> "
            "<cyan>{module}</cyan> - <level>{message}</level>"
        ),
        colorize=True,
    )
    logger.add(
        cfg.resolved_log_path(),
        level="DEBUG",
        rotation=cfg.logging.max_bytes,
        retention=cfg.logging.backup_count,
        encoding="utf-8",
    )
    _CONFIGURED = True
    return logger


def get_logger():
    return setup_logging()
