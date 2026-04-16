"""Usage and cost tracking for agent runs."""
from __future__ import annotations

from typing import Any, Optional

# Pricing per 1M tokens (USD)
MODEL_PRICING_USD_PER_1M: dict[str, dict[str, float]] = {
    # Claude (Anthropic)
    "claude-opus-4.6": {
        "input": 5.00,
        "cache_write_5m": 6.25,
        "cache_write_1h": 10.00,
        "cache_hit": 0.50,
        "output": 25.00,
    },
    "claude-opus-4.5": {
        "input": 5.00,
        "cache_write_5m": 6.25,
        "cache_write_1h": 10.00,
        "cache_hit": 0.50,
        "output": 25.00,
    },
    "claude-sonnet-4.6": {
        "input": 3.00,
        "cache_write_5m": 3.75,
        "cache_write_1h": 6.00,
        "cache_hit": 0.30,
        "output": 15.00,
    },
    "claude-sonnet-4.5": {
        "input": 3.00,
        "cache_write_5m": 3.75,
        "cache_write_1h": 6.00,
        "cache_hit": 0.30,
        "output": 15.00,
    },
    "claude-sonnet-4": {
        "input": 3.00,
        "cache_write_5m": 3.75,
        "cache_write_1h": 6.00,
        "cache_hit": 0.30,
        "output": 15.00,
    },
    "claude-haiku-4.5": {
        "input": 1.00,
        "cache_write_5m": 1.25,
        "cache_write_1h": 2.00,
        "cache_hit": 0.10,
        "output": 5.00,
    },
    # Gemini
    "gemini-3.1-pro-preview": {"input": 2.00, "cached_input": 0.20, "output": 12.00},
    "gemini-3-flash-preview": {"input": 0.50, "cached_input": 0.05, "output": 3.00},
    "gemini-3-pro-image-preview": {"input": 2.00, "output": 120.00},
    "gemini-3.1-flash-image-preview": {"input": 0.50, "cached_input": 0.05, "output": 60.00},
    "gemini-2.5-flash": {"input": 0.30, "cached_input": 0.03, "output": 2.50},
    "gemini-2.5-pro": {"input": 1.25, "cached_input": 0.125, "output": 10.00},
}

# Provider/model alias normalization for pricing lookup
MODEL_NAME_ALIASES: dict[str, str] = {
    # Anthropic aliases used in config
    "claude-opus-4-6": "claude-opus-4.6",
    "claude-sonnet-4-6": "claude-sonnet-4.6",
    "claude-haiku-4-5": "claude-haiku-4.5",
    # Gemini aliases used in config
    "gemini-3.1-flash-lite-preview": "gemini-3-flash-preview",
    "gemini-2.5-flash-image": "gemini-3.1-flash-image-preview",
    "gemini-2.0-flash-image-generation": "gemini-3.1-flash-image-preview",
}


def _to_int(value: Any) -> int:
    try:
        if value is None:
            return 0
        return int(value)
    except Exception:
        return 0


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                return item
    return {}


def normalize_token_usage(raw: Any) -> dict[str, int]:
    """Normalize token usage from various LLM response formats."""
    if raw is None:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cached_input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }

    if hasattr(raw, "model_dump"):
        raw = raw.model_dump()
    elif hasattr(raw, "__dict__") and not isinstance(raw, dict):
        raw = raw.__dict__

    if not isinstance(raw, dict):
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cached_input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
        }

    input_tokens = _to_int(
        raw.get("input_tokens")
        or raw.get("request_tokens")
        or raw.get("prompt_token_count")
        or raw.get("prompt_tokens")
        or 0
    )
    output_tokens = _to_int(
        raw.get("output_tokens")
        or raw.get("response_tokens")
        or raw.get("candidates_token_count")
        or raw.get("completion_tokens")
        or 0
    )
    total_tokens = _to_int(raw.get("total_tokens") or raw.get("total_token_count") or 0)
    total_tokens = total_tokens or (input_tokens + output_tokens)
    cached_input_tokens = _to_int(raw.get("cached_input_tokens") or raw.get("cached_tokens") or 0)
    cache_read_tokens = _to_int(raw.get("cache_read_tokens") or raw.get("cache_read_input_tokens") or 0)
    cache_write_tokens = _to_int(raw.get("cache_write_tokens") or raw.get("cache_creation_input_tokens") or 0)

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "cached_input_tokens": cached_input_tokens,
        "cache_read_tokens": cache_read_tokens,
        "cache_write_tokens": cache_write_tokens,
    }


def extract_token_usage(response: Any) -> dict[str, int]:
    """Extract token usage from pydantic_ai agent response."""
    if response is None:
        return normalize_token_usage(None)

    # PydanticAI AgentRunResult path: response.usage() -> RunUsage
    usage_method = getattr(response, "usage", None)
    if callable(usage_method):
        try:
            return normalize_token_usage(usage_method())
        except Exception:
            pass

    # PydanticAI ModelResponse path: response.response.usage -> RequestUsage
    inner_response = getattr(response, "response", None)
    if inner_response is not None:
        usage = getattr(inner_response, "usage", None)
        if usage is not None:
            return normalize_token_usage(usage)

    # Try standard attributes
    usage = getattr(response, "usage_metadata", None)
    if usage:
        return normalize_token_usage(usage)

    # Try response_metadata dict
    response_meta = getattr(response, "response_metadata", None) or {}
    if isinstance(response_meta, dict):
        for key in ("usage_metadata", "token_usage", "usage"):
            if key in response_meta:
                return normalize_token_usage(response_meta[key])

    return normalize_token_usage(None)


def _resolve_pricing(model_name: str) -> Optional[dict[str, float]]:
    """Resolve pricing for a model, handling version suffixes."""
    model = _normalize_model_name_for_pricing(model_name)
    if model in MODEL_PRICING_USD_PER_1M:
        return MODEL_PRICING_USD_PER_1M[model]
    # Tolerance for snapshot suffixes: gpt-4.1-2025-04-14 etc
    for key, value in MODEL_PRICING_USD_PER_1M.items():
        if model.startswith(key.lower() + "-"):
            return value
    return None


def _normalize_model_name_for_pricing(model_name: str) -> str:
    """
    Normalize provider-prefixed model ids to pricing-table keys.

    Examples:
      - google-gla:gemini-2.5-flash -> gemini-2.5-flash
      - anthropic:claude-sonnet-4-6 -> claude-sonnet-4.6
    """
    token = (model_name or "").strip().lower()
    if not token:
        return ""

    # PydanticAI provider-prefixed format: "<provider>:<model-id>"
    if ":" in token:
        token = token.split(":", 1)[1].strip()

    return MODEL_NAME_ALIASES.get(token, token)


def estimate_cost_usd(
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    *,
    cached_input_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
) -> tuple[float, str]:
    """Estimate cost in USD for a model run."""
    pricing = _resolve_pricing(model_name)
    if not pricing:
        return 0.0, "unknown_pricing"

    uncached_input_tokens = max(0, input_tokens)
    if cached_input_tokens > 0:
        # In some models, input includes cached tokens
        uncached_input_tokens = max(0, input_tokens - cached_input_tokens)

    input_cost = (uncached_input_tokens / 1_000_000.0) * pricing["input"]
    cached_input_cost = 0.0
    if cached_input_tokens > 0:
        cached_rate = pricing.get("cached_input", pricing.get("cache_hit", pricing["input"]))
        cached_input_cost = (cached_input_tokens / 1_000_000.0) * cached_rate

    cache_read_cost = 0.0
    if cache_read_tokens > 0:
        cache_read_rate = pricing.get("cache_hit", pricing.get("cached_input", pricing["input"]))
        cache_read_cost = (cache_read_tokens / 1_000_000.0) * cache_read_rate

    cache_write_cost = 0.0
    if cache_write_tokens > 0:
        cache_write_rate = pricing.get("cache_write_5m", pricing["input"])
        cache_write_cost = (cache_write_tokens / 1_000_000.0) * cache_write_rate

    output_cost = (max(0, output_tokens) / 1_000_000.0) * pricing["output"]
    total = input_cost + cached_input_cost + cache_read_cost + cache_write_cost + output_cost
    return round(total, 8), "estimated"


def make_usage_event(
    *,
    agent_name: str,
    model_name: str,
    input_tokens: int,
    output_tokens: int,
    total_tokens: int,
    cached_input_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    metadata: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Create usage event record."""
    cost_usd, pricing_status = estimate_cost_usd(
        model_name,
        input_tokens,
        output_tokens,
        cached_input_tokens=cached_input_tokens,
        cache_read_tokens=cache_read_tokens,
        cache_write_tokens=cache_write_tokens,
    )
    return {
        "agent": agent_name,
        "model": model_name,
        "input_tokens": int(input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(total_tokens),
        "cached_input_tokens": int(cached_input_tokens),
        "cache_read_tokens": int(cache_read_tokens),
        "cache_write_tokens": int(cache_write_tokens),
        "cost_usd": float(cost_usd),
        "pricing_status": pricing_status,
        "metadata": metadata or {},
    }
