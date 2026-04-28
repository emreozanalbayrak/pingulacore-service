"""
Generic Question Workflow - template-driven question generation with full features.

This workflow integrates:
- MEB PDF grounding (caching)
- Template-level model configuration
- Deterministic constraints (paragraph, option, formatting)
- Batch validation (2 LLM calls instead of 6-7 sequential)
- Smart retry/fix loops with routing to responsible agent

Usage:
    workflow = GenericQuestionWorkflow(
        curriculum_context=meb_context,
        default_models={"paragraph_writer": "gemini-2.0-flash"},
        required_checks=["question_format", "accuracy", "distractors"],
    )

    result = await workflow.generate(
        template_id="ana_fikir",
        topic="OYUN DUNYASI / Okuma Becerileri / Ana Fikri Belirleme",
        grade=5,
    )
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from pathlib import Path
from typing import Callable, TYPE_CHECKING

from .client import GeminiClient
from .schemas import (
    QuestionGenerationResult,
    ValidationOutput,
    ValidationCheckOutput,
    ContextSubQuestionResult,
    CrossValidationResult,
    ContextQuestionGroupResult,
    MultiQuestionGenerationResult,
    SingleQuestionResult,
)
from .templates import TemplateLoader, QuestionTemplate
from .templates.schema import BeceriConfig
from .generators import get_generator, GeneratorOutput
from .batch_validator import (
    BatchValidator,
    BatchValidationResult,
    DEFAULT_REQUIRED_CHECKS,
    enrich_validation_feedback,
)
from .tools.constraints import (
    ParagraphConstraintsConfig,
    OptionWordCountConfig,
    FormattingConstraintsConfig,
    evaluate_paragraph_constraints,
    evaluate_option_word_count,
    evaluate_option_length_balance,
    evaluate_formatting,
    build_constraints_from_template,
    ContextConstraintsConfig,
    evaluate_context_constraints,
    build_context_constraints_from_template,
    map_option_error_categories,
    check_banned_options,
    check_hikaye_unsur_options,
    check_metin_turu_options,
    check_absolute_expressions,
    check_context_bold_leak,
    check_bracket_remnants,
    check_verbatim_copy,
    compute_publication_status,
)
from .prompts.paragraph_prompts import PARAGRAPH_SYSTEM_PROMPT
from .prompts.validator_prompts import VALIDATOR_SYSTEM_PROMPT
from .client import get_cost_tracker
from .tools.image_tools import ImageGeneratorConfig, generate_diagram_with_judge, generate_poster_with_judge, generate_option_images_grid

if TYPE_CHECKING:
    from .tools.curriculum_tools import MEBCurriculumContext

__all__ = [
    "GenericQuestionWorkflow",
    "generate_question_from_template",
]

logger = logging.getLogger(__name__)

# Default model fallback
DEFAULT_MODEL = "gemini-3-flash-preview"


# ============================================================================
# OPTION SHUFFLING
# ============================================================================


def shuffle_options(
    options: dict[str, str],
    correct_answer: str,
    option_reasoning: dict[str, dict] | None = None,
    answer_history: list[str] | None = None,
) -> tuple[dict[str, str], str, dict[str, dict] | None]:
    """
    Shuffle options to randomize correct answer position.

    Dynamically supports any number of options (4 or 5).

    Uses answer_history for balanced distribution:
    - Prefers the LEAST-USED letter across history
    - Avoids consecutive same answers (last answer)
    - Tries up to 20 shuffles to find the best placement
    """
    letters = sorted(options.keys())
    n = len(letters)

    option_values = [options.get(l, "") for l in letters]
    correct_value = options.get(correct_answer, "")

    reasoning_values = None
    if option_reasoning:
        reasoning_values = [option_reasoning.get(l, {}) for l in letters]

    # Build preference: least-used letters first, avoid last answer
    preferred_letters: list[str] = []
    avoid_last: str = ""
    if answer_history:
        # Count usage of each letter
        counts = {l: 0 for l in letters}
        for ans in answer_history:
            if ans in counts:
                counts[ans] += 1
        # Sort by count ascending — least used first
        preferred_letters = sorted(letters, key=lambda x: counts[x])
        # Avoid last answer for consecutive prevention
        avoid_last = answer_history[-1] if answer_history else ""

    best_shuffled = None
    best_correct = correct_answer
    best_reasoning = None
    best_score = -1
    max_attempts = 20 if answer_history else 1

    for _ in range(max_attempts):
        indices = list(range(n))
        random.shuffle(indices)

        shuffled = {letters[i]: option_values[indices[i]] for i in range(n)}

        new_correct = correct_answer
        for i, idx in enumerate(indices):
            if option_values[idx] == correct_value:
                new_correct = letters[i]
                break

        shuffled_r = None
        if reasoning_values:
            shuffled_r = {letters[i]: reasoning_values[indices[i]] for i in range(n)}

        # Score this shuffle: higher = better
        score = 0
        if preferred_letters:
            # Prefer least-used letter (index 0 = least used)
            try:
                rank = preferred_letters.index(new_correct)
                score += (n - 1 - rank) * 10  # Higher for least used, 0 for most used
            except ValueError:
                pass
        if new_correct != avoid_last:
            score += 50  # Big bonus for not repeating last answer

        if score > best_score:
            best_score = score
            best_shuffled = shuffled
            best_correct = new_correct
            best_reasoning = shuffled_r

        # Perfect score — stop early
        if score >= 80:
            break

    return best_shuffled, best_correct, best_reasoning  # type: ignore[return-value]


# ============================================================================
# VALIDATION RESULT CONVERSION
# ============================================================================


def _batch_to_validation_output(batch_result: BatchValidationResult) -> ValidationOutput:
    """Convert BatchValidationResult to ValidationOutput for compatibility."""
    checks = []
    for check in batch_result.checks.values():
        checks.append(
            ValidationCheckOutput(
                check_type=check.check_type,
                check_name=check.check_name,
                status=check.status,
                score=check.score,
                feedback=check.feedback,
                issues=check.issues,
                suggestions=check.suggestions,
                affected_components=check.affected_components,  # type: ignore
            )
        )

    return ValidationOutput(
        passed=batch_result.passed,
        checks=checks,
        overall_score=batch_result.overall_score,
    )


# ============================================================================
# VISUAL CONTEXT HELPERS
# ============================================================================


def _replace_metin_with_gorsel(question: str) -> str:
    """Replace 'metin' references with 'görsel' in question stems for visual_context mode.

    When paragraph is hidden and a visual is shown instead, question stems
    should reference the visual, not the text.
    """
    # Order matters: longer patterns first to avoid partial replacements
    replacements = [
        # "Bu metinde" → "Bu görselde"
        (r"\bBu metinde\b", "Bu görselde"),
        (r"\bbu metinde\b", "bu görselde"),
        # "Bu metnin" → "Bu görselin"
        (r"\bBu metnin\b", "Bu görselin"),
        (r"\bbu metnin\b", "bu görselin"),
        # "Bu metne" → "Bu görsele"
        (r"\bBu metne\b", "Bu görsele"),
        (r"\bbu metne\b", "bu görsele"),
        # "Bu metin" → "Bu görsel" (standalone)
        (r"\bBu metin\b", "Bu görsel"),
        (r"\bbu metin\b", "bu görsel"),
        # "metinde" → "görselde" (generic, e.g. "Aşağıdaki metinde")
        (r"\bmetinde\b", "görselde"),
        # "metnin" → "görselin"
        (r"\bmetnin\b", "görselin"),
        # "metne" → "görsele"
        (r"\bmetne\b", "görsele"),
        # "metinden" → "görselden"
        (r"\bmetinden\b", "görselden"),
        # "metindeki" → "görseldeki"
        (r"\bmetindeki\b", "görseldeki"),
        (r"\bMetindeki\b", "Görseldeki"),
        # "Metinde" (sentence start)
        (r"\bMetinde\b", "Görselde"),
        (r"\bMetnin\b", "Görselin"),
    ]
    result = question
    for pattern, replacement in replacements:
        result = re.sub(pattern, replacement, result)
    return result


# ============================================================================
# GENERIC WORKFLOW
# ============================================================================


class GenericQuestionWorkflow:
    """
    Template-driven question generation workflow with full features.

    This workflow:
    1. Loads template by ID (e.g., "ana_fikir")
    2. Resolves models from template > config > fallback
    3. Gets format-specific generator (e.g., SingleParagraphMCGenerator)
    4. Generates paragraph with optional constraint enforcement
    5. Generates question with optional option balance checks
    6. Applies formatting normalization
    7. Runs BATCH validation (2 LLM calls instead of 6-7)
    8. Smart routing + retry if validation fails

    Example:
        workflow = GenericQuestionWorkflow(
            curriculum_context=meb_context,
            default_models={"paragraph_writer": "gemini-2.0-flash"},
        )
        result = await workflow.generate(
            template_id="ana_fikir",
            topic="OYUN DUNYASI / Okuma Becerileri",
            grade=5,
        )
    """

    def __init__(
        self,
        curriculum_context: "MEBCurriculumContext | None" = None,
        templates_dir: Path | None = None,
        use_caching: bool = True,
        default_models: dict[str, str] | None = None,
        required_checks: list[str] | None = None,
        max_fix_iterations: int = 3,
        paragraph_constraints: ParagraphConstraintsConfig | None = None,
        formatting_constraints: FormattingConstraintsConfig | None = None,
        image_config: ImageGeneratorConfig | None = None,
    ):
        """
        Initialize the generic workflow.

        Args:
            curriculum_context: MEB curriculum context for PDF grounding.
                              If None, questions won't be grounded in MEB textbook.
            templates_dir: Path to templates directory.
                          Defaults to project_root/templates/
            use_caching: Whether to enable PDF caching (default: True)
            default_models: Dict of default models for each role:
                          {"paragraph_writer": "...", "question_crafter": "...", "validator": "..."}
            required_checks: List of validation checks to run (default: all)
            max_fix_iterations: Maximum retry attempts for validation failures (default: 3)
            paragraph_constraints: Optional deterministic paragraph constraints
            formatting_constraints: Optional formatting constraints
            image_config: Optional image generation configuration
        """
        self.curriculum_context = curriculum_context
        self.use_caching = use_caching
        self.default_models = default_models or {}
        self.required_checks = required_checks or DEFAULT_REQUIRED_CHECKS
        self.max_fix_iterations = max_fix_iterations

        # Constraint configs
        self.paragraph_constraints = paragraph_constraints
        self.formatting_constraints = formatting_constraints or FormattingConstraintsConfig()
        self.image_config = image_config

        # Answer distribution tracking (prevents consecutive same answers)
        self._answer_history: list[str] = []

        # Initialize components
        self.template_loader = TemplateLoader(templates_dir)
        self.client = GeminiClient()

        # Create caches if curriculum context is provided
        self._paragraph_cache: str | None = None
        self._validator_cache: str | None = None

        if use_caching and curriculum_context and curriculum_context.pdf_path:
            ttl = curriculum_context.cache_config.ttl_seconds

            # Collect extra PDFs (e.g., topic-specific data PDFs)
            extra_pdfs = list(curriculum_context.data_pdf_paths)

            # Cache for paragraph generation
            para_model = self.default_models.get("paragraph_writer", DEFAULT_MODEL)
            self._paragraph_cache = self.client.create_cache(
                pdf_path=curriculum_context.pdf_path,
                model=para_model,
                system_instruction=PARAGRAPH_SYSTEM_PROMPT,
                ttl_seconds=ttl,
                extra_pdf_paths=extra_pdfs or None,
            )

            # Cache for validation (PDF-required checks)
            validator_model = self.default_models.get("validator", DEFAULT_MODEL)
            self._validator_cache = self.client.create_cache(
                pdf_path=curriculum_context.pdf_path,
                model=validator_model,
                system_instruction=VALIDATOR_SYSTEM_PROMPT,
                ttl_seconds=ttl,
                extra_pdf_paths=extra_pdfs or None,
            )

    def _resolve_model(self, template: QuestionTemplate, role: str) -> str:
        """
        Resolve model for a given role using precedence:
        1. Template-specific model (if defined)
        2. Config default model
        3. Hardcoded fallback: gemini-2.0-flash
        """
        # Check template-level override
        if template.models:
            template_model = getattr(template.models, role, None)
            if template_model:
                return template_model

        # Check config default
        if role in self.default_models:
            return self.default_models[role]

        # Fallback
        return DEFAULT_MODEL

    async def _try_generate_answer_critical_visual(
        self,
        result: QuestionGenerationResult,
        template: Any,
        subject: str,
        log: Callable[[str], None],
        image_config: ImageGeneratorConfig | None = None,
    ) -> bool:
        """
        Generate an answer-critical visual (Bolum 7 templates where the image
        IS the stimulus for the question).

        Returns True on success, False on failure. Unlike _try_generate_image,
        failures here HARD-FAIL the question (caller should set result.success=False).

        Passes question + correct_answer + visual_spec to the image generator's
        answer-aware prompt + judge loop.
        """
        from .tools.image_tools import generate_answer_critical_visual

        cfg = image_config if image_config is not None else self.image_config
        if not cfg or not cfg.enabled:
            log("[IMAGE-CRITIC] image_generation disabled — cannot produce answer-critical visual")
            return False

        # For visual-only templates (paragraph.required=false, e.g., 7.2 gorsel_inceleme),
        # use question + options as the content basis for image generation
        content_text = result.paragraph or ""
        if not content_text and result.question:
            # Build a content description from question + options for the image generator
            opts_desc = "; ".join(f"{k}: {v}" for k, v in (result.options or {}).items())
            content_text = f"Soru: {result.question}\nSecenekler: {opts_desc}"

        if not content_text:
            log("[IMAGE-CRITIC] Ne paragraf ne de soru var, answer-critical visual uretilemez")
            return False

        visual_type = getattr(template, "visual_type", None) or "generic"
        visual_spec = getattr(template, "visual_spec", None) or {}
        log(f"[IMAGE-CRITIC] Answer-critical visual olusturuluyor (tip: {visual_type})...")

        try:
            image_result = await generate_answer_critical_visual(
                paragraph=content_text,
                question=result.question or "",
                correct_answer=result.correct_answer or "",
                options=result.options or {},
                visual_type=visual_type,
                visual_spec=visual_spec,
                subject=subject,
                cfg=cfg,
            )
            if image_result.success and image_result.png_base64:
                result.has_image = True
                result.image_base64 = image_result.png_base64
                get_cost_tracker().record_image()
                log(
                    f"[IMAGE-CRITIC] OK (judge iterations: {image_result.judge_iterations})"
                )
                return True
            log(f"[IMAGE-CRITIC] BASARISIZ: {image_result.error or 'bilinmeyen'}")
            return False
        except Exception as e:
            logger.warning(f"[IMAGE-CRITIC] Hata: {e}")
            log(f"[IMAGE-CRITIC] Hata: {e}")
            return False

    async def _try_generate_image(
        self,
        result: QuestionGenerationResult,
        subject: str,
        log: Callable[[str], None],
        image_config: ImageGeneratorConfig | None = None,
    ) -> None:
        """
        Attempt to generate a diagram image for the question.

        Non-blocking: errors are logged but don't affect result.success.
        Skips if image_config is None/disabled, paragraph is empty (inverse),
        or subject doesn't match required_subjects filter.

        Args:
            result: The question generation result to attach the image to.
            subject: Subject code for filtering.
            log: Progress logging callback.
            image_config: Optional override config; falls back to self.image_config.
        """
        cfg = image_config if image_config is not None else self.image_config
        if not cfg or not cfg.enabled:
            return

        # Skip if no paragraph (e.g., inverse templates)
        if not result.paragraph:
            logger.info("[IMAGE] Paragraf yok (inverse template), gorsel uretim atlanıyor")
            return

        log("[IMAGE] Diyagram olusturuluyor...")
        try:
            image_result = await generate_diagram_with_judge(
                paragraph=result.paragraph,
                subject=subject,
                cfg=cfg,
            )
            if image_result.success and image_result.png_base64:
                result.has_image = True
                result.image_base64 = image_result.png_base64
                get_cost_tracker().record_image()
                log(f"[IMAGE] Diyagram basarili (judge iterations: {image_result.judge_iterations})")
            else:
                log(f"[IMAGE] Diyagram olusturulamadi: {image_result.error or 'bilinmeyen hata'}")
        except Exception as e:
            logger.warning(f"[IMAGE] Gorsel uretim hatasi (non-blocking): {e}")
            log(f"[IMAGE] Gorsel uretim hatasi: {e}")

    async def _try_generate_poster(
        self,
        result: QuestionGenerationResult,
        topic: str,
        log: Callable[[str], None],
        image_config: ImageGeneratorConfig | None = None,
    ) -> None:
        """
        Generate a poster (afiş) image as primary context.

        Unlike _try_generate_image (supplementary diagram), this creates
        a poster that IS the main visual context for the question.
        Auto-enables image generation regardless of config.

        Non-blocking: errors are logged but don't affect result.success.
        """
        # Build config - auto-enable for poster generation
        cfg = image_config if image_config is not None else self.image_config
        if not cfg:
            cfg = ImageGeneratorConfig(enabled=True)
        else:
            # Create a copy with enabled=True
            cfg = ImageGeneratorConfig(
                enabled=True,
                model=cfg.model,
                judge_model=cfg.judge_model,
                temperature=cfg.temperature,
                max_retries=cfg.max_retries,
                max_judge_iterations=cfg.max_judge_iterations,
            )

        if not result.paragraph:
            logger.info("[POSTER] Paragraf yok, poster uretim atlanıyor")
            return

        log("[IMAGE] Afis/poster olusturuluyor...")
        try:
            image_result = await generate_poster_with_judge(
                paragraph=result.paragraph,
                topic=topic,
                cfg=cfg,
                grade=grade,
            )
            if image_result.success and image_result.png_base64:
                result.has_image = True
                result.image_base64 = image_result.png_base64
                get_cost_tracker().record_image()
                result.image_context = True  # Flag: image is primary context
                log(f"[IMAGE] Afis basarili (judge iterations: {image_result.judge_iterations})")
            else:
                log(f"[IMAGE] Afis olusturulamadi: {image_result.error or 'bilinmeyen hata'}")
        except Exception as e:
            logger.warning(f"[POSTER] Gorsel uretim hatasi (non-blocking): {e}")
            log(f"[IMAGE] Afis uretim hatasi: {e}")

    async def _try_generate_infographic(
        self,
        result: QuestionGenerationResult,
        topic: str,
        log: Callable[[str], None],
        image_config: ImageGeneratorConfig | None = None,
    ) -> None:
        """
        Generate an infographic image as primary context.

        Similar to _try_generate_poster but creates a data-dense infographic
        (charts, categories, process diagrams) instead of a poster.
        Auto-enables image generation regardless of config.

        Non-blocking: errors are logged but don't affect result.success.
        """
        cfg = image_config if image_config is not None else self.image_config
        if not cfg:
            cfg = ImageGeneratorConfig(enabled=True)
        else:
            cfg = ImageGeneratorConfig(
                enabled=True,
                model=cfg.model,
                judge_model=cfg.judge_model,
                temperature=cfg.temperature,
                max_retries=cfg.max_retries,
                max_judge_iterations=cfg.max_judge_iterations,
            )

        if not result.paragraph:
            logger.info("[INFOGRAPHIC] Paragraf yok, infografik uretim atlaniyor")
            return

        log("[IMAGE] Infografik olusturuluyor...")
        try:
            from .tools.image_tools import generate_context_image_with_judge

            image_result = await generate_context_image_with_judge(
                context_text=result.paragraph,
                topic=topic,
                image_type="infografik",
                cfg=cfg,
                grade=grade,
            )
            if image_result.success and image_result.png_base64:
                result.has_image = True
                result.image_base64 = image_result.png_base64
                get_cost_tracker().record_image()
                result.image_context = True  # Flag: image is primary context
                log(f"[IMAGE] Infografik basarili (judge iterations: {image_result.judge_iterations})")
            else:
                log(f"[IMAGE] Infografik olusturulamadi: {image_result.error or 'bilinmeyen hata'}")
        except Exception as e:
            logger.warning(f"[INFOGRAPHIC] Gorsel uretim hatasi (non-blocking): {e}")
            log(f"[IMAGE] Infografik uretim hatasi: {e}")

    async def _try_generate_question_visual(
        self,
        result: QuestionGenerationResult,
        template_id: str,
        topic: str,
        log: Callable[[str], None],
        image_config: ImageGeneratorConfig | None = None,
    ) -> None:
        """
        Generate a question-aware visual that replaces the paragraph.

        The visual must contain enough information for the student to
        answer the question without seeing the paragraph text.
        The AI chooses the best visual format (speech bubbles, poster,
        infographic, scene, table, etc.) based on question type.

        Auto-enables image generation regardless of global config.
        Non-blocking: errors logged but don't affect result.success.
        """
        cfg = image_config if image_config is not None else self.image_config
        if not cfg:
            cfg = ImageGeneratorConfig(enabled=True)
        else:
            cfg = ImageGeneratorConfig(
                enabled=True,
                model=cfg.model,
                judge_model=cfg.judge_model,
                temperature=cfg.temperature,
                max_retries=cfg.max_retries,
                max_judge_iterations=cfg.max_judge_iterations,
            )

        # Build visual content: use paragraph if available, otherwise construct from options
        visual_content = result.paragraph
        if not visual_content and result.options:
            # For inverse/no-paragraph templates (anlatici_turleri, paragraf_metin, etc.)
            # the content lives in the options — build a context string from them
            visual_content = "\n".join(
                f"{label}) {text}" for label, text in sorted(result.options.items())
            )
            logger.info("[VISUAL] Paragraf yok, seceneklerden gorsel icerigi olusturuluyor")

        if not visual_content:
            logger.info("[VISUAL] Ne paragraf ne secenek var, gorsel uretim atlaniyor")
            return

        log("[IMAGE] Soru-odakli gorsel olusturuluyor...")
        try:
            from .tools.image_tools import generate_question_visual_with_judge

            image_result = await generate_question_visual_with_judge(
                paragraph=visual_content,
                question=result.question,
                options=result.options,
                correct_answer=result.correct_answer,
                template_id=template_id,
                topic=topic,
                cfg=cfg,
            )
            if image_result.success and image_result.png_base64:
                result.has_image = True
                result.image_base64 = image_result.png_base64
                result.image_context = True  # Hide paragraph in HTML
                # Replace "metin" references with "görsel" in question stem
                result.question = _replace_metin_with_gorsel(result.question)
                log(f"[IMAGE] Gorsel basarili (judge iterations: {image_result.judge_iterations})")
            else:
                log(f"[IMAGE] Gorsel olusturulamadi: {image_result.error or 'bilinmeyen hata'}")
        except Exception as e:
            logger.warning(f"[VISUAL] Gorsel uretim hatasi (non-blocking): {e}")
            log(f"[IMAGE] Gorsel uretim hatasi: {e}")

    async def _generate_option_images(
        self,
        result: QuestionGenerationResult,
        template: "QuestionTemplate",
        log: Callable[[str], None],
        image_config: ImageGeneratorConfig | None = None,
    ) -> None:
        """
        Generate images for each option (gorsel_siklar templates).

        Uses a SINGLE API call to generate all 4 options as a 2x2 grid,
        then crops into individual images. This ensures visual consistency
        (same style, colors, fonts) across all options.

        Args:
            result: The question result containing option descriptions.
            template: The template (for image_style config).
            log: Progress logging callback.
            image_config: Optional override config.
        """
        cfg = image_config if image_config is not None else self.image_config
        if not cfg:
            cfg = ImageGeneratorConfig(enabled=True)
        else:
            cfg = ImageGeneratorConfig(
                enabled=True,
                model=cfg.model,
                judge_model=cfg.judge_model,
                temperature=cfg.temperature,
                max_retries=cfg.max_retries,
                max_judge_iterations=cfg.max_judge_iterations,
            )

        image_style = getattr(template.format.options, "image_style", "photo") or "photo"
        option_count = len(result.options)
        shared_format = result.shared_visual_format or ""
        log(f"[IMAGE] Secenek gorselleri olusturuluyor (tek grid call, stil: {image_style})...")
        if shared_format:
            log(f"[IMAGE] Ortak format: {shared_format[:80]}...")

        # Single call: generate 2x2 grid, then crop
        grid_results = await generate_option_images_grid(
            options=result.options,
            image_style=image_style,
            cfg=cfg,
            shared_visual_format=shared_format,
        )

        option_images: dict[str, str] = {}
        for label, img_result in grid_results.items():
            if img_result.success and img_result.png_base64:
                option_images[label] = img_result.png_base64
                log(f"[IMAGE] Sik {label} gorsel basarili")
            else:
                log(f"[IMAGE] Sik {label} olusturulamadi: {img_result.error or 'bilinmeyen hata'}")

        if option_images:
            result.option_images = option_images
            log(f"[IMAGE] {len(option_images)}/{option_count} secenek gorseli olusturuldu")
        else:
            log("[IMAGE] Hicbir secenek gorseli olusturulamadi — metin tasvir fallback")

    def _apply_formatting(
        self,
        result: QuestionGenerationResult,
        log: Callable[[str], None],
    ) -> None:
        """Apply formatting normalization to result in-place."""
        formatting_report = evaluate_formatting(
            paragraph=result.paragraph,
            question=result.question,
            options=result.options,
            cfg=self.formatting_constraints,
        )
        if formatting_report.normalization_applied:
            log(f"      Düzeltmeler: {', '.join(formatting_report.normalization_applied)}")
        result.paragraph = formatting_report.normalized_paragraph
        result.question = formatting_report.normalized_question
        result.options = formatting_report.normalized_options

    @staticmethod
    def _normalize_multiline_labeled_options(options: dict[str, str]) -> dict[str, str]:
        """Convert comma-separated labeled elements to <br>-separated vertical format.

        Used for element_set_labeled_multiline style (hikaye unsurlari).
        Pattern: "Zaman: X, Mekan: Y, Kişi: Z" → "Zaman: X<br>Mekan: Y<br>Kişi: Z"
        """
        import re
        label_re = re.compile(
            r"(?:\s*[-–—]\s*|,\s*)(?=(?:Zaman|Mekan|Mekân|Yer|Kişi|Kişiler|Kisi|Kisiler|Olay)\s*:)",
            re.IGNORECASE,
        )
        return {k: label_re.sub("<br>", v) for k, v in options.items()}

    @staticmethod
    def _normalize_element_label_options(options: dict[str, str]) -> dict[str, str]:
        """Extract bare hikaye unsur label from value-laden options and uppercase.

        Used for element_label style (hangi_hikaye_unsuru_belirtilmemistir).
        "Zaman: Cumartesi sabahı" → "ZAMAN"
        "Kişiler" → "KİŞİ"
        """
        import re
        import unicodedata

        def tr_lower(s: str) -> str:
            # Turkish-safe lowercase — strip combining marks (İ→i, not i̇)
            s = s.replace("İ", "i").replace("I", "ı")
            s = s.lower()
            # Remove combining characters (U+0307 etc.) that Python adds
            s = "".join(c for c in unicodedata.normalize("NFD", s)
                        if unicodedata.category(c) != "Mn" or c == "̇" and False)
            # Simpler: just drop U+0307 combining dot above
            return s.replace("̇", "")

        canonical_by_base = {
            "zaman": "Zaman",
            "mekan": "Mekan",
            "mekân": "Mekan",
            "yer": "Mekan",
            "kişi": "Kişi",
            "kisi": "Kişi",
            "kişiler": "Kişi",
            "kisiler": "Kişi",
            "olay": "Olay",
        }
        label_re = re.compile(
            r"(Zaman|Mekan|Mekân|Yer|Kişi|Kişiler|Kisi|Kisiler|Olay|ZAMAN|MEKAN|MEKÂN|YER|KİŞİ|KİŞİLER|KISI|KISILER|OLAY)",
            re.IGNORECASE,
        )
        result: dict[str, str] = {}
        for k, v in options.items():
            stripped = re.sub(r"<[^>]+>", "", v).strip()
            m = label_re.search(stripped)
            if m:
                key = tr_lower(m.group(1))
                result[k] = canonical_by_base.get(key, v)
            else:
                result[k] = v
        return result

    def _evaluate_constraints(
        self,
        result: QuestionGenerationResult,
        effective_para_cfg: ParagraphConstraintsConfig | None,
        effective_opt_wc_cfg: OptionWordCountConfig | None,
        label: str = "",
        template_id: str = "",
    ) -> str:
        """
        Run deterministic constraint checks and return feedback text.

        Returns empty string if all constraints pass.
        """
        feedback = ""
        prefix = f"Retry {label} - " if label else ""

        if effective_para_cfg and effective_para_cfg.enabled and result.paragraph:
            para_report = evaluate_paragraph_constraints(
                result.paragraph, effective_para_cfg
            )
            wc = para_report.metrics.word_count
            sc = para_report.metrics.sentence_count
            if para_report.passed:
                logger.info(
                    f"[CONSTRAINT] {prefix}Paragraf OK: {wc} kelime, {sc} cumle"
                )
            else:
                violations_str = (
                    ", ".join(para_report.violations)
                    if para_report.violations
                    else "bilinmeyen"
                )
                logger.warning(
                    f"[CONSTRAINT] {prefix}Paragraf IHLAL ({violations_str}): "
                    f"{wc} kelime, {sc} cumle "
                    f"(hedef: {effective_para_cfg.word_min}-"
                    f"{effective_para_cfg.word_max} kelime, "
                    f"{effective_para_cfg.sentence_min}-"
                    f"{effective_para_cfg.sentence_max} cumle)"
                )
                feedback += (
                    "PARAGRAF OLCU IHLALI (DETERMINISTIK):\n"
                    + para_report.to_feedback_text(effective_para_cfg)
                    + "\n\n"
                )

        if effective_opt_wc_cfg and effective_opt_wc_cfg.enabled:
            opt_wc_report = evaluate_option_word_count(
                result.options, effective_opt_wc_cfg
            )
            if opt_wc_report.passed:
                logger.info(
                    f"[CONSTRAINT] {prefix}Secenek kelime sayilari OK"
                )
            else:
                logger.warning(
                    f"[CONSTRAINT] {prefix}Secenek kelime IHLAL: "
                    f"{opt_wc_report.violations}"
                )
                feedback += (
                    "SECENEK KELIME SAYISI IHLALI (DETERMINISTIK):\n"
                    + opt_wc_report.to_feedback_text(effective_opt_wc_cfg)
                    + "\n\n"
                )

        # Banned options check (hepsi/hiçbiri)
        banned_ok, banned_feedback = check_banned_options(result.options)
        if banned_ok:
            logger.info(f"[CONSTRAINT] {prefix}Yasakli secenek kontrolu OK")
        else:
            logger.warning(f"[CONSTRAINT] {prefix}Yasakli secenek IHLAL")
            feedback += banned_feedback + "\n"

        # Hikaye unsur option check (only for hangi_hikaye_unsuru_belirtilmemistir templates)
        if template_id and "hangi_hikaye_unsuru_belirtilmemistir" in template_id:
            hu_ok, hu_feedback = check_hikaye_unsur_options(result.options)
            if hu_ok:
                logger.info(f"[CONSTRAINT] {prefix}Hikaye unsur secenek kontrolu OK")
            else:
                logger.warning(f"[CONSTRAINT] {prefix}Hikaye unsur secenek IHLAL")
                feedback += hu_feedback + "\n"

        # Metin turu option check (only for metin_turleri_standard templates)
        if template_id and "metin_turleri_standard" in template_id:
            mt_ok, mt_feedback = check_metin_turu_options(result.options)
            if mt_ok:
                logger.info(f"[CONSTRAINT] {prefix}Metin turu secenek kontrolu OK")
            else:
                logger.warning(f"[CONSTRAINT] {prefix}Metin turu secenek IHLAL")
                feedback += mt_feedback + "\n"

        # Mutlak ifade kontrolü
        abs_ok, abs_feedback = check_absolute_expressions(result.question, result.options, template_id=template_id)
        if abs_ok:
            logger.info(f"[CONSTRAINT] {prefix}Mutlak ifade kontrolu OK")
        else:
            logger.warning(f"[CONSTRAINT] {prefix}Mutlak ifade IHLAL")
            feedback += abs_feedback + "\n"

        # Birebir kopyalama kontrolü — SOFT MODE: retry tetiklemez, sadece uyari
        _para_text = result.paragraph or ""
        _correct_letter = result.correct_answer or ""
        _correct_text = result.options.get(_correct_letter, "")
        verbatim_ok, verbatim_feedback = check_verbatim_copy(
            _para_text, _correct_text, _correct_letter
        )
        if verbatim_ok:
            logger.info(f"[CONSTRAINT] {prefix}Birebir kopyalama kontrolu OK")
        else:
            logger.warning(
                f"[CONSTRAINT] {prefix}Birebir kopyalama IHLAL (soft warn, retry tetiklenmez)"
            )
            # Soft mode: feedback retry'a gitmez; LLM validator check'leri karar verir

        # Köşeli parantez kalıntısı kontrolü
        bracket_ok, bracket_feedback = check_bracket_remnants(result.question, result.options)
        if bracket_ok:
            logger.info(f"[CONSTRAINT] {prefix}Koseli parantez kontrolu OK")
        else:
            logger.warning(f"[CONSTRAINT] {prefix}Koseli parantez IHLAL")
            feedback += bracket_feedback + "\n"

        # B3 sıralama soruları deterministik kontrolleri
        _re = re
        _para = result.paragraph or ""
        _stem = result.question or ""
        _is_numbered = bool(_re.search(r'\(\d+\)', _para))

        if _is_numbered:
            # Check: paragraf (1) ile başlamalı — giriş cümlesi OLMAMALI
            _stripped = _para.strip()
            if _stripped.startswith("(1)") or _stripped.startswith("("):
                logger.info(f"[CONSTRAINT] {prefix}Siralama: paragraf (1) ile basliyor — OK")
            else:
                logger.warning(f"[CONSTRAINT] {prefix}Siralama: paragraf giris cumlesiyle basliyor — (1) ile baslamali")
                feedback += (
                    "SIRALAMA FORMAT IHLALI (DETERMINISTIK):\n"
                    "Paragraf giriş cümlesiyle başlıyor. Giriş cümlesi YAZMA, "
                    "paragraf doğrudan (1) ile başlamalı.\n\n"
                )

        # Check: soru kökünde duplicate — hem numaralı hem numarasız B3 templateler için
        _stem_nums = len(_re.findall(r'\(\d+\)', _stem))
        _stem_roman = len(_re.findall(r'(?:^|\s)(I{1,3}V?|IV|V)\.\s', _stem))
        if _stem_nums >= 3 or _stem_roman >= 3:
            logger.warning(f"[CONSTRAINT] {prefix}B3: soru kokunde {_stem_nums} arap + {_stem_roman} roma numarali cumle — DUPLICATE!")
            feedback += (
                "SORU KOKU DUPLICATE IHLALI (DETERMINISTIK):\n"
                "Soru kökünde paragraftaki cümleler numaralanıp tekrar yazılmış. "
                "Soru kökünde SADECE tek bir soru cümlesi olmalı.\n\n"
            )

        # Check: soru kökü paragrafla çok benzer mi (duplicate metin kontrolü)
        # Sadece numarali paragraflar icin uygula (B3 siralama). Paragraf tamamlama vb.
        # kisa stem'li templatelerde false positive uretmesin.
        if _is_numbered and len(_stem) > 100 and len(_para) > 100:
            _stem_clean = _re.sub(r'<[^>]+>', '', _stem).strip()[:80]
            _para_clean = _re.sub(r'<[^>]+>', '', _para).strip()[:80]
            if _stem_clean and _para_clean:
                _common = sum(1 for a, b in zip(_stem_clean, _para_clean) if a == b)
                _similarity = _common / max(len(_stem_clean), 1)
                if _similarity > 0.6:
                    logger.warning(f"[CONSTRAINT] {prefix}Soru koku paragrafla %{int(_similarity*100)} benzer — DUPLICATE!")
                    feedback += (
                        "METIN DUPLICATE IHLALI (DETERMINISTIK):\n"
                        "Soru kökündeki metin paragrafla çok benzer. Paragraftaki metin "
                        "soru kökünde tekrarlanmamalı.\n\n"
                    )

        if _is_numbered:
            # Check: "(X) rakamı ile numaralandırılmış" kötü ifade
            _all_text = _para + " " + _stem + " " + " ".join(
                o.get("text", "") if isinstance(o, dict) else str(o) for o in (result.options or [])
            )
            if _re.search(r'\(\d+\)\s*rakamı\s*ile\s*numaralandırılmış', _all_text, _re.IGNORECASE):
                logger.warning(f"[CONSTRAINT] {prefix}Siralama: kotu ifade '(X) rakami ile numaralandirilmis'")
                feedback += (
                    "SIRALAMA IFADE IHLALI (DETERMINISTIK):\n"
                    "'(3) rakamı ile numaralandırılmış cümle' gibi ifadeler yasak. "
                    "Bunun yerine '3 numaralı cümle' veya '3. cümle' kullanılmalı.\n\n"
                )

        # Option length balance check (correct vs distractors)
        opt_style = effective_opt_wc_cfg.style if effective_opt_wc_cfg else ""
        balance_report = evaluate_option_length_balance(
            result.options, result.correct_answer, style=opt_style
        )
        if balance_report.passed:
            logger.info(
                f"[CONSTRAINT] {prefix}Secenek uzunluk dengesi OK "
                f"(oran: {balance_report.ratio:.2f})"
            )
        else:
            logger.warning(
                f"[CONSTRAINT] {prefix}Secenek uzunluk DENGESIZ: "
                f"{balance_report.violations}"
            )
            feedback += balance_report.to_feedback_text() + "\n\n"

        # Sentence-insertion semantics for Bolum 6 templates
        if template_id and "paragraf_cumle_ekleme_" in template_id:
            placeholder_count = (result.paragraph or "").count("----")
            paragraph_text = (result.paragraph or "").strip()
            # Tolerate leading/trailing quote characters around the "----" placeholder
            # so a paragraph that begins/ends with "----" (quoted) is treated the same as bare ----.
            _strip_chars = '"\'“”‘’ '
            paragraph_probe = paragraph_text.strip(_strip_chars)
            if placeholder_count != 1:
                logger.warning(
                    f"[CONSTRAINT] {prefix}Cumle ekleme: beklenen 1 placeholder yerine "
                    f"{placeholder_count} bulundu"
                )
                feedback += (
                    "CUMLE EKLEME PLACEHOLDER IHLALI (DETERMINISTIK):\n"
                    'Paragrafta tam olarak 1 adet "----" bulunmali.\n\n'
                )
            elif "basina" in template_id and not paragraph_probe.startswith("----"):
                logger.warning(f"[CONSTRAINT] {prefix}Cumle ekleme basina: placeholder basta degil")
                feedback += (
                    "CUMLE EKLEME BASINA IHLALI (DETERMINISTIK):\n"
                    'Basina ekleme sorusunda paragraf "----" ile baslamali.\n\n'
                )
            elif "sonuna" in template_id and not paragraph_probe.endswith("----"):
                logger.warning(f"[CONSTRAINT] {prefix}Cumle ekleme sonuna: placeholder sonda degil")
                feedback += (
                    "CUMLE EKLEME SONUNA IHLALI (DETERMINISTIK):\n"
                    'Sonuna ekleme sorusunda paragraf "----" ile bitmeli.\n\n'
                )
            elif "ortaya" in template_id and (
                paragraph_probe.startswith("----") or paragraph_probe.endswith("----")
            ):
                logger.warning(f"[CONSTRAINT] {prefix}Cumle ekleme ortaya: placeholder kenarda")
                feedback += (
                    "CUMLE EKLEME ORTAYA IHLALI (DETERMINISTIK):\n"
                    'Ortaya ekleme sorusunda "----" ne basta ne sonda olmali.\n\n'
                )

        return feedback

    @staticmethod
    def _build_distractor_strategy_info(
        template: QuestionTemplate,
    ) -> list[dict[str, str]]:
        """Extract rich distractor strategy info from template."""
        info_list = []
        for s in template.celdirici_stratejileri:
            info: dict[str, str] = {"ad": s.ad, "aciklama": s.aciklama}
            if s.tip:
                info["tip"] = s.tip
            if s.nasil_olusturulur:
                info["nasil"] = s.nasil_olusturulur
            if s.kacinilacaklar:
                info["kacinilacaklar"] = s.kacinilacaklar
            info_list.append(info)
        return info_list

    @staticmethod
    def _build_template_semantics_hint(template_id: str) -> str:
        """Build extra validator hints for semantically sensitive templates."""
        if "paragraf_cumle_ekleme_basina_" in template_id:
            return (
                "\n   BOLUM 6 OZEL SEMANTIK (BASINA CUMLE EKLEME):\n"
                '   - Paragrafta "----" EN BASTA olmali.\n'
                "   - Dogru cevap GIRIS cumlesi gibi davranmali; ana konuyu tanitmali.\n"
                "   - Celdiriciler konuya yakin olabilir ama dogal bir baslangic kurmamali.\n"
            )
        if "paragraf_cumle_ekleme_ortaya_" in template_id:
            return (
                "\n   BOLUM 6 OZEL SEMANTIK (ORTAYA CUMLE EKLEME):\n"
                '   - Paragrafta "----" ne basta ne sonda olmali.\n'
                "   - Dogru cevap onceki ve sonraki cumle arasinda MANTIKSAL KOPRU kurmali.\n"
                "   - Celdiriciler konuya yakin olabilir ama akisi veya gecisi bozmalidir.\n"
            )
        if "paragraf_cumle_ekleme_sonuna_" in template_id:
            return (
                "\n   BOLUM 6 OZEL SEMANTIK (SONUNA CUMLE EKLEME):\n"
                '   - Paragrafta "----" EN SONDA olmali.\n'
                "   - Dogru cevap SONUC cumlesi gibi davranmali; konuyu toparlamali veya baglamali.\n"
                "   - Celdiriciler konuya yakin olabilir ama dogal bir kapanis olusturmamalidir.\n"
            )
        return ""

    async def generate(
        self,
        template_id: str,
        topic: str,
        grade: int = 5,
        subject: str = "turkce",
        on_progress: Callable[[str], None] | None = None,
        image_config_override: ImageGeneratorConfig | None = None,
        visual_context: bool = False,
        target_missing_element: str | None = None,
    ) -> QuestionGenerationResult:
        """
        Generate a question using the specified template.

        Args:
            template_id: Template identifier (e.g., "ana_fikir", "konu")
            topic: Topic string from konular/ directory
            grade: Target grade level (default: 5)
            subject: Subject code (default: "turkce")
            on_progress: Optional callback for progress updates
            image_config_override: Optional per-call image config override.
                If provided, used instead of self.image_config (parallel-safe).
            visual_context: If True, generate a question-aware visual that
                replaces the paragraph. The question is solvable from the
                visual alone.

        Returns:
            QuestionGenerationResult with all generated content
        """

        def log(msg: str) -> None:
            logger.info(msg)
            if on_progress:
                on_progress(msg)

        result = QuestionGenerationResult(
            topic=topic,
            question_type=template_id,
            success=False,
        )

        try:
            # Step 1: Load template
            log(f"[1/5] Sablon yukleniyor: {template_id}")
            template = self.template_loader.load(template_id)

            # Pass rendering hints from template format config
            result.options_layout = template.format.options.layout
            # Only use html_template if it matches the option count;
            # default html_template has A-D, so skip it for non-4-option templates
            html_tmpl = template.format.html_template
            opt_count = template.format.options.count
            if html_tmpl and opt_count != 4:
                # 3-option: default template has {option_d} → KeyError
                # 5-option: default template missing {option_e} → incomplete
                result.html_body_template = None  # Let renderer build dynamically
            else:
                result.html_body_template = html_tmpl
            log(f"      Sablon: {template.meta.ad}")

            # Auto-build deterministic constraints from template
            template_para_cfg, template_opt_wc_cfg = build_constraints_from_template(template)
            # User-provided overrides take priority over template-derived ones
            effective_para_cfg = self.paragraph_constraints or template_para_cfg
            effective_opt_wc_cfg = template_opt_wc_cfg

            if effective_para_cfg and effective_para_cfg.enabled:
                logger.info(
                    f"[CONSTRAINT] Paragraf kisitlamalari: "
                    f"{effective_para_cfg.word_min}-{effective_para_cfg.word_max} kelime, "
                    f"{effective_para_cfg.sentence_min}-{effective_para_cfg.sentence_max} cumle"
                )
            if effective_opt_wc_cfg and effective_opt_wc_cfg.enabled:
                logger.info(
                    f"[CONSTRAINT] Secenek kisitlamalari: "
                    f"{effective_opt_wc_cfg.word_count_min}-{effective_opt_wc_cfg.word_count_max} kelime, "
                    f"stil={effective_opt_wc_cfg.style}"
                )

            # Resolve models for this template
            para_model = self._resolve_model(template, "paragraph_writer")
            question_model = self._resolve_model(template, "question_crafter")
            validator_model = self._resolve_model(template, "validator")

            log(f"      Modeller: para={para_model}, soru={question_model}, validator={validator_model}")

            # Step 2: Get generator for format
            generator = get_generator(template.format)
            log(f"[2/5] Format: {template.format.type}")

            # Step 3: Generate question
            log(f"[3/5] Soru olusturuluyor: {topic[:50]}...")

            stem_metadata = template.reserve_stem(template_id)
            result.template_id = template_id
            result.used_stem_index = int(stem_metadata["selected_stem_index"])
            result.selected_stem_index = int(stem_metadata["selected_stem_index"])
            result.selected_stem_text = str(stem_metadata["selected_stem_text"])
            result.stem_source = str(stem_metadata["stem_source"])
            result.stem_reservation_id = str(stem_metadata["stem_reservation_id"])
            result.stem_reservation_status = str(stem_metadata["stem_reservation_status"])

            output = await generator.generate(
                template=template,
                topic=topic,
                client=self.client,
                grade=grade,
                subject=subject,
                cache_name=self._paragraph_cache,
                paragraph_model=para_model,
                question_model=question_model,
                stem_text=result.selected_stem_text,
                stem_metadata=stem_metadata,
                target_missing_element=target_missing_element,
            )

            # Populate initial result
            result.paragraph = output.paragraph
            result.key_concepts = output.key_concepts
            result.difficulty_level = output.difficulty_level
            result.curriculum_source = output.curriculum_source
            result.curriculum_reasoning = output.curriculum_reasoning
            result.question = output.question
            result.key_word = output.key_word
            result.options = output.options
            result.correct_answer = output.correct_answer
            result.option_reasoning = output.option_reasoning
            result.answer_explanation = output.answer_explanation
            result.skill_tag = output.skill_tag
            result.shared_visual_format = output.shared_visual_format
            result.selected_stem_index = output.selected_stem_index
            result.selected_stem_text = output.selected_stem_text or result.selected_stem_text
            result.stem_source = output.stem_source or result.stem_source
            result.stem_reservation_id = output.stem_reservation_id or result.stem_reservation_id
            result.stem_reservation_status = (
                output.stem_reservation_status or result.stem_reservation_status
            )
            result.used_stem_index = output.selected_stem_index

            # Populate beceri context_type from template (only for BeceriConfig, not plain dict)
            if isinstance(getattr(template, "beceri", None), BeceriConfig):
                result.context_type = template.beceri.context_type

            # Detailed logging of generated content
            options_log = "\n".join(
                f"  {l}) {output.options.get(l, '')}" for l in sorted(output.options.keys())
            )
            logger.debug(
                f"[GENERATED CONTENT]\n"
                f"{'='*60}\n"
                f"PARAGRAPH:\n{output.paragraph}\n\n"
                f"KEY CONCEPTS: {output.key_concepts}\n"
                f"DIFFICULTY: {output.difficulty_level}\n"
                f"CURRICULUM SOURCE: {output.curriculum_source}\n\n"
                f"QUESTION: {output.question}\n"
                f"KEY WORD: {output.key_word}\n"
                f"OPTIONS:\n{options_log}\n"
                f"CORRECT: {output.correct_answer}\n"
                f"{'='*60}"
            )

            # Step 4: Apply formatting normalization
            log("[4/5] Formatlama uygulanıyor...")
            self._apply_formatting(result, log)

            # Post-process labeled multiline options (hikaye unsurlari) — comma → <br>
            if template.format.options.style == "element_set_labeled_multiline" and result.options:
                result.options = self._normalize_multiline_labeled_options(result.options)
            # Post-process element_label options — extract bare unsur label, UPPERCASE
            if template.format.options.style == "element_label" and result.options:
                result.options = self._normalize_element_label_options(result.options)

            # Check deterministic constraints from template
            constraint_feedback_text = self._evaluate_constraints(
                result, effective_para_cfg, effective_opt_wc_cfg, template_id=template_id
            )

            # Shuffle options for balanced answer distribution (unless preserve_order is set)
            if not template.format.options.preserve_order:
                result.options, result.correct_answer, result.option_reasoning = shuffle_options(
                    result.options, result.correct_answer, result.option_reasoning,
                    answer_history=self._answer_history,
                )
                log(f"      Siklar karistirildi, dogru cevap: {result.correct_answer}")
            else:
                log(f"      Siklar korundu (preserve_order=true), dogru cevap: {result.correct_answer}")

            # Step 5: Batch validation
            log("[5/5] Kalite kontrolu (batch validation)...")

            batch_validator = BatchValidator(
                client=self.client,
                model=validator_model,
                cache_name=self._validator_cache,
            )

            distractor_strategy_info = self._build_distractor_strategy_info(template)
            template_semantics_hint = self._build_template_semantics_hint(template_id)

            validation_result = await batch_validator.validate(
                paragraph=result.paragraph,
                question=result.question,
                options=result.options,
                correct_answer=result.correct_answer,
                grade=grade,
                required_checks=self.required_checks,
                distractor_strategies=distractor_strategy_info,
                option_style=template.format.options.style,
                visual_requirement=getattr(template, "visual_requirement", None),
                template_semantics=template_semantics_hint,
            )

            # Convert to ValidationOutput for compatibility
            result.validation = _batch_to_validation_output(validation_result)

            # Determine overall pass: both LLM validation AND deterministic constraints must pass
            all_passed = validation_result.passed and not constraint_feedback_text

            if all_passed:
                log(f"      ✓ Tüm kontroller geçti (skor: {validation_result.overall_score:.1f})")
                result.success = True
                # Record answer for distribution tracking
                self._answer_history.append(result.correct_answer)
                # Beceri etiketi from template (convert BeceriConfig to dict for serialization)
                if isinstance(template.beceri, BeceriConfig):
                    result.beceri_etiketi = template.beceri.model_dump()
                else:
                    result.beceri_etiketi = template.beceri
                # Çeldirici hata kategorileri from strategy mapping
                if result.option_reasoning:
                    result.celdirici_hata_kategorileri = map_option_error_categories(
                        result.option_reasoning, result.correct_answer
                    )
            else:
                # Determine affected components for smart routing
                affected = validation_result.get_affected_components() if not validation_result.passed else set()
                # Also route based on deterministic constraint failures
                if constraint_feedback_text:
                    if "PARAGRAF" in constraint_feedback_text and "paragraph" not in affected:
                        affected.add("paragraph")
                    if "SECENEK" in constraint_feedback_text and "options" not in affected:
                        affected.add("options")

                if not validation_result.passed:
                    failed_names = [c.check_name for c in validation_result.failed_checks]
                    log(f"      ✗ Başarısız kontroller: {', '.join(failed_names)}")
                    log(f"      Etkilenen bileşenler: {', '.join(affected) if affected else 'bilinmiyor'}")
                else:
                    log(f"      ✓ LLM kontrolleri geçti ama deterministik kisitlama ihlali var")

                # Detailed logging of all validation results
                logger.debug(
                    f"[VALIDATION DETAILS]\n"
                    f"{'='*60}\n"
                    f"Overall: {'PASSED' if validation_result.passed else 'FAILED'} "
                    f"(score: {validation_result.overall_score:.1f})\n"
                    f"{'-'*60}"
                )
                for check_name, check in validation_result.checks.items():
                    logger.debug(
                        f"\n[{check.check_name}] {check.status} (score={check.score})\n"
                        f"  Feedback: {check.feedback}\n"
                        f"  Issues: {check.issues}\n"
                        f"  Suggestions: {check.suggestions}\n"
                        f"  Affected: {check.affected_components}"
                    )
                logger.debug(f"{'='*60}")

                # Build combined feedback for retry (deterministic first, then LLM)
                validation_feedback_text = enrich_validation_feedback(
                    validation_result=validation_result,
                    options=result.options,
                    correct_answer=result.correct_answer,
                    question=result.question,
                    grade=grade,
                    paragraph=result.paragraph,
                )
                combined_feedback = constraint_feedback_text + validation_feedback_text

                logger.debug(
                    f"[ENRICHED FEEDBACK]\n{'='*60}\n"
                    f"Constraint feedback:\n{constraint_feedback_text or '(none)'}\n"
                    f"{'-'*60}\n"
                    f"Enriched validation feedback:\n{validation_feedback_text or '(none)'}\n"
                    f"{'-'*60}\n"
                    f"Combined feedback:\n{combined_feedback}\n"
                    f"{'='*60}"
                )

                # Retry loop with smart routing
                for iteration in range(1, self.max_fix_iterations + 1):
                    result.fix_iterations = iteration
                    log(f"      Düzeltme denemesi {iteration}/{self.max_fix_iterations}...")

                    # Determine what to regenerate based on affected components
                    regenerate_paragraph = "paragraph" in affected and template.format.paragraph.required
                    regenerate_question = "question_stem" in affected or "options" in affected

                    logger.debug(
                        f"[RETRY {iteration}]\n{'='*60}\n"
                        f"Affected components: {affected}\n"
                        f"Regenerate paragraph: {regenerate_paragraph}\n"
                        f"Regenerate question: {regenerate_question}\n"
                        f"Combined feedback:\n{combined_feedback}\n"
                        f"{'='*60}"
                    )

                    if regenerate_paragraph:
                        log("        → Paragraf yeniden oluşturuluyor...")
                        paragraph_result = await generator.generate_paragraph(
                            template=template,
                            topic=topic,
                            subject=subject,
                            grade=grade,
                            client=self.client,
                            cache_name=self._paragraph_cache,
                            model=para_model,
                            target_missing_element=target_missing_element,
                        )
                        result.paragraph = paragraph_result.paragraph
                        result.key_concepts = paragraph_result.key_concepts
                        result.curriculum_source = paragraph_result.curriculum_source
                        result.curriculum_reasoning = paragraph_result.reasoning
                        # Paragraph changed → must also regenerate question
                        regenerate_question = True

                    if regenerate_question:
                        log("        → Soru yeniden oluşturuluyor...")
                        output = await generator.generate_question(
                            template=template,
                            topic=topic,
                            paragraph=result.paragraph,
                            client=self.client,
                            grade=grade,
                            subject=subject,
                            cache_name=self._paragraph_cache,
                            question_model=question_model,
                            validation_feedback=combined_feedback,
                            stem_text=result.selected_stem_text,
                            stem_metadata=stem_metadata,
                            target_missing_element=target_missing_element,
                        )
                        result.question = output.question
                        result.key_word = output.key_word
                        result.options = output.options
                        result.correct_answer = output.correct_answer
                        result.option_reasoning = output.option_reasoning
                        result.shared_visual_format = output.shared_visual_format
                        result.selected_stem_index = output.selected_stem_index
                        result.selected_stem_text = (
                            output.selected_stem_text or result.selected_stem_text
                        )
                        result.stem_source = output.stem_source or result.stem_source
                        result.stem_reservation_id = (
                            output.stem_reservation_id or result.stem_reservation_id
                        )
                        result.stem_reservation_status = (
                            output.stem_reservation_status or result.stem_reservation_status
                        )
                        result.used_stem_index = output.selected_stem_index

                    # Re-apply formatting
                    self._apply_formatting(result, log)

                    # Post-process labeled multiline options (hikaye unsurlari) — comma → <br>
                    if template.format.options.style == "element_set_labeled_multiline" and result.options:
                        result.options = self._normalize_multiline_labeled_options(result.options)
                    # Post-process element_label options — extract bare unsur label, UPPERCASE
                    if template.format.options.style == "element_label" and result.options:
                        result.options = self._normalize_element_label_options(result.options)

                    # Re-run deterministic constraint checks after retry
                    constraint_feedback_text = self._evaluate_constraints(
                        result, effective_para_cfg, effective_opt_wc_cfg,
                        label=str(iteration), template_id=template_id,
                    )

                    # Re-shuffle options (unless preserve_order is set)
                    if not template.format.options.preserve_order:
                        result.options, result.correct_answer, result.option_reasoning = shuffle_options(
                            result.options, result.correct_answer, result.option_reasoning
                        )

                    # Re-validate
                    validation_result = await batch_validator.validate(
                        paragraph=result.paragraph,
                        question=result.question,
                        options=result.options,
                        correct_answer=result.correct_answer,
                        grade=grade,
                        required_checks=self.required_checks,
                        distractor_strategies=distractor_strategy_info,
                        option_style=template.format.options.style,
                        visual_requirement=getattr(template, "visual_requirement", None),
                        template_semantics=template_semantics_hint,
                    )
                    result.validation = _batch_to_validation_output(validation_result)

                    if validation_result.passed and not constraint_feedback_text:
                        log(f"      ✓ Düzeltme başarılı (deneme {iteration})")
                        result.success = True
                        self._answer_history.append(result.correct_answer)
                        # Beceri etiketi from template
                        if isinstance(template.beceri, BeceriConfig):
                            result.beceri_etiketi = template.beceri.model_dump()
                        else:
                            result.beceri_etiketi = template.beceri
                        # Çeldirici hata kategorileri from strategy mapping
                        if result.option_reasoning:
                            result.celdirici_hata_kategorileri = map_option_error_categories(
                                result.option_reasoning, result.correct_answer
                            )
                        break
                    else:
                        affected = validation_result.get_affected_components()
                        failed_names = [c.check_name for c in validation_result.failed_checks]
                        if failed_names:
                            log(f"        Hala başarısız: {', '.join(failed_names)}")
                        if constraint_feedback_text:
                            log(f"        Deterministik kisitlama ihlali devam ediyor")
                        # Update combined feedback for next retry
                        validation_feedback_text = enrich_validation_feedback(
                            validation_result=validation_result,
                            options=result.options,
                            correct_answer=result.correct_answer,
                            question=result.question,
                            grade=grade,
                            paragraph=result.paragraph,
                        )
                        combined_feedback = constraint_feedback_text + validation_feedback_text

                if not result.success:
                    log(f"      ✗ {self.max_fix_iterations} deneme sonrası başarısız")
                    result.success = False

            # Generate option images for gorsel_siklar templates
            if result.success and template.format.options.style == "image_description":
                try:
                    await self._generate_option_images(result, template, log, image_config=image_config_override)
                except Exception as e:
                    logger.warning(f"[OPTION_IMAGES] Gorsel uretim hatasi (non-blocking): {e}")
                    log(f"[IMAGE] Secenek gorsel uretim hatasi: {e}")
            # Answer-critical visual (Bolum 7 — template explicitly marks visual_requirement)
            elif result.success and getattr(template, "visual_requirement", None) == "answer_critical":
                effective_image = image_config_override if image_config_override is not None else self.image_config
                ok = await self._try_generate_answer_critical_visual(
                    result, template, subject, log, image_config=effective_image
                )
                if not ok:
                    log("      ✗ Answer-critical gorsel uretilemedi — soru gecersiz")
                    result.success = False
                elif ok:
                    # If template has hide_paragraph_after_visual flag, the visual IS the content —
                    # hide paragraph from output (it was only used internally to generate the visual)
                    if getattr(template, "hide_paragraph_after_visual", False):
                        log("      [IMAGE-CRITIC] Paragraf gizleniyor (gorsel ana kaynak)")
                        result.paragraph = ""
            # Generate poster/infographic if template has image_context (e.g., beceri_afis, beceri_infografik)
            elif result.success and isinstance(getattr(template, "beceri", None), BeceriConfig) and template.beceri.image_context:
                if template.beceri.context_type == "INFOGRAFIK":
                    await self._try_generate_infographic(result, topic, log, image_config=image_config_override)
                else:
                    await self._try_generate_poster(result, topic, log, image_config=image_config_override)
            # Question-aware visual generation (visual_context flag from config)
            elif result.success and visual_context:
                await self._try_generate_question_visual(
                    result, template_id, topic, log, image_config=image_config_override
                )
            else:
                # Generate diagram if configured and question generation succeeded
                effective_image = image_config_override if image_config_override is not None else self.image_config
                if result.success and effective_image and effective_image.enabled:
                    await self._try_generate_image(result, subject, log, image_config=effective_image)

            # Ethics check + publication status (karar ağacı)
            ethics_passed = True
            if result.question and result.options:
                try:
                    ethics_result = await batch_validator.check_ethics(
                        paragraph=result.paragraph,
                        question=result.question,
                        options=result.options,
                        subject=subject,
                        grade=grade,
                    )
                    ethics_check = ethics_result.get("ethics_check")
                    if ethics_check and ethics_check.status == "FAIL":
                        ethics_passed = False
                        logger.warning(
                            f"[ETHICS] FAIL: {ethics_check.feedback}"
                        )
                        log(f"      ⚠ Etik kontrol FAIL: {ethics_check.feedback}")
                    else:
                        logger.info("[ETHICS] OK")
                except Exception as e:
                    logger.warning(f"[ETHICS] Check error (non-blocking): {e}")

            result.yayinlanma_durumu = compute_publication_status(
                validation_result=validation_result,
                constraint_feedback=constraint_feedback_text,
                ethics_passed=ethics_passed,
            )
            log(f"      Yayinlanma durumu: {result.yayinlanma_durumu}")

            return result

        except Exception as e:
            result.error = str(e)
            log(f"[ERROR] Hata: {e}")
            logger.exception("Workflow error")
            return result



    async def generate_context_group(
        self,
        template_id: str,
        topic: str,
        grade: int = 5,
        subject: str = "turkce",
        on_progress: Callable[[str], None] | None = None,
    ) -> ContextQuestionGroupResult:
        """Generate a context-based question group (1 context → N questions).

        Args:
            template_id: Context template identifier
            topic: Topic string
            grade: Target grade level
            subject: Subject code
            on_progress: Optional progress callback

        Returns:
            ContextQuestionGroupResult with context + sub-questions
        """

        def log(msg: str) -> None:
            logger.info(msg)
            if on_progress:
                on_progress(msg)

        result = ContextQuestionGroupResult(
            topic=topic,
            context_type=template_id,
            success=False,
        )

        try:
            # Step 1: Load template and verify it's a context template
            log(f"[1/6] Sablon yukleniyor: {template_id}")
            template = self.template_loader.load(template_id)

            if not template.is_context_template:
                result.error = f"Template '{template_id}' is not a context template"
                log(f"[ERROR] {result.error}")
                return result

            ctx_config = template.context
            log(f"      Baglam tipi: {ctx_config.type}, Soru sayisi: {ctx_config.question_count}")

            # Build context constraints
            ctx_constraints = build_context_constraints_from_template(template)

            # Resolve models
            para_model = self._resolve_model(template, "paragraph_writer")
            question_model = self._resolve_model(template, "question_crafter")
            validator_model = self._resolve_model(template, "validator")
            log(f"      Modeller: ctx={para_model}, soru={question_model}, val={validator_model}")

            # Get generator
            generator = get_generator(template.format)

            # Step 2: Generate context text (with retry for 503)
            log(f"[2/6] Baglam metni olusturuluyor...")
            context_result = None
            for ctx_attempt in range(3):
                try:
                    context_result = await generator.generate_context(
                        template=template,
                        topic=topic,
                        subject=subject,
                        grade=grade,
                        client=self.client,
                        cache_name=self._paragraph_cache,
                        model=para_model,
                    )
                    break
                except Exception as e:
                    logger.warning(f"[CONTEXT_GEN] Attempt {ctx_attempt} error: {e}")
                    if ctx_attempt >= 2:
                        raise
                    if "503" in str(e) or "429" in str(e) or "UNAVAILABLE" in str(e):
                        wait_secs = 15 * (ctx_attempt + 1)
                        log(f"      API hatasi, {wait_secs}s bekleniyor...")
                        await asyncio.sleep(wait_secs)
                    else:
                        raise

            result.context_text = context_result.paragraph
            result.key_concepts = context_result.key_concepts
            result.difficulty_level = context_result.difficulty_level
            result.curriculum_source = context_result.curriculum_source
            result.curriculum_reasoning = context_result.reasoning

            # Check context constraints
            if ctx_constraints:
                ctx_ok, ctx_feedback = evaluate_context_constraints(
                    result.context_text, ctx_constraints
                )
                if ctx_ok:
                    logger.info(f"[CONSTRAINT] Baglam metni OK")
                else:
                    logger.warning(f"[CONSTRAINT] Baglam metni ihlal: {ctx_feedback}")

            log(f"      Baglam metni: {len(result.context_text.split())} kelime")

            # NOTE: Context image generation deferred to AFTER all sub-questions pass
            # (cost optimization — don't produce an image that will be thrown away if
            # any slot fails validation).

            # Step 3: Build header text
            if template.header_template:
                result.header_text = template.header_template.replace(
                    "{n}", str(ctx_config.question_count)
                )
            elif ctx_config.question_count == 1:
                # 1Q bağlam sorularında header olmaz
                result.header_text = ""
            else:
                result.header_text = (
                    f"(1-{ctx_config.question_count}). soruları aşağıdaki "
                    f"metne göre cevaplayınız."
                )
            log(f"[3/6] Baslik: {result.header_text}")

            # Step 4: Generate sub-questions
            log(f"[4/6] Alt sorular olusturuluyor ({ctx_config.question_count} adet)...")

            batch_validator = BatchValidator(
                client=self.client,
                model=validator_model,
                cache_name=self._validator_cache,
            )
            distractor_strategy_info = self._build_distractor_strategy_info(template)
            previous_questions: list[dict] = []

            # Build option word count config from slot
            for slot in ctx_config.questions:
                slot_result = ContextSubQuestionResult(
                    slot=slot.slot,
                    question_type=slot.type,
                    success=False,
                )

                log(f"      Soru {slot.slot}/{ctx_config.question_count}: {slot.type}")

                # Build slot-specific option constraints
                slot_opt_cfg = OptionWordCountConfig(
                    enabled=True,
                    style=slot.options_style,
                    word_count_min=slot.word_count_min,
                    word_count_max=slot.word_count_max,
                )

                # Retry loop for this sub-question
                combined_feedback = None
                for attempt in range(self.max_fix_iterations + 1):
                    try:
                        vf = None if attempt == 0 else combined_feedback
                        output = await generator.generate_question_from_context(
                            template=template,
                            slot=slot,
                            topic=topic,
                            context_text=result.context_text,
                            client=self.client,
                            grade=grade,
                            subject=subject,
                            cache_name=self._paragraph_cache,
                            question_model=question_model,
                            previous_questions=previous_questions,
                            validation_feedback=vf,
                        )

                        # Post-process: if LLM copied paragraph into question, replace with stem
                        _q = (output.question or "").strip()
                        _q_word_count = len(_q.split())
                        _slot_stems = getattr(slot, "soru_kokleri", None) or []
                        if _slot_stems and _q_word_count > 30:
                            # LLM probably copied paragraph — force stem from template
                            import re as _re
                            # Try to extract <b>...</b> from the end (most likely the real stem)
                            _bold_match = _re.findall(r'<b>.*?</b>', _q, flags=_re.DOTALL)
                            if _bold_match:
                                _q = _bold_match[-1].strip()
                            else:
                                _q = _slot_stems[0]
                            log(f"      [STEM FIX] question field paragraph tekrari icerdi — stem ile degistirildi")
                            output.question = _q

                        slot_result.question = output.question
                        slot_result.key_word = output.key_word
                        slot_result.options = output.options
                        slot_result.correct_answer = output.correct_answer
                        slot_result.option_reasoning = output.option_reasoning

                        # Apply formatting
                        fmt_report = evaluate_formatting(
                            paragraph="",
                            question=output.question,
                            options=output.options,
                            cfg=self.formatting_constraints,
                        )
                        slot_result.question = fmt_report.normalized_question
                        slot_result.options = fmt_report.normalized_options

                        # Check option word count constraints
                        constraint_feedback = ""
                        opt_wc_report = evaluate_option_word_count(
                            slot_result.options, slot_opt_cfg
                        )
                        if not opt_wc_report.passed:
                            constraint_feedback += (
                                "SECENEK KELIME SAYISI IHLALI (DETERMINISTIK):\n"
                                + opt_wc_report.to_feedback_text(slot_opt_cfg)
                                + "\n\n"
                            )

                        # Check banned options (hepsi/hiçbiri)
                        banned_ok, banned_fb = check_banned_options(slot_result.options)
                        if not banned_ok:
                            constraint_feedback += banned_fb + "\n"

                        # Mutlak ifade kontrolü
                        abs_ok, abs_fb = check_absolute_expressions(
                            slot_result.question, slot_result.options
                        )
                        if not abs_ok:
                            constraint_feedback += abs_fb + "\n"

                        # Köşeli parantez kalıntısı kontrolü
                        bracket_ok, bracket_fb = check_bracket_remnants(
                            slot_result.question, slot_result.options
                        )
                        if not bracket_ok:
                            constraint_feedback += bracket_fb + "\n"

                        # Birebir kopyalama kontrolü (context text + slot result)
                        # Sıralama template'lerinde tamamlama/akışı bozan sorularının
                        # seçenekleri doğal olarak metindeki cümlelere benzer — istisna
                        _skip_verbatim = "siralama" in (template_id or "").lower()
                        if not _skip_verbatim:
                            _ctx_text = result.context_text or ""
                            _c_letter = slot_result.correct_answer or ""
                            _c_text = slot_result.options.get(_c_letter, "")
                            verbatim_ok, verbatim_fb = check_verbatim_copy(
                                _ctx_text, _c_text, _c_letter
                            )
                            if not verbatim_ok:
                                constraint_feedback += verbatim_fb + "\n"

                        # Shuffle options
                        if slot.options_style != "roman_numeral_combination":
                            slot_result.options, slot_result.correct_answer, slot_result.option_reasoning = shuffle_options(
                                slot_result.options,
                                slot_result.correct_answer,
                                slot_result.option_reasoning,
                                answer_history=self._answer_history,
                            )

                        # Validate + context dependency in parallel
                        validation_result, ctx_dep_result = await asyncio.gather(
                            batch_validator.validate(
                                paragraph=result.context_text,
                                question=slot_result.question,
                                options=slot_result.options,
                                correct_answer=slot_result.correct_answer,
                                grade=grade,
                                required_checks=self.required_checks,
                                distractor_strategies=distractor_strategy_info,
                                is_context_template=True,
                            ),
                            batch_validator.check_context_dependency(
                                context_text=result.context_text,
                                question=slot_result.question,
                                options=slot_result.options,
                                correct_answer=slot_result.correct_answer,
                            ),
                        )
                        slot_result.validation = _batch_to_validation_output(validation_result)

                        if validation_result.passed and not constraint_feedback:
                            # Check context dependency (already computed in parallel)
                            ctx_dep_check = ctx_dep_result.get("context_dependency")
                            if ctx_dep_check and ctx_dep_check.status == "FAIL":
                                constraint_feedback += (
                                    "BAGLAM BAGIMLILIGI IHLALI:\n"
                                    f"- {ctx_dep_check.feedback}\n"
                                    "- Soru SADECE baglam metnindeki veriye "
                                    "dayanarak cevaplanabilir olmali.\n\n"
                                )
                                logger.warning(
                                    f"[CONSTRAINT] Soru {slot.slot} baglam "
                                    f"bagimliligi FAIL: {ctx_dep_check.feedback}"
                                )
                            else:
                                logger.info(
                                    f"[CONSTRAINT] Soru {slot.slot} baglam bagimliligi OK"
                                )

                        if validation_result.passed and not constraint_feedback:
                            slot_result.success = True
                            slot_result.fix_iterations = attempt
                            self._answer_history.append(slot_result.correct_answer)
                            # Beceri etiketi from slot
                            slot_result.beceri_etiketi = slot.beceri
                            # Çeldirici hata kategorileri
                            if slot_result.option_reasoning:
                                slot_result.celdirici_hata_kategorileri = map_option_error_categories(
                                    slot_result.option_reasoning, slot_result.correct_answer
                                )
                            log(f"        ✓ Soru {slot.slot} basarili (deneme {attempt})")
                            break
                        else:
                            validation_feedback_text = enrich_validation_feedback(
                                validation_result=validation_result,
                                options=slot_result.options,
                                correct_answer=slot_result.correct_answer,
                                question=slot_result.question,
                                grade=grade,
                                paragraph=result.context_text,
                            )
                            combined_feedback = constraint_feedback + validation_feedback_text
                            slot_result.fix_iterations = attempt
                            if attempt < self.max_fix_iterations:
                                log(f"        Deneme {attempt} basarisiz, yeniden deneniyor...")

                    except Exception as e:
                        slot_result.error = str(e)
                        logger.warning(f"[CONTEXT_Q] Slot {slot.slot} attempt {attempt} error: {e}")
                        if attempt >= self.max_fix_iterations:
                            break
                        # Backoff for API errors (503, 429, etc.)
                        if "503" in str(e) or "429" in str(e) or "UNAVAILABLE" in str(e):
                            wait_secs = 10 * (attempt + 1)
                            log(f"        API hatasi, {wait_secs}s bekleniyor...")
                            await asyncio.sleep(wait_secs)

                if not slot_result.success and not slot_result.error:
                    slot_result.error = f"Validation failed after {self.max_fix_iterations} retries"

                # Track previous questions for overlap prevention
                if slot_result.success:
                    previous_questions.append({
                        "question": slot_result.question,
                        "correct_answer": slot_result.correct_answer,
                        "correct_text": slot_result.options.get(slot_result.correct_answer, ""),
                    })

                # Generate option images if slot uses image_description style (gorsel siklar)
                if slot_result.success and slot.options_style == "image_description":
                    try:
                        from .tools.image_tools import generate_option_images_grid
                        img_style = slot.image_style or getattr(template.format.options, "image_style", None) or "table"
                        shared_fmt = getattr(slot_result, "shared_visual_format", "") or ""
                        _img_cfg = self.image_config
                        if _img_cfg and _img_cfg.enabled:
                            log(f"      [IMAGE] Slot {slot.slot} secenek gorselleri (stil: {img_style})...")
                            grid_results = await generate_option_images_grid(
                                options=slot_result.options,
                                image_style=img_style,
                                cfg=_img_cfg,
                                shared_visual_format=shared_fmt,
                            )
                            option_images: dict[str, str] = {}
                            for lbl, imgr in grid_results.items():
                                if imgr.success and imgr.png_base64:
                                    option_images[lbl] = imgr.png_base64
                            if option_images:
                                slot_result.option_images = option_images
                                log(f"      [IMAGE] Slot {slot.slot}: {len(option_images)} secenek gorseli olusturuldu")
                    except Exception as _e:
                        logger.warning(f"[OPTION_IMAGES] Slot {slot.slot} gorsel hatasi: {_e}")

                result.questions.append(slot_result)

                # Cost optimization: early-abort if this slot failed — the group will not
                # be saved anyway, so there's no reason to spend tokens on remaining slots
                # or on image generation.
                if not slot_result.success:
                    log(
                        f"      ✗ Slot {slot.slot} basarisiz — kalan slotlar ATLANIYOR "
                        "(maliyet tasarrufu, grup yine de kaydedilmeyecek)"
                    )
                    break

            # Step 5: Cross-validate group (with retry)
            log(f"[5/6] Capraz dogrulama...")
            max_cross_retries = 2

            for cross_attempt in range(max_cross_retries + 1):
                # 5a: Deterministic cross-validation
                result.cross_validation = self._cross_validate_group(result.questions)

                # 5b: LLM-based semantic cross-validation
                successful_qs = [q for q in result.questions if q.success]
                llm_cross_failed = False
                cross_feedback_parts: list[str] = []

                # Sıralama template'lerinde cross-validation atla — sıralama+tamamlama+akışı bozan
                # doğası gereği ipucu zinciri oluşturur (sıralama bilinince diğerleri kolaylaşır)
                _skip_cross = "siralama" in (template_id or "").lower()

                if len(successful_qs) >= 2 and not _skip_cross:
                    llm_cross_data = [
                        {
                            "question": q.question,
                            "options": q.options,
                            "correct_answer": q.correct_answer,
                        }
                        for q in successful_qs
                    ]
                    try:
                        llm_cross_results = await batch_validator.cross_validate_group(
                            context_text=result.context_text,
                            questions=llm_cross_data,
                        )
                        for check_name, check in llm_cross_results.items():
                            if check.status == "FAIL":
                                result.cross_validation.issues.append(
                                    f"[LLM] {check.check_name}: {check.feedback}"
                                )
                                result.cross_validation.passed = False
                                llm_cross_failed = True
                                cross_feedback_parts.append(
                                    f"- {check.check_name}: {check.feedback}"
                                )
                                for issue in check.issues:
                                    cross_feedback_parts.append(f"  * {issue}")
                    except Exception as e:
                        logger.warning(f"[CROSS_VALIDATE] LLM cross-validation error: {e}")

                if result.cross_validation.passed:
                    log(f"      ✓ Capraz dogrulama gecti")
                    break

                if not llm_cross_failed or cross_attempt >= max_cross_retries:
                    # Only deterministic issues or max retries reached
                    issues_str = "; ".join(result.cross_validation.issues[:3])
                    log(f"      ⚠ Capraz dogrulama uyarilari: {issues_str}")
                    break

                # --- Retry: regenerate last question with cross-validation feedback ---
                issues_str = "; ".join(result.cross_validation.issues[:3])
                log(
                    f"      ✗ Capraz dogrulama FAIL (deneme {cross_attempt}): "
                    f"{issues_str}"
                )
                log(f"      → Son soru yeniden uretiliyor...")

                last_idx = len(result.questions) - 1
                last_slot = ctx_config.questions[last_idx]
                last_q = result.questions[last_idx]

                # Build cross-validation feedback
                cross_feedback = (
                    "CAPRAZ DOGRULAMA IHLALI:\n"
                    + "\n".join(cross_feedback_parts)
                    + "\n- Onceki sorularla CAKISMAYAN, FARKLI bir aci/konu kullan.\n"
                    + "- Farkli bir tablo satiri/verisi hakkinda sor.\n"
                    + "- Onceki sorunun cevabina ipucu vermeyecek secenekler yaz.\n\n"
                )

                # Remove last question's data from tracking
                if previous_questions:
                    previous_questions.pop()
                if self._answer_history and self._answer_history[-1] == last_q.correct_answer:
                    self._answer_history.pop()

                # Slot option constraints
                slot_opt_cfg = OptionWordCountConfig(
                    enabled=True,
                    style=last_slot.options_style,
                    word_count_min=last_slot.word_count_min,
                    word_count_max=last_slot.word_count_max,
                )

                try:
                    output = await generator.generate_question_from_context(
                        template=template,
                        slot=last_slot,
                        topic=topic,
                        context_text=result.context_text,
                        client=self.client,
                        grade=grade,
                        subject=subject,
                        cache_name=self._paragraph_cache,
                        question_model=question_model,
                        previous_questions=previous_questions,
                        validation_feedback=cross_feedback,
                    )

                    last_q.question = output.question
                    last_q.key_word = output.key_word
                    last_q.options = output.options
                    last_q.correct_answer = output.correct_answer
                    last_q.option_reasoning = output.option_reasoning

                    # Apply formatting
                    fmt_report = evaluate_formatting(
                        paragraph="",
                        question=output.question,
                        options=output.options,
                        cfg=self.formatting_constraints,
                    )
                    last_q.question = fmt_report.normalized_question
                    last_q.options = fmt_report.normalized_options

                    # Deterministic constraints
                    constraint_ok = True
                    opt_wc_report = evaluate_option_word_count(
                        last_q.options, slot_opt_cfg
                    )
                    if not opt_wc_report.passed:
                        constraint_ok = False
                    banned_ok, _ = check_banned_options(last_q.options)
                    if not banned_ok:
                        constraint_ok = False
                    abs_ok, _ = check_absolute_expressions(
                        last_q.question, last_q.options
                    )
                    if not abs_ok:
                        constraint_ok = False
                    bracket_ok, _ = check_bracket_remnants(
                        last_q.question, last_q.options
                    )
                    if not bracket_ok:
                        constraint_ok = False

                    # Shuffle
                    if last_slot.options_style != "roman_numeral_combination":
                        last_q.options, last_q.correct_answer, last_q.option_reasoning = (
                            shuffle_options(
                                last_q.options,
                                last_q.correct_answer,
                                last_q.option_reasoning,
                                answer_history=self._answer_history,
                            )
                        )

                    # Validate + context dependency in parallel
                    validation_result, ctx_dep_result = await asyncio.gather(
                        batch_validator.validate(
                            paragraph=result.context_text,
                            question=last_q.question,
                            options=last_q.options,
                            correct_answer=last_q.correct_answer,
                            grade=grade,
                            required_checks=self.required_checks,
                            distractor_strategies=distractor_strategy_info,
                            is_context_template=True,
                        ),
                        batch_validator.check_context_dependency(
                            context_text=result.context_text,
                            question=last_q.question,
                            options=last_q.options,
                            correct_answer=last_q.correct_answer,
                        ),
                    )
                    last_q.validation = _batch_to_validation_output(validation_result)

                    if not validation_result.passed or not constraint_ok:
                        log(f"      → Yeniden uretilen soru bireysel dogrulamayi gecemedi")
                        break

                    # Check context dependency (already computed in parallel)
                    ctx_dep_check = ctx_dep_result.get("context_dependency")
                    if ctx_dep_check and ctx_dep_check.status == "FAIL":
                        log(f"      → Yeniden uretilen soru baglam bagimliligi gecemedi")
                        break

                    # Update tracking
                    self._answer_history.append(last_q.correct_answer)
                    last_q.beceri_etiketi = last_slot.beceri
                    if last_q.option_reasoning:
                        last_q.celdirici_hata_kategorileri = map_option_error_categories(
                            last_q.option_reasoning, last_q.correct_answer
                        )
                    previous_questions.append({
                        "question": last_q.question,
                        "correct_answer": last_q.correct_answer,
                        "correct_text": last_q.options.get(last_q.correct_answer, ""),
                    })

                    log(f"      → Soru yeniden uretildi, capraz dogrulama tekrarlaniyor...")
                    # Clear cross_validation for re-evaluation in next iteration
                    result.cross_validation = CrossValidationResult(passed=True)

                except Exception as e:
                    logger.warning(f"[CROSS_VALIDATE] Retry error: {e}")
                    break

            # Step 6: Determine overall success — ALL slots must succeed AND expected count reached
            successful_count = sum(1 for q in result.questions if q.success)
            expected_count = ctx_config.question_count
            cross_passed_final = result.cross_validation.passed if result.cross_validation else True
            if not cross_passed_final:
                issues_str = "; ".join(result.cross_validation.issues[:3])
                log(f"      ✗ Capraz dogrulama BASARISIZ — grup uretilmeyecek: {issues_str}")
                result.success = False
            else:
                # Must have produced all expected slots AND each must be successful
                result.success = (
                    successful_count == expected_count
                    and len(result.questions) == expected_count
                )

            # Step 6.5: Context image generation (ONLY if all slots succeeded)
            # Moved here from before the slot loop so we don't waste API calls on an
            # image that would be discarded if any slot fails.
            if result.success:
                _gen_cfg = template.context.generation if template.context else None
                _image_type = getattr(_gen_cfg, 'image_type', None) if _gen_cfg else None
                if _image_type and self.image_config and self.image_config.enabled:
                    try:
                        from .tools.image_tools import generate_context_image_with_judge
                        log(f"[IMAGE] Baglam gorseli olusturuluyor ({_image_type})...")
                        img_result = await generate_context_image_with_judge(
                            context_text=result.context_text,
                            topic=topic,
                            image_type=_image_type,
                            cfg=self.image_config,
                            grade=grade,
                        )
                        if img_result.success and img_result.png_base64:
                            result.has_image = True
                            result.image_base64 = img_result.png_base64
                            log(
                                f"[IMAGE] Baglam gorseli basarili "
                                f"(judge iterations: {img_result.judge_iterations})"
                            )
                        else:
                            log(
                                f"[IMAGE] Baglam gorseli olusturulamadi: "
                                f"{img_result.error or 'bilinmeyen hata'}"
                            )
                    except Exception as e:
                        logger.warning(f"[CONTEXT_IMAGE] Gorsel uretim hatasi (non-blocking): {e}")
                        log(f"[IMAGE] Gorsel uretim hatasi: {e}")

            # Ethics check for all successful questions (parallel)
            ethics_passed = True
            ethics_tasks = []
            ethics_qs = []
            for q in result.questions:
                if q.success and q.question and q.options:
                    ethics_tasks.append(
                        batch_validator.check_ethics(
                            paragraph=result.context_text,
                            question=q.question,
                            options=q.options,
                            subject=subject,
                            grade=grade,
                        )
                    )
                    ethics_qs.append(q)

            if ethics_tasks:
                ethics_results = await asyncio.gather(
                    *ethics_tasks, return_exceptions=True
                )
                for q, eth_res in zip(ethics_qs, ethics_results):
                    if isinstance(eth_res, Exception):
                        logger.warning(
                            f"[ETHICS] Soru {q.slot} check error (non-blocking): {eth_res}"
                        )
                        continue
                    ethics_check = eth_res.get("ethics_check")
                    if ethics_check and ethics_check.status == "FAIL":
                        ethics_passed = False
                        logger.warning(
                            f"[ETHICS] Soru {q.slot} FAIL: {ethics_check.feedback}"
                        )
                        log(f"      ⚠ Soru {q.slot} etik kontrol FAIL: {ethics_check.feedback}")
                    else:
                        logger.info(f"[ETHICS] Soru {q.slot} OK")

            # Publication status (karar ağacı)
            # Use the last successful validation result for the decision tree
            # For context groups, we check cross-validation status too
            cross_passed = result.cross_validation.passed if result.cross_validation else True
            # Collect constraint feedback from the last validation round
            # (if all passed during retries, constraint_feedback will be empty)
            final_constraint_feedback = ""
            if result.questions:
                last_q = result.questions[-1]
                if not last_q.success:
                    final_constraint_feedback = "validation_failed"

            # Build a minimal validation result for compute_publication_status
            # We use the last question's batch validation as representative
            from .batch_validator import BatchValidationResult as _BVR, BatchCheckResult as _BCR
            merged_checks: dict[str, _BCR] = {}
            for q in result.questions:
                if q.validation:
                    for vc in q.validation.checks:
                        if vc.status == "FAIL":
                            merged_checks[vc.check_type] = _BCR(
                                check_type=vc.check_type,
                                check_name=vc.check_name,
                                status="FAIL",
                                score=vc.score,
                                feedback=vc.feedback,
                            )
            merged_result = _BVR(
                passed=all(c.status == "PASS" for c in merged_checks.values()) if merged_checks else True,
                overall_score=0.0,
                checks=merged_checks,
            )

            result.yayinlanma_durumu = compute_publication_status(
                validation_result=merged_result,
                constraint_feedback=final_constraint_feedback,
                ethics_passed=ethics_passed,
                cross_validation_passed=cross_passed,
            )
            log(f"      Yayinlanma durumu: {result.yayinlanma_durumu}")

            log(f"[6/6] Sonuc: {successful_count}/{len(result.questions)} soru basarili")
            return result

        except Exception as e:
            result.error = str(e)
            log(f"[ERROR] Hata: {e}")
            logger.exception("Context group workflow error")
            return result

    @staticmethod
    def _cross_validate_group(
        questions: list[ContextSubQuestionResult],
    ) -> CrossValidationResult:
        """Deterministic cross-validation of sub-questions in a group.

        Checks:
        - Answer distribution (same letter >2 times → warning)
        - Option text overlap (>80% word similarity → warning)
        - Question stem similarity (>70% → warning)
        """
        issues: list[str] = []
        duplicate_answers: list[str] = []
        overlapping_distractors: list[str] = []

        successful = [q for q in questions if q.success]
        if len(successful) < 2:
            return CrossValidationResult(passed=True)

        # Check answer distribution
        answer_counts: dict[str, int] = {}
        for q in successful:
            letter = q.correct_answer
            answer_counts[letter] = answer_counts.get(letter, 0) + 1

        for letter, count in answer_counts.items():
            if count > 2:
                msg = f"Dogru cevap '{letter}' {count} kez tekrarlaniyor"
                issues.append(msg)
                duplicate_answers.append(msg)

        # Check option text overlap between questions
        def _word_set(text: str) -> set[str]:
            return set(text.lower().split())

        for i, q1 in enumerate(successful):
            for j, q2 in enumerate(successful):
                if j <= i:
                    continue
                # Compare correct answer texts
                w1 = _word_set(q1.options.get(q1.correct_answer, ""))
                w2 = _word_set(q2.options.get(q2.correct_answer, ""))
                if w1 and w2:
                    overlap = len(w1 & w2) / max(len(w1 | w2), 1)
                    if overlap > 0.8:
                        msg = (
                            f"Soru {q1.slot} ve {q2.slot} dogru cevaplari "
                            f"cok benzer (%{overlap*100:.0f} ortusme)"
                        )
                        issues.append(msg)
                        overlapping_distractors.append(msg)

        # Check question stem similarity
        for i, q1 in enumerate(successful):
            for j, q2 in enumerate(successful):
                if j <= i:
                    continue
                w1 = _word_set(q1.question)
                w2 = _word_set(q2.question)
                if w1 and w2:
                    overlap = len(w1 & w2) / max(len(w1 | w2), 1)
                    if overlap > 0.7:
                        msg = (
                            f"Soru {q1.slot} ve {q2.slot} kokleri "
                            f"cok benzer (%{overlap*100:.0f} ortusme)"
                        )
                        issues.append(msg)

        return CrossValidationResult(
            passed=len(issues) == 0,
            issues=issues,
            duplicate_answers=duplicate_answers,
            overlapping_distractors=overlapping_distractors,
        )

    async def generate_multi_question(
        self,
        template_id: str,
        topic: str,
        grade: int = 5,
        subject: str = "turkce",
        on_progress: Callable[[str], None] | None = None,
        image_config_override: ImageGeneratorConfig | None = None,
    ) -> MultiQuestionGenerationResult:
        """
        Generate multiple questions from a single paragraph/context.

        Used for beceri_temelli templates with questions_per_context > 1.
        Paragraph is generated once, then N questions are generated with variety hints.

        Args:
            template_id: Template identifier
            topic: Topic string
            grade: Target grade level
            subject: Subject code
            on_progress: Optional progress callback
            image_config_override: Optional per-call image config override

        Returns:
            MultiQuestionGenerationResult with shared paragraph and N questions
        """

        def log(msg: str) -> None:
            logger.info(msg)
            if on_progress:
                on_progress(msg)

        multi_result = MultiQuestionGenerationResult(
            topic=topic,
            question_type=template_id,
            success=False,
        )

        try:
            # Step 1: Load template
            log(f"[1/5] Sablon yukleniyor: {template_id}")
            template = self.template_loader.load(template_id)
            questions_per_context = template.format.questions_per_context

            multi_result.options_layout = template.format.options.layout
            # Skip default html_template if it doesn't have enough options
            html_tmpl = template.format.html_template
            if html_tmpl and template.format.options.count > 4 and "{option_e}" not in html_tmpl:
                multi_result.html_body_template = None
            else:
                multi_result.html_body_template = html_tmpl
            if isinstance(getattr(template, "beceri", None), BeceriConfig):
                multi_result.context_type = template.beceri.context_type

            # Auto-build constraints
            template_para_cfg, template_opt_wc_cfg = build_constraints_from_template(template)
            effective_para_cfg = self.paragraph_constraints or template_para_cfg
            effective_opt_wc_cfg = template_opt_wc_cfg

            # Resolve models
            para_model = self._resolve_model(template, "paragraph_writer")
            question_model = self._resolve_model(template, "question_crafter")
            validator_model = self._resolve_model(template, "validator")

            log(f"      Sorulacak soru sayisi: {questions_per_context}")
            log(f"      Modeller: para={para_model}, soru={question_model}")

            # Step 2: Get generator
            generator = get_generator(template.format)
            log(f"[2/5] Format: {template.format.type}")

            # Step 3: Generate paragraph once
            paragraph_text = ""
            if template.format.paragraph.required:
                log("[3/5] Paragraf olusturuluyor...")
                paragraph_result = await generator.generate_paragraph(
                    template=template,
                    topic=topic,
                    subject=subject,
                    grade=grade,
                    client=self.client,
                    cache_name=self._paragraph_cache,
                    model=para_model,
                )
                paragraph_text = paragraph_result.paragraph
                multi_result.paragraph = paragraph_text
                multi_result.key_concepts = paragraph_result.key_concepts
                multi_result.difficulty_level = paragraph_result.difficulty_level
            else:
                log("[3/5] Paragraf atlanıyor (inverse format)")

            # Step 4: Generate N questions from same paragraph
            log(f"[4/5] {questions_per_context} soru olusturuluyor...")
            previous_questions: list[SingleQuestionResult] = []

            batch_validator = BatchValidator(
                client=self.client,
                model=validator_model,
                cache_name=self._validator_cache,
            )
            distractor_strategy_info = self._build_distractor_strategy_info(template)

            all_succeeded = True

            for q_idx in range(questions_per_context):
                log(f"      Soru {q_idx + 1}/{questions_per_context} olusturuluyor...")

                # Build variety hint from previous questions
                variety_hint = None
                if previous_questions:
                    hint_lines = ["ONCEDEN URETILEN SORULAR (TEKRARLAMA!):"]
                    for prev in previous_questions:
                        hint_lines.append(
                            f"- {prev.question} (Cevap: {prev.correct_answer})"
                        )
                    variety_hint = "\n".join(hint_lines)

                # Generate question
                output = await generator.generate_question(
                    template=template,
                    topic=topic,
                    paragraph=paragraph_text,
                    client=self.client,
                    grade=grade,
                    subject=subject,
                    cache_name=self._paragraph_cache,
                    question_model=question_model,
                    validation_feedback=variety_hint,
                )

                # Build single question result
                q_options = output.options
                q_correct = output.correct_answer
                q_reasoning = output.option_reasoning

                # Shuffle
                if not template.format.options.preserve_order:
                    q_options, q_correct, q_reasoning = shuffle_options(
                        q_options, q_correct, q_reasoning
                    )

                # Validate
                validation_result = await batch_validator.validate(
                    paragraph=paragraph_text,
                    question=output.question,
                    options=q_options,
                    correct_answer=q_correct,
                    grade=grade,
                    required_checks=self.required_checks,
                    distractor_strategies=distractor_strategy_info,
                    option_style=template.format.options.style,
                )

                sq = SingleQuestionResult(
                    question=output.question,
                    key_word=output.key_word,
                    options=q_options,
                    correct_answer=q_correct,
                    option_reasoning=q_reasoning,
                    validation=_batch_to_validation_output(validation_result),
                    answer_explanation=output.answer_explanation,
                    skill_tag=output.skill_tag,
                )

                if not validation_result.passed:
                    all_succeeded = False
                    log(f"      Soru {q_idx + 1} dogrulama BASARISIZ")

                previous_questions.append(sq)
                multi_result.questions.append(sq)

            multi_result.success = all_succeeded or len(multi_result.questions) > 0
            log(f"[5/5] {len(multi_result.questions)} soru olusturuldu")

            return multi_result

        except Exception as e:
            multi_result.error = str(e)
            log(f"[ERROR] Hata: {e}")
            logger.exception("Multi-question workflow error")
            return multi_result




# ============================================================================
# CONVENIENCE FUNCTION
# ============================================================================


async def generate_question_from_template(
    template_id: str,
    topic: str,
    grade: int = 5,
    subject: str = "turkce",
    curriculum_context: "MEBCurriculumContext | None" = None,
    default_models: dict[str, str] | None = None,
    required_checks: list[str] | None = None,
    max_fix_iterations: int = 3,
    on_progress: Callable[[str], None] | None = None,
    image_config: ImageGeneratorConfig | None = None,
) -> QuestionGenerationResult:
    """
    Generate a question using the template system.

    This is a convenience function for one-off generation.
    For batch generation, use GenericQuestionWorkflow directly.

    Args:
        template_id: Template identifier (e.g., "ana_fikir", "konu")
        topic: Topic string
        grade: Target grade level
        subject: Subject code
        curriculum_context: Optional MEB context for PDF grounding
        default_models: Optional default models configuration
        required_checks: Optional list of validation checks to run
        max_fix_iterations: Maximum retry attempts (default: 3)
        on_progress: Optional progress callback
        image_config: Optional image generation configuration

    Returns:
        QuestionGenerationResult
    """
    workflow = GenericQuestionWorkflow(
        curriculum_context=curriculum_context,
        default_models=default_models,
        required_checks=required_checks,
        max_fix_iterations=max_fix_iterations,
        image_config=image_config,
    )

    return await workflow.generate(
        template_id=template_id,
        topic=topic,
        grade=grade,
        subject=subject,
        on_progress=on_progress,
    )
