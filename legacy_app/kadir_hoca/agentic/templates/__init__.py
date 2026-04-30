"""
Template system for generic question generation.

This module provides:
- Schema definitions for templates (Pydantic models)
- Template loader for YAML files

The new template system has embedded format configuration:
- format is a FormatConfig object containing paragraph, stem, options specs
- Templates include rich examples for distractors and correct answers
"""

from .schema import (
    # Format config (embedded in template)
    FormatConfig,
    FormatParagraphConfig,
    FormatStemConfig,
    FormatOptionsConfig,
    # Question template
    QuestionTemplate,
    TemplateMeta,
    CorrectAnswerConfig,
    CorrectAnswerExample,
    DistractorStrategy,
    DistractorExample,
    ModelConfig,
    # Topic source config
    TopicSourceConfig,
    TopicHierarchy,
    TopicHierarchyLevel,
)
from .loader import TemplateLoader, TemplateNotFoundError
from .stem_registry import (
    commit_reserved_stem,
    release_reserved_stem,
    reserve_balanced_stem,
    select_balanced_stem,
    reset_stem_registry,
    get_stem_statistics,
)

__all__ = [
    # Format config
    "FormatConfig",
    "FormatParagraphConfig",
    "FormatStemConfig",
    "FormatOptionsConfig",
    # Question template
    "QuestionTemplate",
    "TemplateMeta",
    "CorrectAnswerConfig",
    "CorrectAnswerExample",
    "DistractorStrategy",
    "DistractorExample",
    "ModelConfig",
    # Topic source config
    "TopicSourceConfig",
    "TopicHierarchy",
    "TopicHierarchyLevel",
    # Loader
    "TemplateLoader",
    "TemplateNotFoundError",
    # Stem registry
    "reserve_balanced_stem",
    "commit_reserved_stem",
    "release_reserved_stem",
    "select_balanced_stem",
    "reset_stem_registry",
    "get_stem_statistics",
]
