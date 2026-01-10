# =============================================================================
# Core Package
# =============================================================================
"""Core utilities and configuration."""

from src.core.config import settings
from src.core.logging import get_logger, setup_logging

__all__ = ["settings", "get_logger", "setup_logging"]
