"""
Question Generators - format-specific question generation logic.

The HTML generator handles all formats based on template configuration.
Templates now have format as a FormatConfig object with html_template field.
"""

from .base import BaseQuestionGenerator, GeneratorOutput
from .html_generator import HTMLQuestionGenerator

__all__ = [
    "BaseQuestionGenerator",
    "GeneratorOutput",
    "HTMLQuestionGenerator",
    "get_generator",
]


def get_generator(format_type: str | object) -> BaseQuestionGenerator:
    """
    Get a generator instance for the given format.

    Args:
        format_type: Format type string (e.g., "llm_generated_html")
                    or FormatConfig object with .type attribute

    Returns:
        Generator instance (HTMLQuestionGenerator for all formats)

    Raises:
        ValueError: If format type is not recognized
    """
    # Handle FormatConfig objects (new template structure)
    if hasattr(format_type, "type"):
        format_type = format_type.type

    format_str = str(format_type)

    if format_str != "llm_generated_html":
        raise ValueError(
            f"Unknown format: {format_str}. Available formats: llm_generated_html"
        )

    return HTMLQuestionGenerator()
