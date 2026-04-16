from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

# ---------------------------------------------------------------------------
# Config types
# ---------------------------------------------------------------------------

AGENTS_YAML_PATH = Path(__file__).resolve().parents[2] / "config.agents.yaml"

# ---------------------------------------------------------------------------
# Model aliases  (short name → full provider-prefixed model id)
# ---------------------------------------------------------------------------
MODEL_ALIASES: dict[str, str] = {
    "gemini-3.1-pro": "google-gla:gemini-3.1-pro-preview",
    "gemini-3.1-flash": "google-gla:gemini-3.1-flash-lite-preview",
    "gemini-2.5-pro": "google-gla:gemini-2.5-pro",
    "gemini-2.5-flash": "google-gla:gemini-2.5-flash",
    "claude-sonnet-4-6": "anthropic:claude-sonnet-4-6",
    "claude-opus-4-6": "anthropic:claude-opus-4-6",
    "claude-haiku-4-5": "anthropic:claude-haiku-4-5",
    "gemini-2.5-flash-image": "google-gla:gemini-2.5-flash-image",
    "gemini-2.0-flash-image": "google-gla:gemini-2.0-flash-image-generation",
}


def _resolve_model(name: str) -> str:
    return MODEL_ALIASES.get(name, name)


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
    generate_image: AgentConfig


# ---------------------------------------------------------------------------
# YAML loader
# ---------------------------------------------------------------------------

_AGENT_NAMES = [
    "generate_question",
    "extract_rules",
    "evaluate_rule",
    "generate_layout",
    "validate_question_layout",
    "generate_html",
    "validate_html",
    "generate_image",
]


def _load_from_yaml(path: Path) -> AgentSettings:
    with path.open("r", encoding="utf-8") as fh:
        raw: dict[str, Any] = yaml.safe_load(fh) or {}

    instructions_block: dict[str, Any] = raw.get("instructions", {})
    run_settings_block: dict[str, Any] = raw.get("run_settings", {})

    configs: dict[str, AgentConfig] = {}
    for name in _AGENT_NAMES:
        instr_lines = instructions_block.get(name, [])
        instructions = " ".join(str(line) for line in instr_lines) if isinstance(instr_lines, list) else str(instr_lines)

        rs: dict[str, Any] = run_settings_block.get(name, {})
        on_fail_raw = str(rs.get("on_fail", "error"))
        on_fail: Literal["error", "fallback"] = "fallback" if on_fail_raw == "fallback" else "error"

        configs[name] = AgentConfig(
            instructions=instructions,
            primary_model=_resolve_model(str(rs["primary_model"])),
            primary_max_retry=int(rs.get("primary_max_retry", 3)),
            on_fail=on_fail,
            fallback_model=_resolve_model(str(rs["fallback_model"])) if rs.get("fallback_model") else None,
            thinking_level=str(rs.get("thinking_level", "medium")),
        )

    return AgentSettings(**configs)


def get_agent_settings() -> AgentSettings:
    return _load_from_yaml(AGENTS_YAML_PATH)
