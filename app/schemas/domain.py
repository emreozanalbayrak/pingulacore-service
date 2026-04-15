from __future__ import annotations

from app.schemas.html import CompositeImageResult, GeneratedHtml
from app.schemas.layout import AssetBinding, AssetSpec, AssetType, HtmlLayoutNode, LayoutPlan, PlacementFrame
from app.schemas.question import (
    EntitySpec,
    QuestionCharacterSpec,
    QuestionOptionSpec,
    QuestionScenarioSpec,
    QuestionSceneSpec,
    QuestionSpec,
)
from app.schemas.validation import (
    HtmlValidationResult,
    QuestionLayoutValidationResult,
    RuleEvaluation,
    RuleEvaluationSet,
    RuleExtractionResult,
    ValidationRule,
)

__all__ = [
    "EntitySpec",
    "QuestionSceneSpec",
    "QuestionCharacterSpec",
    "QuestionScenarioSpec",
    "QuestionOptionSpec",
    "QuestionSpec",
    "AssetType",
    "AssetSpec",
    "AssetBinding",
    "PlacementFrame",
    "HtmlLayoutNode",
    "LayoutPlan",
    "GeneratedHtml",
    "CompositeImageResult",
    "ValidationRule",
    "RuleExtractionResult",
    "RuleEvaluation",
    "RuleEvaluationSet",
    "QuestionLayoutValidationResult",
    "HtmlValidationResult",
]
