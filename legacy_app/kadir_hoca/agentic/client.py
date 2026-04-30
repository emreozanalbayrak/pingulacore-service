"""
Gemini client with PDF caching and structured output.

Replaces Agno framework for guaranteed caching support.
Direct google.genai SDK provides:
- Explicit PDF caching (90% cost reduction)
- Structured output via Pydantic models
- Simple, maintainable API
- Persistent cache storage (survives restarts)
"""
from __future__ import annotations

import json
import os
import logging
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel
from google import genai
from google.genai import types

__all__ = ["GeminiClient", "get_cost_tracker", "CostTracker"]

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


# ============================================================================
# COST TRACKING
# ============================================================================

# Per-million-token pricing (USD) — Gemini models as of April 2026
_MODEL_PRICING: dict[str, dict[str, float]] = {
    "gemini-3-pro-preview":       {"input": 2.00, "output": 12.00, "cached": 0.20},
    "gemini-3.1-pro-preview":     {"input": 2.00, "output": 12.00, "cached": 0.20},
    "gemini-3-flash-preview":     {"input": 0.50, "output": 3.00,  "cached": 0.05},
    "gemini-3.1-flash-preview":   {"input": 0.25, "output": 1.50,  "cached": 0.025},
    "gemini-3-pro-image-preview": {"input": 2.00, "output": 12.00, "cached": 0.20, "image": 0.134},
    "gemini-2.0-flash":           {"input": 0.30, "output": 2.50,  "cached": 0.03},
    "gemini-2.5-flash":           {"input": 0.30, "output": 2.50,  "cached": 0.03},
}


class CostTracker:
    """Accumulates token usage across LLM calls and estimates cost."""

    def __init__(self) -> None:
        self._session_start = datetime.now(timezone.utc).isoformat()
        # model → {input_tokens, output_tokens, cached_tokens, calls}
        self._usage: dict[str, dict[str, int]] = {}
        self._image_count = 0

    def record(self, model: str, response) -> None:
        """Record token usage from a Gemini response."""
        meta = getattr(response, "usage_metadata", None)
        if not meta:
            return
        key = model.lower()
        if key not in self._usage:
            self._usage[key] = {"input_tokens": 0, "output_tokens": 0, "cached_tokens": 0, "calls": 0}
        bucket = self._usage[key]
        bucket["input_tokens"] += getattr(meta, "prompt_token_count", 0) or 0
        bucket["output_tokens"] += getattr(meta, "candidates_token_count", 0) or 0
        bucket["cached_tokens"] += getattr(meta, "cached_content_token_count", 0) or 0
        bucket["calls"] += 1

    def record_image(self) -> None:
        """Record one image generation."""
        self._image_count += 1

    def estimate_cost(self) -> dict:
        """Calculate estimated cost per model + total."""
        models = {}
        total = 0.0
        for model_key, usage in self._usage.items():
            pricing = _MODEL_PRICING.get(model_key, {"input": 1.0, "output": 5.0, "cached": 0.1})
            # Non-cached input = total input - cached portion
            non_cached_input = max(0, usage["input_tokens"] - usage["cached_tokens"])
            cost = (
                non_cached_input * pricing["input"] / 1_000_000
                + usage["output_tokens"] * pricing["output"] / 1_000_000
                + usage["cached_tokens"] * pricing.get("cached", pricing["input"] * 0.1) / 1_000_000
            )
            models[model_key] = {**usage, "estimated_cost_usd": round(cost, 4)}
            total += cost

        # Image cost
        image_cost = self._image_count * 0.134  # per image
        total += image_cost

        return {
            "session_start": self._session_start,
            "models": models,
            "image_count": self._image_count,
            "image_cost_usd": round(image_cost, 4),
            "total_estimated_cost_usd": round(total, 4),
        }

    def print_summary(self) -> None:
        """Print cost summary to terminal."""
        est = self.estimate_cost()
        total_tokens = sum(m["input_tokens"] + m["output_tokens"] for m in est["models"].values())
        total_calls = sum(m["calls"] for m in est["models"].values())
        print(f"\n{'='*50}")
        print(f"MALIYET OZETI")
        print(f"{'='*50}")
        for model, data in est["models"].items():
            print(f"  {model}: {data['calls']} çağrı, {data['input_tokens']+data['output_tokens']} token → ${data['estimated_cost_usd']:.4f}")
        if est["image_count"]:
            print(f"  Görseller: {est['image_count']} adet → ${est['image_cost_usd']:.4f}")
        print(f"{'─'*50}")
        print(f"  TOPLAM: {total_calls} çağrı, {total_tokens} token, {est['image_count']} görsel")
        print(f"  TAHMİNİ MALİYET: ${est['total_estimated_cost_usd']:.4f}")
        print(f"{'='*50}\n")


# Singleton
_cost_tracker: CostTracker | None = None


def get_cost_tracker() -> CostTracker:
    """Get or create the global cost tracker."""
    global _cost_tracker
    if _cost_tracker is None:
        _cost_tracker = CostTracker()
    return _cost_tracker

# Default cache storage location
DEFAULT_CACHE_FILE = Path.home() / ".cache" / "agentic" / "gemini_caches.json"


def _hash_content(content: str) -> str:
    """Create a short hash of content for cache key."""
    return hashlib.md5(content.encode()).hexdigest()[:12]


class GeminiClient:
    """
    Direct google.genai client with:
    - PDF caching (90% cost reduction)
    - Structured output (Pydantic models)
    - Persistent cache storage (reuses caches across restarts)
    - Simple API

    Usage:
        client = GeminiClient()

        # Create cache for PDF-dependent operations (reuses if exists)
        cache_name = client.create_cache(
            pdf_path=Path("textbook.pdf"),
            model="gemini-3-flash-preview",
            system_instruction="You are an expert...",
        )

        # Generate with structured output
        result = await client.generate(
            model="gemini-3-flash-preview",
            prompt="Write about...",
            output_schema=MyPydanticModel,
            cache_name=cache_name,
        )
    """

    def __init__(
        self,
        api_key: str | None = None,
        cache_file: Path | None = None,
    ):
        """
        Initialize the Gemini client.

        Args:
            api_key: Google API key. If not provided, reads from
                     GOOGLE_API_KEY or GEMINI_API_KEY environment variables.
            cache_file: Path to store cache metadata for persistence.
                       Defaults to ~/.cache/agentic/gemini_caches.json

        Raises:
            ValueError: If no API key is found.
        """
        api_key = api_key or os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY environment variable required")

        self._client = genai.Client(api_key=api_key)
        self._cache_file = cache_file or DEFAULT_CACHE_FILE
        self._caches: dict[str, dict] = {}  # cache_key -> {name, model, expires}
        self._uploaded_files: dict[str, types.File] = {}  # path_str -> uploaded File

        # Load persisted cache metadata
        self._load_cache_metadata()

    def _load_cache_metadata(self) -> None:
        """Load cache metadata from persistent storage."""
        if not self._cache_file.exists():
            return

        try:
            with open(self._cache_file, "r") as f:
                data = json.load(f)
                self._caches = data.get("caches", {})
                logger.info(f"[CACHE] Loaded {len(self._caches)} cached entries from disk")
        except Exception as e:
            logger.warning(f"[CACHE] Failed to load cache metadata: {e}")
            self._caches = {}

    def _save_cache_metadata(self) -> None:
        """Save cache metadata to persistent storage."""
        try:
            self._cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self._cache_file, "w") as f:
                json.dump({"caches": self._caches}, f, indent=2)
        except Exception as e:
            logger.warning(f"[CACHE] Failed to save cache metadata: {e}")

    def _is_cache_valid(self, cache_info: dict) -> bool:
        """Check if a cached entry is still valid on Gemini's servers."""
        cache_name = cache_info.get("name")
        if not cache_name:
            return False

        try:
            # Try to get the cache from Gemini
            cache = self._client.caches.get(name=cache_name)

            # Check if it's expired
            if cache.expire_time:
                # Parse the expire_time if it's a string
                if isinstance(cache.expire_time, str):
                    expire_dt = datetime.fromisoformat(cache.expire_time.replace("Z", "+00:00"))
                else:
                    expire_dt = cache.expire_time

                now = datetime.now(timezone.utc)
                if expire_dt <= now:
                    logger.info(f"[CACHE] Cache expired: {cache_name}")
                    return False

            logger.info(f"[CACHE] Cache still valid: {cache_name}")
            return True

        except Exception as e:
            logger.info(f"[CACHE] Cache not found or invalid: {cache_name} ({e})")
            return False

    def _make_cache_key(self, pdf_paths: list[Path], model: str, system_instruction: str) -> str:
        """Create a unique cache key from inputs."""
        paths_str = "|".join(str(p.absolute()) for p in sorted(pdf_paths))
        pdf_hash = _hash_content(paths_str)
        instruction_hash = _hash_content(system_instruction)
        return f"{model}:{pdf_hash}:{instruction_hash}"

    _MIME_TYPES = {
        ".pdf": "application/pdf",
        ".md": "text/markdown",
        ".txt": "text/plain",
        ".html": "text/html",
    }

    def _upload_pdf(self, pdf_path: Path) -> types.File:
        """Upload a file if not already uploaded, return the uploaded File object."""
        path_key = str(pdf_path.absolute())
        if path_key not in self._uploaded_files:
            logger.info(f"[CACHE] Uploading file: {pdf_path.name}")
            print(f"[CACHE] Uploading file: {pdf_path.name}")
            mime_type = self._MIME_TYPES.get(pdf_path.suffix.lower())
            kwargs = {"file": pdf_path}
            if mime_type:
                kwargs["config"] = {"mime_type": mime_type}
            uploaded = self._client.files.upload(**kwargs)
            self._uploaded_files[path_key] = uploaded
            logger.info(f"[CACHE] File uploaded: {uploaded.name}")
        return self._uploaded_files[path_key]

    def create_cache(
        self,
        pdf_path: Path,
        model: str,
        system_instruction: str,
        ttl_seconds: int = 3600,
        extra_pdf_paths: list[Path] | None = None,
    ) -> str:
        """
        Create or reuse cached content for a model.

        The cache includes the PDF(s) and system instruction, which are then
        reused across all subsequent requests to that model.

        Caches are persisted to disk and reused across program restarts
        as long as they haven't expired on Gemini's servers.

        Args:
            pdf_path: Path to the primary PDF file to cache (e.g., MEB textbook).
            model: Gemini model ID (e.g., "gemini-3-flash-preview").
            system_instruction: System prompt to cache with the PDF(s).
            ttl_seconds: Cache time-to-live in seconds (default: 1 hour).
            extra_pdf_paths: Optional additional PDF files to include in cache
                            (e.g., topic-specific data PDFs).

        Returns:
            Cache name string that can be passed to generate().

        Raises:
            FileNotFoundError: If any PDF file doesn't exist.
        """
        # Collect all PDF paths
        all_pdf_paths = [pdf_path]
        if extra_pdf_paths:
            all_pdf_paths.extend(extra_pdf_paths)

        # Validate all paths exist
        for p in all_pdf_paths:
            if not p.exists():
                raise FileNotFoundError(f"PDF not found: {p}")

        # Create cache key from model + all pdfs + system instruction
        cache_key = self._make_cache_key(all_pdf_paths, model, system_instruction)

        # Check if we have a cached entry that's still valid
        if cache_key in self._caches:
            cache_info = self._caches[cache_key]
            if self._is_cache_valid(cache_info):
                cache_name = cache_info["name"]
                print(f"[CACHE] Reusing existing cache for {model}")
                logger.info(f"[CACHE] Reusing cache: {cache_name}")
                return cache_name
            else:
                # Cache expired or invalid, remove it
                del self._caches[cache_key]

        # Upload all PDFs
        uploaded_files = [self._upload_pdf(p) for p in all_pdf_paths]

        # Create cache
        pdf_names = ", ".join(p.name for p in all_pdf_paths)
        logger.info(f"[CACHE] Creating cache for model {model} with {len(all_pdf_paths)} PDF(s)...")
        print(f"[CACHE] Creating cache for model {model} ({pdf_names})...")

        cache = self._client.caches.create(
            model=model,
            config=types.CreateCachedContentConfig(
                system_instruction=system_instruction,
                contents=uploaded_files,
                ttl=f"{ttl_seconds}s",
            ),
        )

        cache_name = cache.name

        # Store cache metadata for persistence
        self._caches[cache_key] = {
            "name": cache_name,
            "model": model,
            "pdf_paths": [str(p.absolute()) for p in all_pdf_paths],
            "created": datetime.now(timezone.utc).isoformat(),
        }
        self._save_cache_metadata()

        logger.info(f"[CACHE] Cache created: {cache_name}")
        print(f"[CACHE] Cache created for {model} (TTL: {ttl_seconds}s, {len(all_pdf_paths)} PDF(s))")

        return cache_name

    async def generate(
        self,
        model: str,
        prompt: str,
        output_schema: type[T],
        cache_name: str | None = None,
        system_instruction: str | None = None,
    ) -> T:
        """
        Generate content with structured output.

        Args:
            model: Gemini model ID.
            prompt: User prompt/message.
            output_schema: Pydantic model class for structured output.
            cache_name: Optional cache name from create_cache().
                        If provided, the cached PDF and system instruction
                        are automatically included.
            system_instruction: Optional system instruction for non-cached calls.
                               Ignored if cache_name is provided.

        Returns:
            Instance of output_schema populated with the model's response.

        Raises:
            Exception: If generation fails or response cannot be parsed.
        """
        # Build generation config
        config = types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=output_schema,
            temperature=0.5,
        )

        # Add cache if provided
        if cache_name:
            config.cached_content = cache_name
        elif system_instruction:
            # For non-cached calls, include system instruction in config
            config.system_instruction = system_instruction

        # Log the full prompt being sent
        logger.debug(
            f"[LLM REQUEST]\n"
            f"{'='*80}\n"
            f"Model: {model}\n"
            f"Schema: {output_schema.__name__}\n"
            f"Cache: {cache_name or 'none'}\n"
            f"System instruction: {'(from cache)' if cache_name else (system_instruction or 'none')}\n"
            f"{'-'*80}\n"
            f"PROMPT:\n{prompt}\n"
            f"{'='*80}"
        )

        # Generate content
        response = await self._client.aio.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )

        # Track token usage for cost estimation
        get_cost_tracker().record(model, response)

        # Log the raw LLM response
        logger.debug(
            f"[LLM RESPONSE]\n"
            f"{'='*80}\n"
            f"Model: {model}\n"
            f"Schema: {output_schema.__name__}\n"
            f"{'-'*80}\n"
            f"RAW OUTPUT:\n{response.text}\n"
            f"{'='*80}"
        )

        # Parse response into Pydantic model
        parsed = output_schema.model_validate_json(response.text)

        logger.debug(
            f"[LLM PARSED] {output_schema.__name__} parsed successfully"
        )

        return parsed

