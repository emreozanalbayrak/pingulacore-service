"""
Template Loader - loads and parses YAML template files.

Handles:
1. Loading question type templates from templates/
2. Parsing the embedded format configuration
3. Caching loaded templates for performance

The new template system embeds format configuration directly in each
template YAML file, so we no longer need separate format loading.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import yaml

from .schema import QuestionTemplate
from .strategy_loader import StrategyLoader, StrategyLoadError

__all__ = ["TemplateLoader", "TemplateNotFoundError"]

logger = logging.getLogger(__name__)

# Default templates directory: env override (LEGACY_TURKCE_TEMPLATES_DIR) → repo-root /templates
DEFAULT_TEMPLATES_DIR = Path(
    os.environ.get("LEGACY_TURKCE_TEMPLATES_DIR")
    or (Path(__file__).parent.parent.parent / "templates")
)


def _is_runnable_template_file(path: Path) -> bool:
    """Return True for YAML files that represent runnable question templates."""
    name = path.name
    stem = path.stem
    if name.startswith(("_", ".")):
        return False
    if name == "templates.yaml":
        return False
    if stem.endswith("_referans"):
        return False
    if "Ortak_Kurallar" in stem:
        return False
    return True


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursive merge. Override values take priority. Lists in override REPLACE base lists."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


class TemplateNotFoundError(Exception):
    """Raised when a template file is not found."""

    pass


class TemplateLoader:
    """
    Loader for template YAML files.

    Loads templates from the templates/ directory and caches them
    for efficient reuse.

    The new template structure has format embedded as an object,
    not as a string reference to a separate file.

    Usage:
        loader = TemplateLoader()
        template = loader.load("konu_standard")
        # template.format is now a FormatConfig object
        # template.format.type gives you the format type string
    """

    def __init__(
        self,
        templates_dir: Path | None = None,
    ):
        """
        Initialize the template loader.

        Args:
            templates_dir: Path to templates directory.
                          Defaults to project_root/templates/
        """
        self.templates_dir = Path(templates_dir) if templates_dir else DEFAULT_TEMPLATES_DIR
        self._template_cache: dict[str, QuestionTemplate] = {}
        self._template_index: dict[str, Path] | None = None
        self._defaults_cache: dict | None = None
        self._strategy_loader = StrategyLoader()

        logger.info(f"[TEMPLATES] Initialized loader with dir: {self.templates_dir}")

    def _load_defaults(self) -> dict:
        """Load _defaults.yaml, cached after first load."""
        if not hasattr(self, '_defaults_cache') or self._defaults_cache is None:
            defaults_path = self.templates_dir / "_defaults.yaml"
            if defaults_path.exists():
                with open(defaults_path, "r", encoding="utf-8") as f:
                    self._defaults_cache = yaml.safe_load(f) or {}
                logger.info(f"[TEMPLATES] Loaded defaults from {defaults_path}")
            else:
                self._defaults_cache = {}
        return self._defaults_cache

    def _build_template_index(self) -> None:
        """Build an index mapping template_id -> file path, scanning subdirectories."""
        if self._template_index is not None:
            return

        self._template_index = {}
        # Scan root and all subdirectories
        for f in self.templates_dir.rglob("*.yaml"):
            if not _is_runnable_template_file(f):
                continue
            tid = f.stem
            # First-found wins (subdirectories are fine)
            if tid not in self._template_index:
                self._template_index[tid] = f

        logger.info(
            f"[TEMPLATES] Indexed {len(self._template_index)} templates "
            f"across {self.templates_dir}"
        )

    def _get_template_path(self, template_id: str) -> Path:
        """Get the path to a question template file, searching subdirectories."""
        self._build_template_index()
        if template_id in self._template_index:
            return self._template_index[template_id]
        # Fallback to direct path for clear error message
        return self.templates_dir / f"{template_id}.yaml"

    def load(self, template_id: str) -> QuestionTemplate:
        """
        Load a question template by ID.

        The format configuration is embedded in the template YAML,
        so no separate format loading is needed.

        Args:
            template_id: Template identifier (e.g., "konu_standard", "konu_inverse")

        Returns:
            QuestionTemplate instance with embedded FormatConfig

        Raises:
            TemplateNotFoundError: If template file doesn't exist
        """
        # Check cache first
        if template_id in self._template_cache:
            return self._template_cache[template_id]

        # Load from file
        template_path = self._get_template_path(template_id)
        if not template_path.exists():
            raise TemplateNotFoundError(
                f"Question template not found: {template_id} "
                f"(looked in {template_path})"
            )

        logger.info(f"[TEMPLATES] Loading template: {template_id}")

        with open(template_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Non-mutating restore: if soru_kokleri is empty but the file has
        # "# KULLANILDI" lines, restore them in memory without editing the YAML.
        # This keeps the source file stable during parallel runs.
        if data is not None and not (data.get("soru_kokleri") or []):
            import re as _re
            raw = template_path.read_text(encoding="utf-8")
            if _re.search(r'^\s*#\s*KULLANILDI:\s*-', raw, _re.MULTILINE):
                logger.warning(
                    f"[TEMPLATES] {template_id}: all stems were marked KULLANILDI — "
                    "restoring stems in memory without mutating the YAML."
                )
                restored = _re.sub(r'^(\s*)#\s*KULLANILDI:\s*-', r'\1-', raw, flags=_re.MULTILINE)
                data = yaml.safe_load(restored)

        # Merge with defaults (template values override defaults)
        defaults = self._load_defaults()
        if defaults:
            data = _deep_merge(defaults, data)

        # Validate and create template with embedded format
        template = QuestionTemplate.model_validate(data)

        # Resolve shared strategies if enabled
        if template.use_shared_strategies:
            template = self._resolve_shared_strategies(template)

        logger.info(
            f"[TEMPLATES] Loaded: {template.meta.ad} "
            f"(format={template.format.type}, stems={len(template.soru_kokleri)}, "
            f"strategies={len(template.celdirici_stratejileri)})"
        )

        self._template_cache[template_id] = template

        return template

    def _resolve_shared_strategies(self, template: QuestionTemplate) -> QuestionTemplate:
        """
        Resolve shared strategies for templates with use_shared_strategies=True.

        Loads strategies from _strategies.yaml filtered for this specific template.
        Only strategies that have the template ID in their `templates` list are included.

        Args:
            template: QuestionTemplate with use_shared_strategies=True

        Returns:
            Updated QuestionTemplate with filtered strategies from shared pool
        """
        try:
            # Load only strategies applicable to this template
            filtered_strategies = self._strategy_loader.load_for_template(template.meta.id)
            logger.info(
                f"[TEMPLATES] Resolved {len(filtered_strategies)} strategies "
                f"for template: {template.meta.id}"
            )

            # Create a new template instance with filtered strategies
            # Using model_copy to preserve all other fields
            return template.model_copy(
                update={"celdirici_stratejileri": filtered_strategies}
            )

        except StrategyLoadError as e:
            logger.warning(
                f"[TEMPLATES] Failed to load shared strategies: {e}. "
                f"Using template's own strategies (if any)."
            )
            return template

    def list_templates(self) -> list[str]:
        """
        List runnable template IDs (searches subdirectories too).

        Returns:
            List of template IDs (without .yaml extension)
        """
        if not self.templates_dir.exists():
            return []

        self._build_template_index()
        runnable: list[str] = []
        for template_id in sorted(self._template_index.keys()):
            try:
                self.load(template_id)
            except Exception as exc:
                logger.debug("[TEMPLATES] Skipping non-runnable template %s: %s", template_id, exc)
                continue
            runnable.append(template_id)
        return runnable

    def clear_cache(self) -> None:
        """Clear the template and index cache."""
        self._template_cache.clear()
        self._template_index = None
        logger.info("[TEMPLATES] Cache cleared")

    def reload(self, template_id: str) -> QuestionTemplate:
        """
        Force reload a template from disk.

        Useful for development when templates are being edited.

        Args:
            template_id: Template identifier

        Returns:
            Freshly loaded QuestionTemplate
        """
        if template_id in self._template_cache:
            del self._template_cache[template_id]
        return self.load(template_id)

    def get_template_info(self, template_id: str) -> dict:
        """
        Get summary information about a template.

        Args:
            template_id: Template identifier

        Returns:
            Dict with template metadata and structure info
        """
        template = self.load(template_id)
        return {
            "id": template.meta.id,
            "name": template.meta.ad,
            "description": template.meta.aciklama,
            "grade": template.meta.sinif_seviyesi,
            "format_type": template.format.type,
            "stem_count": len(template.soru_kokleri),
            "distractor_strategies": [s.ad for s in template.celdirici_stratejileri],
            "uses_shared_strategies": template.use_shared_strategies,
            "has_examples": bool(template.ornekler),
            "has_topic_source": bool(template.konu_kaynagi),
        }

    def comment_out_used_stem(self, template_id: str, stem_index: int) -> bool:
        """Comment out a used stem in the template YAML file.

        After successful question generation, the used stem is commented out
        so it won't be selected again. The stem line gets prefixed with
        '# KULLANILDI: ' to indicate it was used.

        Args:
            template_id: Template identifier
            stem_index: 0-based index of the stem in soru_kokleri list

        Returns:
            True if successfully commented out, False otherwise
        """
        template_path = self._get_template_path(template_id)
        if not template_path.exists():
            logger.warning(f"[STEM-COMMENT] Template file not found: {template_path}")
            return False

        try:
            with open(template_path, "r", encoding="utf-8") as f:
                lines = f.readlines()

            # Find soru_kokleri section and count stem entries
            in_soru_kokleri = False
            current_stem_idx = -1
            target_line_idx = None

            for i, line in enumerate(lines):
                stripped = line.strip()

                # Detect soru_kokleri section start
                if stripped.startswith("soru_kokleri:"):
                    in_soru_kokleri = True
                    continue

                if in_soru_kokleri:
                    # End of section: non-indented line that's not a comment/empty
                    if stripped and not stripped.startswith("-") and not stripped.startswith("#"):
                        break

                    # Count stem entries (lines starting with '- ')
                    if stripped.startswith("- "):
                        current_stem_idx += 1
                        if current_stem_idx == stem_index:
                            target_line_idx = i
                            break

            if target_line_idx is None:
                logger.warning(
                    f"[STEM-COMMENT] Stem index {stem_index} not found in {template_id}"
                )
                return False

            # Check if already commented
            target_line = lines[target_line_idx]
            if "# KULLANILDI:" in target_line:
                logger.info(f"[STEM-COMMENT] Stem {stem_index} already commented in {template_id}")
                return True

            # Comment out: preserve indentation, add prefix
            indent = len(target_line) - len(target_line.lstrip())
            original_content = target_line.strip()
            lines[target_line_idx] = f"{' ' * indent}# KULLANILDI: {original_content}\n"

            with open(template_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

            # Clear cache so next load picks up the change
            if template_id in self._template_cache:
                del self._template_cache[template_id]

            logger.info(
                f"[STEM-COMMENT] Stem {stem_index} commented out in {template_id} "
                f"({template_path.name})"
            )
            return True

        except Exception as e:
            logger.warning(f"[STEM-COMMENT] Error commenting stem: {e}")
            return False
