"""
Output saving tool for agentic question generator.

This module handles persisting generated questions to disk:
1. save_question_output() - Saves individual question (JSON + HTML + PNG)
2. save_batch_summary() - Saves statistics for a batch generation run

Output structure:
    output_dir/
        {topic_name}_{question_type}/
            question.json   - Full question data with metadata
            question.html   - Rendered HTML
            diagram.png     - Standalone diagram image (if generated)
            question.png    - Rendered image
        summary.json        - Batch statistics
"""

from __future__ import annotations

import base64
import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import logging

from .render_html import (
    render_detailed_html,
    render_detailed_context_group_html,
    render_question_html,
    render_multi_question_html,
    render_to_png,
    render_context_group_html,
)

# TYPE_CHECKING is False at runtime, True during type checking
# This avoids circular imports (workflow imports save_output, save_output imports schema types)
if TYPE_CHECKING:
    from ..schemas import QuestionGenerationResult, ContextQuestionGroupResult, MultiQuestionGenerationResult

__all__ = ["save_question_output", "save_multi_question_output", "save_batch_summary", "save_context_group_output"]

logger = logging.getLogger(__name__)


def _sanitize_filename(name: str) -> str:
    """
    Convert a topic name to a safe filename.

    - Replaces non-alphanumeric chars with underscore
    - Replaces spaces with underscores
    - Strips leading/trailing whitespace

    Args:
        name: Raw topic name (may contain Turkish chars, spaces, etc.)

    Returns:
        Filesystem-safe name
    """
    # Keep alphanumeric, dash, underscore, space
    safe = "".join(
        c if c.isalnum() or c in "-_ " else "_"
        for c in name
    ).strip()
    # Replace spaces with underscores
    return safe.replace(" ", "_")


# Bolum 7 template prefix mapping (template_id pattern → section number)
_BOLUM7_PREFIX_MAP = [
    ("sekil_sembol_", "7.1"),
    ("gorsel_inceleme_", "7.2"),
    ("paragraf_gorsel_", "7.3"),
    ("infografik_", "7.4"),
    ("tablo_yorumlama_", "7.5"),
    ("grafik_yorumlama_", "7.6"),
    ("sozel_mantik_siralama_sonucu_", "7.7"),
    ("sozel_mantik_aile_iliski_", "7.8"),
    ("sozel_mantik_kural_eleme_", "7.9"),
    ("sozel_mantik_yanlis_olani_bulma_", "7.10"),
]


def _get_section_prefix(template_id: str) -> str:
    """Return 'X.Y_' prefix if template matches Bolum 7 mapping, else empty string."""
    if not template_id:
        return ""
    for pattern, prefix in _BOLUM7_PREFIX_MAP:
        if pattern in template_id:
            return f"{prefix}_"
    return ""


def _get_section_subdir(template_id: str) -> str:
    """Return section subdir name ('7.1', '7.10', etc.) for Bolum 7 templates, else empty."""
    if not template_id:
        return ""
    for pattern, prefix in _BOLUM7_PREFIX_MAP:
        if pattern in template_id:
            return prefix
    return ""


async def save_question_output(
    result: "QuestionGenerationResult",
    output_dir: Path,
    render_png: bool = True,
    question_index: int | None = None,
    background_color: str | None = None,
) -> dict[str, Any]:
    """
    Save a question generation result to files.

    Creates a directory for the question containing:
    - question.json: Full question data with all metadata
    - question.html: Rendered HTML (if generation succeeded)
    - diagram.png: Standalone diagram image (if image generation was enabled)
    - question.png: Rendered image (if render_png=True and generation succeeded)
    - question_detailed.png: Detailed view with metadata (option reasoning,
                             validation checks, curriculum grounding)

    Args:
        result: The QuestionGenerationResult from orchestrator
        output_dir: Base output directory
        render_png: Whether to render PNG (requires Playwright)
        question_index: Optional index for multiple questions per topic
                       (0-indexed internally, displayed as 1-indexed in folder)

    Returns:
        Dict with paths to created files:
        {
            "json": Path to question.json,
            "html": Path to question.html (if created),
            "diagram": Path to diagram.png (if image was generated),
            "png": Path to question.png (if created),
            "detailed_png": Path to question_detailed.png (if created),
            "diagram_error": Error message (if diagram save failed),
            "png_error": Error message (if PNG failed),
            "detailed_png_error": Error message (if detailed PNG failed)
        }

    Example:
        result = await orchestrator.generate(topic="Besin Zinciri", ...)
        files = await save_question_output(result, Path("output/fen/5_sinif"))
        print(f"Saved to: {files['json']}")
    """
    output_dir = Path(output_dir)

    # Create directory name from topic + question type
    safe_topic = _sanitize_filename(result.topic)
    prefix = _get_section_prefix(result.question_type)
    subdir = _get_section_subdir(result.question_type)
    base_dir = output_dir / subdir if subdir else output_dir

    # Append question index if multiple questions per topic (1-indexed for readability)
    if question_index is not None:
        question_dir = base_dir / f"{prefix}{safe_topic}_{result.question_type}_{question_index + 1}"
    else:
        question_dir = base_dir / f"{prefix}{safe_topic}_{result.question_type}"

    question_dir.mkdir(parents=True, exist_ok=True)

    logger.debug(
        f"[SAVE OUTPUT]\n{'='*60}\n"
        f"Topic: {result.topic}\n"
        f"Template: {result.question_type}\n"
        f"Success: {result.success}\n"
        f"Directory: {question_dir}\n"
        f"Has image: {result.has_image}\n"
        f"html_body_template: {'yes' if result.html_body_template else 'no'}\n"
        f"options_layout: {result.options_layout}\n"
        f"{'='*60}"
    )

    created_files: dict[str, Any] = {}

    # 1. Save JSON (always)
    json_path = question_dir / "question.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    created_files["json"] = json_path

    # 2. Generate and save HTML (only if generation succeeded)
    # Note: paragraph can be empty for inverse format (e.g., konu_inverse)
    # so we check `paragraph is not None` instead of just `paragraph`
    if result.success and result.paragraph is not None and result.question:
        # For image_context (poster/afis), hide paragraph text - image IS the context
        display_paragraph = "" if result.image_context and result.has_image else result.paragraph
        html_content = render_question_html(
            paragraph=display_paragraph,
            question=result.question,
            options=result.options,
            correct_answer=result.correct_answer,
            key_word=result.key_word,
            image_base64=result.image_base64,  # Pass image if available
            options_layout=result.options_layout,
            html_body_template=result.html_body_template,
            option_images=result.option_images,
            background_color=background_color,
        )

        html_path = question_dir / "question.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        created_files["html"] = html_path

        # 3a. Save option images as standalone PNGs (gorsel_siklar)
        if result.option_images:
            for label, img_b64 in result.option_images.items():
                try:
                    opt_img_path = question_dir / f"option_{label.lower()}.png"
                    opt_img_path.write_bytes(base64.b64decode(img_b64))
                    created_files[f"option_{label.lower()}_png"] = opt_img_path
                except Exception as e:
                    created_files[f"option_{label.lower()}_error"] = str(e)

        # 3b. Save image as standalone PNG (if available)
        if result.has_image and result.image_base64:
            try:
                image_path = question_dir / "question_image.png"
                image_path.write_bytes(base64.b64decode(result.image_base64))
                created_files["question_image"] = image_path
            except Exception as e:
                created_files["question_image_error"] = str(e)

        # 4. Render PNG (optional, gracefully handles failures)
        if render_png:
            try:
                png_path = question_dir / "question.png"
                # Wider render for image options
                png_width = 800 if result.option_images else 340
                await render_to_png(html_content, png_path, width=png_width)
                created_files["png"] = png_path
            except Exception as e:
                # PNG rendering is optional - don't fail the whole save
                created_files["png_error"] = str(e)

            # 5. Render detailed PNG with metadata (option reasoning, validation, curriculum)
            try:
                # Build validation dict for the detailed view
                validation_dict = None
                if result.validation:
                    # Handle both Pydantic model and dataclass formats
                    checks_list = []
                    for c in result.validation.checks:
                        if hasattr(c, 'model_dump'):
                            # Pydantic model (ValidationCheckOutput)
                            check_dict = c.model_dump()
                            checks_list.append({
                                "type": check_dict.get("check_type", ""),
                                "name": check_dict.get("check_name", ""),
                                "status": check_dict.get("status", "FAIL"),
                                "score": check_dict.get("score", 0),
                                "feedback": check_dict.get("feedback", ""),
                            })
                        else:
                            # Dataclass (backwards compatibility)
                            checks_list.append({
                                "type": getattr(c, 'check_type', ''),
                                "name": getattr(c, 'check_name', ''),
                                "status": getattr(c, 'status', 'FAIL'),
                                "score": getattr(c, 'score', 0),
                                "feedback": getattr(c, 'feedback', ''),
                            })
                    validation_dict = {
                        "passed": result.validation.passed,
                        "overall_score": result.validation.overall_score,
                        "checks": checks_list,
                    }

                detailed_html = render_detailed_html(
                    paragraph=result.paragraph,
                    question=result.question,
                    options=result.options,
                    correct_answer=result.correct_answer,
                    option_reasoning=result.option_reasoning,
                    validation=validation_dict,
                    curriculum_source=result.curriculum_source,
                    curriculum_reasoning=result.curriculum_reasoning,
                    image_base64=result.image_base64,
                    options_layout=result.options_layout,
                    option_images=result.option_images,
                )

                detailed_png_path = question_dir / "question_detailed.png"
                await render_to_png(detailed_html, detailed_png_path, width=740, height=800)
                created_files["detailed_png"] = detailed_png_path
            except Exception as e:
                # Detailed PNG is optional - don't fail the whole save
                created_files["detailed_png_error"] = str(e)

    return created_files


async def save_multi_question_output(
    result: "MultiQuestionGenerationResult",
    output_dir: Path,
    render_png: bool = True,
) -> dict[str, Any]:
    """
    Save a multi-question generation result to files.

    Creates:
    - questions.json: All questions with shared paragraph
    - questions.html: Combined view with paragraph + N questions
    - questions.png: Rendered PNG (optional)

    Args:
        result: MultiQuestionGenerationResult
        output_dir: Base output directory
        render_png: Whether to render PNG

    Returns:
        Dict with paths to created files
    """
    output_dir = Path(output_dir)
    safe_topic = _sanitize_filename(result.topic)
    prefix = _get_section_prefix(result.question_type)
    subdir = _get_section_subdir(result.question_type)
    base_dir = output_dir / subdir if subdir else output_dir
    question_dir = base_dir / f"{prefix}{safe_topic}_{result.question_type}"
    question_dir.mkdir(parents=True, exist_ok=True)

    created_files: dict[str, Any] = {}

    # 1. Save JSON
    json_path = question_dir / "questions.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    created_files["json"] = json_path

    # 2. Render HTML
    if result.success and result.questions:
        questions_data = [
            {
                "question": q.question,
                "options": q.options,
                "correct_answer": q.correct_answer,
            }
            for q in result.questions
        ]

        html_content = render_multi_question_html(
            paragraph=result.paragraph,
            questions=questions_data,
            image_base64=result.image_base64,
        )

        html_path = question_dir / "questions.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        created_files["html"] = html_path

        # 3. Render PNG
        if render_png:
            try:
                png_path = question_dir / "questions.png"
                await render_to_png(html_content, png_path)
                created_files["png"] = png_path
            except Exception as e:
                created_files["png_error"] = str(e)

    return created_files


def save_batch_summary(
    results: list["QuestionGenerationResult"],
    output_dir: Path,
    config: dict | None = None,
) -> Path:
    """
    Save a summary of batch generation results.

    Creates summary.json with:
    - Timestamp
    - Overall statistics (total, success, failed, rate)
    - Breakdown by question type
    - Validation statistics (average score, check pass rates)
    - Per-result summary (topic, type, success, errors)
    - Original config (for reproducibility)

    Args:
        results: List of QuestionGenerationResult objects
        output_dir: Directory to save summary.json
        config: Optional config dict to include for reproducibility

    Returns:
        Path to the created summary.json file

    Example:
        results = await batch_generate(topics, config)
        summary_path = save_batch_summary(results, config.output_dir, config_dict)
        print(f"Batch summary: {summary_path}")
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Calculate overall statistics
    total = len(results)
    successful = sum(1 for r in results if r.success)
    failed = total - successful

    # Count by question type (context groups don't have question_type — use template_id)
    by_type: dict[str, dict] = {}
    for r in results:
        qt = getattr(r, "question_type", None) or getattr(r, "template_id", None) or "context_group"
        if qt not in by_type:
            by_type[qt] = {"total": 0, "success": 0, "failed": 0}
        by_type[qt]["total"] += 1
        if r.success:
            by_type[qt]["success"] += 1
        else:
            by_type[qt]["failed"] += 1

    # Validation statistics (for results that have validation)
    validation_stats: dict[str, Any] = {
        "avg_score": 0,
        "avg_fix_iterations": 0,
        "checks": {},
    }

    scores: list[float] = []
    fix_iters: list[int] = []

    for r in results:
        _val = getattr(r, "validation", None)
        if _val:
            scores.append(_val.overall_score)
            fix_iters.append(getattr(r, "fix_iterations", 0))

            # Count pass/fail for each check type
            for check in _val.checks:
                ct = check.check_type
                if ct not in validation_stats["checks"]:
                    validation_stats["checks"][ct] = {
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                    }
                validation_stats["checks"][ct]["total"] += 1
                if check.status == "PASS":
                    validation_stats["checks"][ct]["passed"] += 1
                else:
                    validation_stats["checks"][ct]["failed"] += 1

    if scores:
        validation_stats["avg_score"] = sum(scores) / len(scores)
    if fix_iters:
        validation_stats["avg_fix_iterations"] = sum(fix_iters) / len(fix_iters)

    # Build summary document
    summary = {
        "timestamp": datetime.now().isoformat(),
        "statistics": {
            "total": total,
            "successful": successful,
            "failed": failed,
            "success_rate": successful / total if total > 0 else 0,
        },
        "by_question_type": by_type,
        "validation_stats": validation_stats,
        "config": config,
        "results": [
            {
                "topic": r.topic,
                "question_type": getattr(r, "question_type", None) or getattr(r, "template_id", "context_group"),
                "success": r.success,
                "error": getattr(r, "error", None),
                "fix_iterations": getattr(r, "fix_iterations", 0),
                "validation_score": r.validation.overall_score if getattr(r, "validation", None) else None,
            }
            for r in results
        ],
    }

    # Save to file
    summary_path = output_dir / "summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    return summary_path


async def save_context_group_output(
    result: "ContextQuestionGroupResult",
    output_dir: Path,
    render_png: bool = True,
    background_color: str | None = None,
) -> dict[str, Any]:
    """Save a context-based question group result to files.

    Creates:
        {topic}_{context_type}_group/
            group.json          # Full group data
            group.html          # Rendered HTML
            group.png           # PNG output
            question_1.json     # Sub-question 1
            question_2.json     # Sub-question 2
            ...

    Args:
        result: ContextQuestionGroupResult
        output_dir: Base output directory
        render_png: Whether to render PNG

    Returns:
        Dict with paths to created files
    """
    output_dir = Path(output_dir)

    safe_topic = _sanitize_filename(result.topic)
    prefix = _get_section_prefix(result.context_type)
    subdir = _get_section_subdir(result.context_type)
    base_dir = output_dir / subdir if subdir else output_dir
    group_dir = base_dir / f"{prefix}{safe_topic}_{result.context_type}_group"
    group_dir.mkdir(parents=True, exist_ok=True)

    created_files: dict[str, Any] = {}

    # 1. Save group JSON
    json_path = group_dir / "group.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)
    created_files["json"] = json_path

    # 2. Save individual sub-question JSONs
    for q in result.questions:
        q_path = group_dir / f"question_{q.slot}.json"
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
        with open(q_path, "w", encoding="utf-8") as f:
            json.dump(q_dict, f, ensure_ascii=False, indent=2)
        created_files[f"question_{q.slot}"] = q_path

    # 3. Render group HTML
    successful_questions = [q for q in result.questions if q.success]
    if successful_questions:
        questions_data = [
            {
                "question": q.question,
                "options": q.options,
                "option_images": getattr(q, "option_images", None),
            }
            for q in successful_questions
        ]
        correct_answers = [q.correct_answer for q in successful_questions]

        html_content = render_context_group_html(
            header_text=result.header_text,
            context_text=result.context_text,
            questions=questions_data,
            correct_answers=correct_answers,
            image_base64=getattr(result, 'image_base64', None),
            background_color=background_color,
        )

        html_path = group_dir / "group.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        created_files["html"] = html_path

        # 3b. Save standalone context image (if available)
        if getattr(result, 'has_image', False) and result.image_base64:
            try:
                img_path = group_dir / "context_image.png"
                img_path.write_bytes(base64.b64decode(result.image_base64))
                created_files["context_image"] = img_path
            except Exception as e:
                created_files["context_image_error"] = str(e)

        # 4. Render PNG
        if render_png:
            try:
                png_path = group_dir / "group.png"
                await render_to_png(html_content, png_path)
                created_files["png"] = png_path
            except Exception as e:
                created_files["png_error"] = str(e)

            # 5. Render detailed PNG with metadata
            try:
                # Build per-question validation dicts
                validation_dicts = []
                for q in successful_questions:
                    if q.validation:
                        checks_list = []
                        for c in q.validation.checks:
                            if hasattr(c, 'model_dump'):
                                check_dict = c.model_dump()
                                checks_list.append({
                                    "type": check_dict.get("check_type", ""),
                                    "name": check_dict.get("check_name", ""),
                                    "status": check_dict.get("status", "FAIL"),
                                    "score": check_dict.get("score", 0),
                                    "feedback": check_dict.get("feedback", ""),
                                })
                            else:
                                checks_list.append({
                                    "type": getattr(c, 'check_type', ''),
                                    "name": getattr(c, 'check_name', ''),
                                    "status": getattr(c, 'status', 'FAIL'),
                                    "score": getattr(c, 'score', 0),
                                    "feedback": getattr(c, 'feedback', ''),
                                })
                        validation_dicts.append({
                            "passed": q.validation.passed,
                            "overall_score": q.validation.overall_score,
                            "checks": checks_list,
                        })
                    else:
                        validation_dicts.append(None)

                option_reasonings = [q.option_reasoning for q in successful_questions]

                cross_val_dict = None
                if result.cross_validation:
                    cross_val_dict = {
                        "passed": result.cross_validation.passed,
                        "issues": result.cross_validation.issues,
                        "duplicate_answers": result.cross_validation.duplicate_answers,
                        "overlapping_distractors": result.cross_validation.overlapping_distractors,
                    }

                detailed_html = render_detailed_context_group_html(
                    header_text=result.header_text,
                    context_text=result.context_text,
                    questions=questions_data,
                    correct_answers=correct_answers,
                    option_reasonings=option_reasonings,
                    validations=validation_dicts,
                    cross_validation=cross_val_dict,
                    curriculum_source=result.curriculum_source,
                    curriculum_reasoning=result.curriculum_reasoning,
                    image_base64=getattr(result, 'image_base64', None),
                )

                detailed_png_path = group_dir / "group_detailed.png"
                await render_to_png(detailed_html, detailed_png_path, width=740, height=800)
                created_files["detailed_png"] = detailed_png_path
            except Exception as e:
                created_files["detailed_png_error"] = str(e)

    return created_files
