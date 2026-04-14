from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ValidationRule(BaseModel):
    id: str
    category: str
    text: str
    source_path: str = ""


class RuleExtractionResult(BaseModel):
    items: list[ValidationRule] = Field(default_factory=list)


class RuleEvaluation(BaseModel):
    rule_id: str
    category: str
    rule_text: str
    status: Literal["pass", "partial", "fail"]
    rationale: str
    confidence: float = 0.8
    evidence: str = ""


class RuleEvaluationSet(BaseModel):
    items: list[RuleEvaluation] = Field(default_factory=list)


class QuestionLayoutValidationResult(BaseModel):
    overall_status: Literal["pass", "fail"]
    issues: list[str] = Field(default_factory=list)
    feedback: str = ""


class LayoutHtmlValidationResult(BaseModel):
    overall_status: Literal["pass", "fail"]
    issues: list[str] = Field(default_factory=list)
    feedback: str = ""
