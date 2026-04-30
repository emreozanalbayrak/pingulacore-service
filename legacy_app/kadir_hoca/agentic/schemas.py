"""
Pydantic schemas for the agentic question generator.

These schemas define the structured output for question generation:
- ParagraphOutput: Output from paragraph generation step
- QuestionOutput: Output from question creation step
- ValidationCheckOutput: Output from a single validation check
- ValidationOutput: Complete validation result
- QuestionGenerationResult: Final workflow output

Using Pydantic BaseModel enables:
1. Type-safe structured output with Gemini's structured generation
2. Automatic validation of LLM responses
3. Better IDE support with type hints
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

__all__ = [
    "ParagraphOutput",
    "ValidationCheckOutput",
    "ValidationOutput",
    "QuestionGenerationResult",
    # Context-based question group results (mustafa)
    "ContextSubQuestionResult",
    "CrossValidationResult",
    "ContextQuestionGroupResult",
    # Multi-question support (baglam-deneme)
    "SingleQuestionResult",
    "MultiQuestionGenerationResult",
]


# ============================================================================
# PARAGRAPH OUTPUT
# ============================================================================


class ParagraphOutput(BaseModel):
    """Output from the paragraph generation step."""

    paragraph: str = Field(
        ...,
        description="The generated educational paragraph",
    )
    key_concepts: list[str] = Field(
        ...,
        description="List of key concepts covered in the paragraph",
    )
    difficulty_level: Literal["kolay", "orta", "zor"] = Field(
        ...,
        description="Difficulty level of the paragraph",
    )
    curriculum_source: str = Field(
        ...,
        description="MEB textbook source (e.g., 'MEB 5. Sınıf Fen Bilimleri, Ünite 2, Sayfa 45')",
    )
    reasoning: str = Field(
        ...,
        description="Explanation of how the paragraph was created based on the textbook",
    )


# ============================================================================
# VALIDATION OUTPUT
# ============================================================================


class ValidationCheckOutput(BaseModel):
    """Output from a single validation check."""

    check_type: str = Field(
        default="",
        description="Check type identifier (e.g., 'question_format', 'distractors')",
    )
    check_name: str = Field(
        default="",
        description="Human-readable check name (e.g., 'Soru Formatı', 'Çeldirici Kalitesi')",
    )
    status: Literal["PASS", "FAIL"] = Field(
        ...,
        description="Whether the check passed or failed",
    )
    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Quality score from 0-100",
    )
    feedback: str = Field(
        ...,
        description="Detailed feedback about the check result",
    )
    issues: list[str] = Field(
        default_factory=list,
        description="List of specific issues found (empty if passed)",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="List of suggestions for improvement",
    )
    affected_components: list[Literal["paragraph", "question_stem", "options"]] = Field(
        default_factory=list,
        description="Which component(s) have issues",
    )


class ValidationOutput(BaseModel):
    """Complete validation result (aggregated from all checks)."""

    passed: bool = Field(
        ...,
        description="Whether all checks passed",
    )
    checks: list[ValidationCheckOutput] = Field(
        default_factory=list,
        description="Results from each individual check",
    )
    overall_score: float = Field(
        default=0.0,
        description="Average score across all checks",
    )

    @property
    def failed_checks(self) -> list[ValidationCheckOutput]:
        """Return list of failed checks."""
        return [c for c in self.checks if c.status == "FAIL"]

    def get_feedback_summary(self) -> str:
        """Get a summary of all feedback."""
        lines = []
        for check in self.checks:
            status_marker = "[PASS]" if check.status == "PASS" else "[FAIL]"
            lines.append(f"{status_marker}: {check.feedback}")
            for issue in check.issues:
                lines.append(f"  - Sorun: {issue}")
            for suggestion in check.suggestions:
                lines.append(f"  - Öneri: {suggestion}")
        return "\n".join(lines)


# ============================================================================
# COMPLETE GENERATION RESULT
# ============================================================================


class QuestionGenerationResult(BaseModel):
    """Complete result of the question generation workflow."""

    topic: str
    question_type: str
    success: bool

    # Generated content
    paragraph: str = ""
    question: str = ""
    key_word: str = ""
    options: dict[str, str] = Field(default_factory=dict)
    correct_answer: str = ""

    # Option reasoning (reasoning-first format)
    option_reasoning: dict[str, dict] = Field(default_factory=dict)

    # Paragraph metadata
    key_concepts: list[str] = Field(default_factory=list)
    difficulty_level: str = "orta"

    # Curriculum grounding
    curriculum_source: str | None = None
    curriculum_reasoning: str | None = None

    # Image generation
    has_image: bool = False
    image_base64: str | None = None
    image_context: bool = False  # If True, image is primary context (poster/afis), paragraph hidden in HTML

    # Image options (gorsel_siklar templates)
    option_images: dict[str, str] | None = None  # {"A": "base64_png", "B": "base64_png", ...}
    shared_visual_format: str = ""  # Shared visual format spec for consistent image generation

    # Rendering hints (from template format config)
    options_layout: str | None = None  # "two_column" for 2x2 grid, None for vertical
    html_body_template: str | None = None  # Template's rendering layout from YAML

    # Beceri temelli fields
    skill_tag: str | None = None
    context_type: str | None = None
    answer_explanation: str | None = None

    # Validation info
    validation: ValidationOutput | None = None
    fix_iterations: int = 0

    # Beceri etiketi (from template)
    beceri_etiketi: dict | None = None

    # Çeldirici bilişsel hata kategorileri (strategy → category mapping)
    celdirici_hata_kategorileri: dict[str, str] = Field(default_factory=dict)

    # Yayınlanma durumu (karar ağacı sonucu)
    yayinlanma_durumu: str = ""  # "yayina_hazir" | "revizyon_gerekli" | "revizyon_zorunlu"

    # Stem tracking (for post-generation commenting in YAML)
    used_stem_index: int | None = None
    template_id: str = ""
    selected_stem_index: int | None = None
    selected_stem_text: str = ""
    stem_source: str = ""
    stem_reservation_id: str | None = None
    stem_reservation_status: str = ""
    commented_stem_index: int | None = None

    # Error info
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        validation_dict = None
        if self.validation:
            validation_dict = {
                "passed": self.validation.passed,
                "overall_score": self.validation.overall_score,
                "checks": [
                    {
                        "type": c.check_type,
                        "name": c.check_name,
                        "status": c.status,
                        "score": c.score,
                        "feedback": c.feedback,
                    }
                    for c in self.validation.checks
                ],
            }

        result = {
            "topic": self.topic,
            "question_type": self.question_type,
            "success": self.success,
            "paragraph": self.paragraph,
            "question": self.question,
            "key_word": self.key_word,
            "options": self.options,
            "correct_answer": self.correct_answer,
            "option_reasoning": self.option_reasoning,
            "key_concepts": self.key_concepts,
            "difficulty_level": self.difficulty_level,
            "validation": validation_dict,
            "fix_iterations": self.fix_iterations,
            "error": self.error,
            "template_id": self.template_id,
            "used_stem_index": self.used_stem_index,
            "selected_stem_index": self.selected_stem_index,
            "selected_stem_text": self.selected_stem_text,
            "stem_source": self.stem_source,
            "stem_reservation_id": self.stem_reservation_id,
            "stem_reservation_status": self.stem_reservation_status,
            "commented_stem_index": self.commented_stem_index,
        }

        # Include beceri etiketi
        if self.beceri_etiketi:
            result["beceri_etiketi"] = self.beceri_etiketi

        # Include çeldirici hata kategorileri
        if self.celdirici_hata_kategorileri:
            result["celdirici_hata_kategorileri"] = self.celdirici_hata_kategorileri

        # Include yayınlanma durumu
        if self.yayinlanma_durumu:
            result["yayinlanma_durumu"] = self.yayinlanma_durumu

        # Include image info
        if self.has_image:
            result["has_image"] = True
            result["image_context"] = self.image_context
            if self.image_base64:
                result["image_base64"] = self.image_base64

        # Include option images info (don't serialize full base64 to JSON)
        if self.option_images:
            result["option_images_count"] = len(self.option_images)
            result["option_images_labels"] = sorted(self.option_images.keys())

        # Include curriculum grounding info
        if self.curriculum_source or self.curriculum_reasoning:
            result["curriculum_grounding"] = {
                "source": self.curriculum_source,
                "reasoning": self.curriculum_reasoning,
            }

        # Include beceri temelli fields
        if self.skill_tag:
            result["skill_tag"] = self.skill_tag
        if self.context_type:
            result["context_type"] = self.context_type
        if self.answer_explanation:
            result["answer_explanation"] = self.answer_explanation

        return result


# ============================================================================
# CONTEXT-BASED QUESTION GROUP RESULTS
# ============================================================================


class ContextSubQuestionResult(BaseModel):
    """Result of a single sub-question within a context group."""

    slot: int
    question_type: str
    success: bool
    question: str = ""
    key_word: str = ""
    options: dict[str, str] = Field(default_factory=dict)
    correct_answer: str = ""
    option_reasoning: dict[str, dict] = Field(default_factory=dict)
    beceri_etiketi: dict | None = None
    celdirici_hata_kategorileri: dict[str, str] = Field(default_factory=dict)
    validation: ValidationOutput | None = None
    fix_iterations: int = 0
    error: str | None = None
    # Visual option support (gorsel siklar in context templates)
    option_images: dict[str, str] | None = None  # {"A": "base64_png", ...}
    shared_visual_format: str = ""


class CrossValidationResult(BaseModel):
    """Result of cross-validation across sub-questions in a group."""

    passed: bool
    issues: list[str] = Field(default_factory=list)
    duplicate_answers: list[str] = Field(default_factory=list)
    overlapping_distractors: list[str] = Field(default_factory=list)


class ContextQuestionGroupResult(BaseModel):
    """Complete result of a context-based question group generation."""

    topic: str
    context_type: str
    success: bool
    context_text: str = ""
    header_text: str = ""
    key_concepts: list[str] = Field(default_factory=list)
    difficulty_level: str = "orta"
    curriculum_source: str | None = None
    curriculum_reasoning: str | None = None
    questions: list[ContextSubQuestionResult] = Field(default_factory=list)
    cross_validation: CrossValidationResult | None = None
    yayinlanma_durumu: str = ""  # "yayina_hazir" | "revizyon_gerekli" | "revizyon_zorunlu"

    # Image generation (context infographic/poster)
    has_image: bool = False
    image_base64: str | None = None

    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        questions_list = []
        for q in self.questions:
            q_dict = {
                "slot": q.slot,
                "question_type": q.question_type,
                "success": q.success,
                "question": q.question,
                "key_word": q.key_word,
                "options": q.options,
                "correct_answer": q.correct_answer,
                "option_reasoning": q.option_reasoning,
                "beceri_etiketi": q.beceri_etiketi,
                "celdirici_hata_kategorileri": q.celdirici_hata_kategorileri,
                "fix_iterations": q.fix_iterations,
                "error": q.error,
            }
            if q.validation:
                q_dict["validation"] = {
                    "passed": q.validation.passed,
                    "overall_score": q.validation.overall_score,
                    "checks": [
                        {
                            "type": c.check_type,
                            "name": c.check_name,
                            "status": c.status,
                            "score": c.score,
                            "feedback": c.feedback,
                        }
                        for c in q.validation.checks
                    ],
                }
            questions_list.append(q_dict)

        cross_val_dict = None
        if self.cross_validation:
            cross_val_dict = {
                "passed": self.cross_validation.passed,
                "issues": self.cross_validation.issues,
                "duplicate_answers": self.cross_validation.duplicate_answers,
                "overlapping_distractors": self.cross_validation.overlapping_distractors,
            }

        result = {
            "topic": self.topic,
            "context_type": self.context_type,
            "success": self.success,
            "context_text": self.context_text,
            "header_text": self.header_text,
            "key_concepts": self.key_concepts,
            "difficulty_level": self.difficulty_level,
            "curriculum_source": self.curriculum_source,
            "curriculum_reasoning": self.curriculum_reasoning,
            "questions": questions_list,
            "cross_validation": cross_val_dict,
            "error": self.error,
        }

        if self.yayinlanma_durumu:
            result["yayinlanma_durumu"] = self.yayinlanma_durumu

        # Include image info
        if self.has_image:
            result["has_image"] = True

        return result


# ============================================================================
# MULTI-QUESTION SUPPORT (baglam-deneme)
# ============================================================================


class SingleQuestionResult(BaseModel):
    """Result of a single question within a multi-question context."""

    question: str = ""
    key_word: str = ""
    options: dict[str, str] = Field(default_factory=dict)
    correct_answer: str = ""
    option_reasoning: dict[str, dict] = Field(default_factory=dict)
    validation: ValidationOutput | None = None
    skill_tag: str | None = None
    answer_explanation: str = ""


class MultiQuestionGenerationResult(BaseModel):
    """Result for multi-question generation (1-3 questions per context)."""

    topic: str
    question_type: str
    success: bool
    context_type: str | None = None
    paragraph: str = ""
    key_concepts: list[str] = Field(default_factory=list)
    difficulty_level: str = "orta"
    has_image: bool = False
    image_base64: str | None = None
    questions: list[SingleQuestionResult] = Field(default_factory=list)
    options_layout: str | None = None
    html_body_template: str | None = None
    fix_iterations: int = 0
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "topic": self.topic,
            "question_type": self.question_type,
            "success": self.success,
            "context_type": self.context_type,
            "paragraph": self.paragraph,
            "key_concepts": self.key_concepts,
            "difficulty_level": self.difficulty_level,
            "has_image": self.has_image,
            "questions": [q.model_dump() for q in self.questions],
            "fix_iterations": self.fix_iterations,
            "error": self.error,
        }
