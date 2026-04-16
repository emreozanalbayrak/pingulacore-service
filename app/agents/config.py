from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

# ---------------------------------------------------------------------------
# Model aliases
# ---------------------------------------------------------------------------
GEMINI_PRO = "google-gla:gemini-3.1-pro-preview"
GEMINI_FLASH_LITE = "google-gla:gemini-3.1-flash-lite-preview"
CLAUDE_SONNET = "anthropic:claude-sonnet-4-6"
CLAUDE_HAIKU = "anthropic:claude-haiku-4-5"

# ---------------------------------------------------------------------------
# Agent instructions
# ---------------------------------------------------------------------------
QUESTION_AGENT_INSTRUCTIONS = (
    "You generate only QuestionSpec from curriculum YAML. "
    "Do not produce layout, coordinates, HTML, or render instructions. "
    "Use scenario.scenes as a list. "
    "Do not use a singular scene field."
)

RULE_EXTRACTOR_INSTRUCTIONS = (
    "Extract atomically testable validation rules from the YAML input. "
    "Prioritize only the most critical constraints for generation quality and correctness. "
    "Merge overlapping or near-duplicate rules into a single concise rule when possible. "
    "Return at most 12 rules."
)

RULE_EVALUATOR_INSTRUCTIONS = (
    "Evaluate one rule against a QuestionSpec and return pass/partial/fail."
)

LAYOUT_PLANNER_INSTRUCTIONS = (
    "Generate a LayoutPlan from QuestionSpec. "
    "QuestionSpec.scenario.scenes may include multiple scene items; each enabled scene should map to a background asset. "
    "AI-generated assets are opaque and rectangular/square (not transparent), so place them carefully to avoid hiding critical objects. "
    "Catalog assets are transparent and can be layered above AI assets. "
    "Use binding layer and z_index so critical foreground objects remain visible. "
    "Use catalog components from the provided catalog_files list. "
    "For catalog_component assets, source_filename must be one of catalog_files and transparent_background should be true."
)

LAYOUT_VALIDATOR_INSTRUCTIONS = (
    "Validate consistency between QuestionSpec and LayoutPlan. "
    "Check multi-scene coverage and ensure opaque AI assets do not hide critical foreground elements."
)

HTML_GENERATOR_INSTRUCTIONS = (
    "Generate question HTML from QuestionSpec, LayoutPlan, and asset map. "
    "Use QuestionSpec.stem/options/solution semantics to keep educational intent clear in the final card. "
    "Use src values from provided asset_map entries for catalog assets and do not invent unknown file paths."
)

HTML_VALIDATOR_INSTRUCTIONS = (
    "You are a visual QA agent for educational question cards. "
    "Evaluate the quality of the FINAL RENDERED QUESTION IMAGE together with the HTML source. "
    "Primary criterion is visual quality and pedagogical usability, not strict layout-plan matching. "
    "Check readability, spacing, alignment, overlap/occlusion, option clarity, visual hierarchy, and whether the question is understandable at first glance. "
    "Return fail when quality is not acceptable for student-facing usage. "
    "Issues must be concrete and feedback must be actionable editing guidance for the HTML."
)

# ---------------------------------------------------------------------------
# Config types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AgentConfig:
    instructions: str
    primary_model: str
    primary_max_retry: int
    on_fail: Literal["error", "fallback"]
    fallback_model: str | None = None
    thinking_level: str = "medium"


@dataclass(frozen=True)
class AgentSettings:
    generate_question: AgentConfig
    extract_rules: AgentConfig
    evaluate_rule: AgentConfig
    generate_layout: AgentConfig
    validate_question_layout: AgentConfig
    generate_html: AgentConfig
    validate_html: AgentConfig


# ---------------------------------------------------------------------------
# Default settings
# ---------------------------------------------------------------------------

_DEFAULT_AGENT_SETTINGS = AgentSettings(
    generate_question=AgentConfig(
        instructions=QUESTION_AGENT_INSTRUCTIONS,
        primary_model=GEMINI_PRO,
        primary_max_retry=5,
        on_fail="fallback",
        fallback_model=GEMINI_FLASH_LITE,
        thinking_level="high",
    ),
    extract_rules=AgentConfig(
        instructions=RULE_EXTRACTOR_INSTRUCTIONS,
        primary_model=GEMINI_FLASH_LITE,
        primary_max_retry=5,
        on_fail="fallback",
        fallback_model=GEMINI_PRO,
        thinking_level="medium",
    ),
    evaluate_rule=AgentConfig(
        instructions=RULE_EVALUATOR_INSTRUCTIONS,
        primary_model=GEMINI_FLASH_LITE,
        primary_max_retry=5,
        on_fail="fallback",
        fallback_model=GEMINI_PRO,
        thinking_level="low",
    ),
    generate_layout=AgentConfig(
        instructions=LAYOUT_PLANNER_INSTRUCTIONS,
        primary_model=GEMINI_PRO,
        primary_max_retry=5,
        on_fail="fallback",
        fallback_model=GEMINI_FLASH_LITE,
        thinking_level="high",
    ),
    validate_question_layout=AgentConfig(
        instructions=LAYOUT_VALIDATOR_INSTRUCTIONS,
        primary_model=GEMINI_PRO,
        primary_max_retry=5,
        on_fail="fallback",
        fallback_model=GEMINI_FLASH_LITE,
        thinking_level="medium",
    ),
    generate_html=AgentConfig(
        instructions=HTML_GENERATOR_INSTRUCTIONS,
        primary_model=CLAUDE_SONNET,
        primary_max_retry=5,
        on_fail="fallback",
        fallback_model=GEMINI_PRO,
        thinking_level="high",
    ),
    validate_html=AgentConfig(
        instructions=HTML_VALIDATOR_INSTRUCTIONS,
        primary_model=GEMINI_PRO,
        primary_max_retry=5,
        on_fail="fallback",
        fallback_model=GEMINI_FLASH_LITE,
        thinking_level="high",
    ),
)


def get_agent_settings() -> AgentSettings:
    return _DEFAULT_AGENT_SETTINGS
