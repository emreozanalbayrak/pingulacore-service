"""
Base Question Generator - abstract interface for format-specific generators.

Each format (e.g., single_paragraph_mc) has its own generator implementation
that knows how to:
1. Generate a paragraph according to template rules
2. Generate a question stem from template variations
3. Generate correct answer following template definition
4. Generate distractors using template strategies
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..client import GeminiClient
    from ..schemas import ParagraphOutput
    from ..templates.schema import QuestionTemplate

__all__ = ["BaseQuestionGenerator", "GeneratorOutput"]


@dataclass
class GeneratorOutput:
    """
    Output from a question generator.

    Contains all components needed for the final question.
    """

    # Paragraph (required)
    paragraph: str
    key_concepts: list[str]
    difficulty_level: str

    # Question (required)
    question: str
    key_word: str

    # Options (required)
    options: dict[str, str]
    correct_answer: str

    # Reasoning for each option (required)
    option_reasoning: dict[str, dict]

    # Optional fields with defaults (must come after required fields)
    curriculum_source: str | None = None
    curriculum_reasoning: str | None = None
    template_id: str = ""
    format_id: str = ""

    # Beceri temelli fields
    answer_explanation: str = ""
    skill_tag: str = ""

    # Image options (gorsel_siklar templates)
    option_images: dict[str, str] | None = None  # {"A": "base64...", "B": "base64..."}
    shared_visual_format: str = ""  # Shared visual format spec for image generation

    # Stem tracking
    selected_stem_index: int | None = None
    selected_stem_text: str = ""
    stem_source: str = ""
    stem_reservation_id: str | None = None
    stem_reservation_status: str = ""


class BaseQuestionGenerator(ABC):
    """
    Abstract base class for question generators.

    Each format (single_paragraph_mc, multi_paragraph, etc.) implements
    this interface with format-specific generation logic.

    Usage:
        generator = SingleParagraphMCGenerator()
        output = await generator.generate(
            template=template,
            topic="OYUN DUNYASI / Okuma Becerileri",
            client=gemini_client,
            grade=5,
        )
    """

    @property
    @abstractmethod
    def format_id(self) -> str:
        """Return the format ID this generator handles."""
        pass

    @abstractmethod
    async def generate(
        self,
        template: "QuestionTemplate",
        topic: str,
        client: "GeminiClient",
        grade: int,
        subject: str = "turkce",
        cache_name: str | None = None,
        paragraph_model: str = "gemini-3-flash-preview",
        question_model: str = "gemini-3-flash-preview",
        validation_feedback: str | None = None,
        stem_text: str | None = None,
        stem_metadata: dict[str, str | int | None] | None = None,
    ) -> GeneratorOutput:
        """
        Generate a complete question using the template.

        Args:
            template: QuestionTemplate with rules for this question type
            topic: Topic string (e.g., "OYUN DUNYASI / Okuma Becerileri")
            client: GeminiClient for API calls
            grade: Target grade level
            subject: Subject code (default: "turkce")
            cache_name: Optional cache name for PDF-grounded generation
            paragraph_model: Model to use for paragraph generation
            question_model: Model to use for question generation
            validation_feedback: Optional feedback from previous validation failure
                                to guide the LLM on what to fix in this retry

        Returns:
            GeneratorOutput with all question components
        """
        pass

    @abstractmethod
    async def generate_paragraph(
        self,
        template: "QuestionTemplate",
        topic: str,
        subject: str,
        grade: int,
        client: "GeminiClient",
        cache_name: str | None = None,
        model: str = "gemini-3-flash-preview",
    ) -> "ParagraphOutput":
        """
        Generate only the paragraph component.

        Args:
            template: QuestionTemplate with paragraph rules
            topic: Topic string
            subject: Subject code
            grade: Target grade level
            client: GeminiClient for API calls
            cache_name: Optional cache name for PDF grounding
            model: Model to use for paragraph generation

        Returns:
            ParagraphOutput with paragraph text and metadata
        """
        pass

    @abstractmethod
    async def generate_question(
        self,
        template: "QuestionTemplate",
        topic: str,
        paragraph: str,
        client: "GeminiClient",
        grade: int,
        subject: str = "turkce",
        cache_name: str | None = None,
        question_model: str = "gemini-3-flash-preview",
        validation_feedback: str | None = None,
        stem_text: str | None = None,
        stem_metadata: dict[str, str | int | None] | None = None,
    ) -> GeneratorOutput:
        """
        Generate only the question component (stem + options) from a given paragraph.

        Args:
            template: QuestionTemplate with question rules
            topic: Topic string
            paragraph: Pre-generated paragraph text
            client: GeminiClient for API calls
            grade: Target grade level
            subject: Subject code
            cache_name: Optional cache name for PDF grounding
            question_model: Model to use for question generation
            validation_feedback: Optional feedback from previous validation failure

        Returns:
            GeneratorOutput with question, options, and default paragraph metadata
        """
        pass
