"""
MEB Curriculum Context - manages PDF path and cache configuration.

Simplified from original Agno-based implementation.
The actual caching is now handled by GeminiClient.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "MEBCurriculumContext",
    "CacheConfig",
]

logger = logging.getLogger(__name__)


# ============================================================================
# CACHE CONFIGURATION
# ============================================================================

@dataclass
class CacheConfig:
    """Configuration for Gemini explicit caching."""
    enabled: bool = True
    ttl_seconds: int = 3600  # 1 hour default


# ============================================================================
# CURRICULUM CONTEXT
# ============================================================================

@dataclass
class MEBCurriculumContext:
    """
    Simple container for PDF path(s) and cache settings.

    The actual caching is handled by GeminiClient. This class just
    manages the PDF path(s) and cache configuration.

    Supports dual-PDF grounding:
    - pdf_path: MEB textbook PDF (e.g., turkce_5_1_compressed.pdf)
    - data_pdf_path: Topic-specific PDF from data/ directory (e.g., metinde_konu.pdf)
    """

    pdf_path: Path | None = None
    data_pdf_paths: list[Path] = field(default_factory=list)
    cache_config: CacheConfig = field(default_factory=CacheConfig)
    is_initialized: bool = False

    def initialize(self, pdf_path: Path, cache_config: CacheConfig | None = None) -> None:
        """
        Initialize with PDF path.

        Args:
            pdf_path: Path to MEB PDF file.
            cache_config: Optional cache configuration.

        Raises:
            FileNotFoundError: If PDF file doesn't exist.
        """
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        if cache_config:
            self.cache_config = cache_config

        file_size_mb = pdf_path.stat().st_size / (1024 * 1024)
        logger.info(f"[MEB] PDF path set: {pdf_path.name} ({file_size_mb:.2f} MB)")
        print(f"[MEB] PDF path set: {pdf_path.name} ({file_size_mb:.2f} MB)")

        self.pdf_path = pdf_path
        self.is_initialized = True

    def cleanup(self) -> None:
        """Reset context."""
        self.pdf_path = None
        self.is_initialized = False
        logger.info("[MEB] Context reset")
