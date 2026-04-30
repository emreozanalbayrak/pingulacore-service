# Agentic question generation module (using direct google.genai SDK)
#
# This module provides AI-powered question generation for Turkish educational content,
# grounded in MEB (Turkish Ministry of Education) curriculum.
#
# Features:
# - Template-driven question generation
# - Explicit PDF caching (90% cost reduction)
# - Structured output via Pydantic models
# - Batch validation (2 API calls instead of 6-7)

from .schemas import (
    ParagraphOutput,
    ValidationCheckOutput,
    ValidationOutput,
    QuestionGenerationResult,
)
from .client import GeminiClient


# Template-driven workflow (lazy import to avoid circular imports)
def get_generic_workflow_class():
    """Get GenericQuestionWorkflow class (lazy import)."""
    from .generic_workflow import GenericQuestionWorkflow
    return GenericQuestionWorkflow


def get_template_generate_function():
    """Get generate_question_from_template function (lazy import)."""
    from .generic_workflow import generate_question_from_template
    return generate_question_from_template


# Batch validator (optimized validation - 2 calls instead of 6-7)
def get_batch_validator_class():
    """Get BatchValidator class (lazy import)."""
    from .batch_validator import BatchValidator
    return BatchValidator


__all__ = [
    # Client
    "GeminiClient",
    # Schemas (Pydantic models)
    "ParagraphOutput",
    "ValidationCheckOutput",
    "ValidationOutput",
    "QuestionGenerationResult",
    # Template-driven Workflow
    "get_generic_workflow_class",
    "get_template_generate_function",
    # Batch Validator (optimized - 2 calls instead of 6-7)
    "get_batch_validator_class",
]
