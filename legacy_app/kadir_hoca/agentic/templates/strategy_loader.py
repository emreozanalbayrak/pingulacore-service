"""
Strategy Loader - loads shared distractor strategies from _strategies.yaml.

This module provides centralized strategy management for all templates.
Templates that set `use_shared_strategies: true` will have their
celdirici_stratejileri populated from the shared pool.

The LLM dynamically selects appropriate strategies from this pool
based on paragraph content.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

if TYPE_CHECKING:
    from .schema import DistractorStrategy

__all__ = ["StrategyLoader", "StrategyLoadError"]

logger = logging.getLogger(__name__)

# Default strategies file location
DEFAULT_STRATEGIES_FILE = Path(__file__).parent.parent.parent / "templates" / "_strategies.yaml"


class StrategyLoadError(Exception):
    """Raised when strategy loading fails."""
    pass


class StrategyLoader:
    """
    Loader for shared distractor strategies.

    Loads strategies from templates/_strategies.yaml and converts them
    to DistractorStrategy objects for use in templates.

    Usage:
        loader = StrategyLoader()
        strategies = loader.load_all()
        # Returns list of DistractorStrategy objects
    """

    def __init__(self, strategies_file: Path | None = None):
        """
        Initialize the strategy loader.

        Args:
            strategies_file: Path to _strategies.yaml file.
                           Defaults to templates/_strategies.yaml
        """
        self.strategies_file = strategies_file or DEFAULT_STRATEGIES_FILE
        self._cache: list["DistractorStrategy"] | None = None

        logger.debug(f"[STRATEGIES] Initialized loader with file: {self.strategies_file}")

    def load_all(self) -> list["DistractorStrategy"]:
        """
        Load all shared strategies from the YAML file.

        Returns:
            List of DistractorStrategy objects

        Raises:
            StrategyLoadError: If file not found or parsing fails
        """
        # Return cached result if available
        if self._cache is not None:
            return self._cache

        if not self.strategies_file.exists():
            raise StrategyLoadError(
                f"Strategies file not found: {self.strategies_file}"
            )

        logger.info(f"[STRATEGIES] Loading shared strategies from: {self.strategies_file}")

        try:
            with open(self.strategies_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise StrategyLoadError(f"Failed to parse strategies YAML: {e}")

        if not data or "strategies" not in data:
            raise StrategyLoadError(
                f"Invalid strategies file format: missing 'strategies' key"
            )

        strategies = self._parse_strategies(data["strategies"])

        logger.info(f"[STRATEGIES] Loaded {len(strategies)} shared strategies")

        # Cache the result
        self._cache = strategies

        return strategies

    def load_for_template(self, template_id: str) -> list["DistractorStrategy"]:
        """
        Load strategies filtered for a specific template.

        Only returns strategies that have the template_id in their templates list,
        or strategies with an empty templates list (which means "all templates").

        Args:
            template_id: Template identifier (e.g., "konu_standard", "konu_inverse")

        Returns:
            List of DistractorStrategy objects applicable to this template

        Raises:
            StrategyLoadError: If file not found or parsing fails
        """
        all_strategies = self.load_all()

        filtered = [
            s for s in all_strategies
            if not s.templates or template_id in s.templates
        ]

        logger.info(
            f"[STRATEGIES] Filtered {len(filtered)}/{len(all_strategies)} "
            f"strategies for template: {template_id}"
        )

        return filtered

    def _parse_strategies(self, strategies_dict: dict) -> list["DistractorStrategy"]:
        """
        Parse strategy dictionary into DistractorStrategy objects.

        Args:
            strategies_dict: Dictionary of strategy_id -> strategy_data

        Returns:
            List of DistractorStrategy objects
        """
        from .schema import DistractorStrategy, DistractorExample

        strategies = []

        for strategy_id, strategy_data in strategies_dict.items():
            # Parse examples if present
            examples = []
            if "ornekler" in strategy_data:
                for ex_data in strategy_data["ornekler"]:
                    examples.append(DistractorExample(
                        paragraf_konusu=ex_data.get("paragraf_konusu"),
                        celdirici=ex_data.get("celdirici"),
                        neden_yanlis=ex_data.get("neden_yanlis"),
                        konu=ex_data.get("konu"),
                        paragraf=ex_data.get("paragraf"),
                        neden_dogru=ex_data.get("neden_dogru"),
                    ))

            strategy = DistractorStrategy(
                ad=strategy_data.get("ad", strategy_id.upper()),
                aciklama=strategy_data.get("aciklama", ""),
                nasil_olusturulur=strategy_data.get("nasil_olusturulur", ""),
                kacinilacaklar=strategy_data.get("kacinilacaklar", ""),
                tip=strategy_data.get("tip"),
                kategori=strategy_data.get("kategori"),
                bilissel_hata=strategy_data.get("bilissel_hata"),
                rol=strategy_data.get("rol"),
                templates=strategy_data.get("templates", []),
                ornekler=examples,
            )

            strategies.append(strategy)
            logger.debug(f"[STRATEGIES] Parsed strategy: {strategy.ad} (templates={strategy.templates})")

        return strategies

    def clear_cache(self) -> None:
        """Clear the strategies cache."""
        self._cache = None
        logger.debug("[STRATEGIES] Cache cleared")

    def reload(self) -> list["DistractorStrategy"]:
        """
        Force reload strategies from disk.

        Returns:
            Freshly loaded list of DistractorStrategy objects
        """
        self.clear_cache()
        return self.load_all()
