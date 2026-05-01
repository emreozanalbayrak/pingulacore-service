"""
CLI for the agentic question generator.

Usage:
    # Run from config file (simplest)
    python -m legacy_app.kadir_hoca.agentic --config template_config.yaml
    python -m legacy_app.kadir_hoca.agentic -c template_config.yaml

    # Override template/topic via CLI
    python -m legacy_app.kadir_hoca.agentic -c template_config.yaml --template ana_fikir --topic "..."

    # List available templates
    python -m legacy_app.kadir_hoca.agentic --list-templates

    # Extract question types from PDF
    python -m legacy_app.kadir_hoca.agentic --extract-question-types book.pdf
"""

import argparse
import asyncio
import logging
import base64
import json
import os
import random
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml


# Load .env file if it exists (for API keys)
def _load_dotenv():
    """Load environment variables from .env file in current directory or parent."""
    for env_path in [Path(".env"), Path(__file__).parent.parent / ".env"]:
        if env_path.exists():
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        # Handle KEY="value" or KEY=value format
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"').strip("'")
                        if key and value:
                            os.environ.setdefault(key, value)
            return True
    return False


_load_dotenv()

from .tools.pdf_question_type_extractor import extract_question_types_from_pdf
from .tools.save_output import save_question_output, save_multi_question_output, save_batch_summary, save_context_group_output, _sanitize_filename, _get_section_prefix, _get_section_subdir
from .tools.image_tools import ImageGeneratorConfig
from .templates import TemplateLoader, commit_reserved_stem, release_reserved_stem
from .generic_workflow import GenericQuestionWorkflow, generate_question_from_template
from .tools.curriculum_tools import MEBCurriculumContext, CacheConfig


def load_template_config(config_path: Path) -> dict:
    """
    Load template workflow configuration from YAML file.

    Returns dict with:
    - models: dict with paragraph_writer, question_crafter, validator
    - grounding: dict with enabled, pdf_path, cache_ttl
    - validation: dict with max_fix_iterations, required_checks
    - paragraph_constraints: dict (optional)
    - option_constraints: dict (optional)
    - formatting_constraints: dict (optional)
    - output: dict (optional)
    """
    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # Resolve relative paths based on config file location
    config_dir = config_path.parent

    if "grounding" in config and config["grounding"].get("pdf_path"):
        pdf_path = config["grounding"]["pdf_path"]
        if not Path(pdf_path).is_absolute():
            config["grounding"]["pdf_path"] = str(config_dir / pdf_path)

    # Resolve data_pdf_paths (list) or data_pdf_path (single, backward compat)
    if "grounding" in config:
        grounding = config["grounding"]
        # Support both singular and plural forms
        data_paths = grounding.get("data_pdf_paths", [])
        if not data_paths and grounding.get("data_pdf_path"):
            data_paths = [grounding["data_pdf_path"]]
        resolved = []
        for dp in data_paths:
            if not Path(dp).is_absolute():
                resolved.append(str(config_dir / dp))
            else:
                resolved.append(dp)
        if resolved:
            grounding["data_pdf_paths"] = resolved

    if "output" in config and config["output"].get("dir"):
        out_dir = config["output"]["dir"]
        if not Path(out_dir).is_absolute():
            config["output"]["dir"] = str(config_dir / out_dir)

    if config.get("topics_file"):
        tf = config["topics_file"]
        if not Path(tf).is_absolute():
            config["topics_file"] = str(config_dir / tf)

    return config


def _refresh_saved_result_json(json_path: Path, result) -> None:
    """Rewrite saved result JSON after post-save stem bookkeeping."""
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)


# ============================================================================
# GENERATION PLAN (Multi-Template Batch)
# ============================================================================


@dataclass
class GenerationGroup:
    """A group of topics sharing the same template and settings."""

    template_id: str
    topic_indices: list[int] = field(default_factory=list)  # 0-indexed internally
    image_override: bool | None = None  # None = use global default
    visual_context: bool = False  # If True, generate question-aware visual (solvable from image alone)


def parse_topic_ranges(range_str: str, total: int) -> list[int]:
    """
    Parse a topic range string into 0-indexed topic indices.

    Supports:
      "1-3"     → [0, 1, 2]
      "1,3,5"   → [0, 2, 4]
      "1-3,7,10-12" → [0, 1, 2, 6, 9, 10, 11]

    Args:
        range_str: Comma-separated ranges/singles (1-indexed).
        total: Total number of topics (for bounds checking).

    Returns:
        Sorted list of 0-indexed topic indices.

    Raises:
        ValueError: If indices are out of range or syntax is invalid.
    """
    indices: set[int] = set()

    for part in range_str.split(","):
        part = part.strip()
        if not part:
            continue

        if "-" in part:
            bounds = part.split("-", 1)
            if len(bounds) != 2 or not bounds[0].strip().isdigit() or not bounds[1].strip().isdigit():
                raise ValueError(
                    f"Gecersiz aralik formati: '{part}'. "
                    f"Beklenen: 'baslangic-bitis' (ornek: '1-3')"
                )
            start = int(bounds[0].strip())
            end = int(bounds[1].strip())
            if start > end:
                raise ValueError(
                    f"Gecersiz aralik: '{part}' — baslangic ({start}) bitis ({end}) degerinden buyuk olamaz"
                )
            if start < 1 or end > total:
                raise ValueError(
                    f"Aralik sinir disi: '{part}' — toplam konu sayisi: {total} (1-{total} arasi bekleniyor)"
                )
            indices.update(range(start - 1, end))  # Convert to 0-indexed
        else:
            if not part.isdigit():
                raise ValueError(
                    f"Gecersiz konu numarasi: '{part}'. Sayi bekleniyor."
                )
            idx = int(part)
            if idx < 1 or idx > total:
                raise ValueError(
                    f"Konu numarasi sinir disi: {idx} — toplam konu sayisi: {total} (1-{total} arasi bekleniyor)"
                )
            indices.add(idx - 1)  # Convert to 0-indexed

    return sorted(indices)


def parse_generation_plan(
    plan_config: list[dict], total_topics: int
) -> list[GenerationGroup]:
    """
    Parse and validate the generation_plan config section.

    Args:
        plan_config: List of group dicts from YAML config.
        total_topics: Total number of topics loaded from topics_file.

    Returns:
        List of validated GenerationGroup instances.

    Raises:
        ValueError: If config is invalid (missing fields, overlapping indices, etc.)
    """
    if not isinstance(plan_config, list) or not plan_config:
        raise ValueError("generation_plan bos olamaz — en az 1 grup gerekli")

    groups: list[GenerationGroup] = []

    for i, group_cfg in enumerate(plan_config, start=1):
        if not isinstance(group_cfg, dict):
            raise ValueError(f"Grup {i}: dict bekleniyor, {type(group_cfg).__name__} bulundu")

        # Required: template
        template_id = group_cfg.get("template")
        if not template_id:
            raise ValueError(f"Grup {i}: 'template' alani zorunlu")

        # Required: topics
        topics_str = group_cfg.get("topics")
        if not topics_str:
            raise ValueError(f"Grup {i}: 'topics' alani zorunlu (ornek: '1-3' veya '1,3,5')")

        try:
            topic_indices = parse_topic_ranges(str(topics_str), total_topics)
        except ValueError as e:
            raise ValueError(f"Grup {i} ({template_id}): {e}") from e

        if not topic_indices:
            raise ValueError(f"Grup {i} ({template_id}): bos konu listesi")

        # Topic reuse is now allowed - same topic can be used with different templates

        # Optional: image override
        image_override = group_cfg.get("image")
        if image_override is not None:
            image_override = bool(image_override)

        # Optional: visual_context (question-aware visual generation)
        visual_context = bool(group_cfg.get("visual_context", False))

        groups.append(GenerationGroup(
            template_id=template_id,
            topic_indices=topic_indices,
            image_override=image_override,
            visual_context=visual_context,
        ))

    return groups


def _resolve_image_config(
    base_config: ImageGeneratorConfig | None,
    image_override: bool | None,
    image_gen_raw: dict,
) -> ImageGeneratorConfig | None:
    """
    Resolve effective ImageGeneratorConfig for a generation group.

    Args:
        base_config: The global ImageGeneratorConfig (may be None if disabled globally).
        image_override: Group-level override (True/False/None).
        image_gen_raw: Raw image_generation dict from config YAML (for building config when base is None).

    Returns:
        ImageGeneratorConfig with correct enabled flag, or None if disabled.
    """
    if image_override is None:
        # No override — use global config (if enabled: false globally, won't generate)
        return base_config

    if image_override is False:
        # Explicitly disabled for this group
        return None

    # image_override is True — need an enabled config
    if base_config is not None:
        # Clone global config but force enabled=True
        return ImageGeneratorConfig(
            enabled=True,
            model=base_config.model,
            judge_model=base_config.judge_model,
            temperature=base_config.temperature,
            max_retries=base_config.max_retries,
            max_judge_iterations=base_config.max_judge_iterations,
            required_subjects=base_config.required_subjects,
        )

    # Global config is None (disabled/absent) — build from raw YAML with defaults
    return ImageGeneratorConfig(
        enabled=True,
        model=image_gen_raw.get("model", "gemini-3-pro-image-preview"),
        judge_model=image_gen_raw.get("judge_model", "gemini-3.1-pro-preview"),
        temperature=image_gen_raw.get("temperature", 0.2),
        max_retries=image_gen_raw.get("max_retries", 2),
        max_judge_iterations=image_gen_raw.get("max_judge_iterations", 3),
        required_subjects=image_gen_raw.get("required_subjects", []),
    )


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Agentic Turkish question generator with MEB curriculum grounding",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run from config file (simplest)
  python -m legacy_app.kadir_hoca.agentic --config template_config.yaml
  python -m legacy_app.kadir_hoca.agentic -c template_config.yaml

  # Override template/topic via CLI
  python -m legacy_app.kadir_hoca.agentic -c template_config.yaml --template ana_fikir --topic "..."

  # List available templates
  python -m legacy_app.kadir_hoca.agentic --list-templates

  # Extract question types from a PDF
  python -m legacy_app.kadir_hoca.agentic --extract-question-types book.pdf
        """,
    )

    # Template workflow arguments (primary mode)
    parser.add_argument(
        "--template",
        type=str,
        help="Template ID for question generation (e.g., konu, ana_fikir, baslik)",
    )

    parser.add_argument(
        "--topic",
        type=str,
        help="Topic for question generation (required with --template)",
    )

    parser.add_argument(
        "--grade",
        type=int,
        default=5,
        help="Grade level (default: 5)",
    )

    parser.add_argument(
        "--list-templates",
        action="store_true",
        help="List available templates and exit",
    )

    # Configuration file
    parser.add_argument(
        "--config", "-c",
        type=Path,
        dest="config",
        help="Path to config YAML file (e.g., template_config.yaml). "
             "Provides template, topic, models, validation, grounding PDF, etc.",
    )

    # Model and validation overrides
    parser.add_argument(
        "--model",
        type=str,
        help="Override model for all agents (e.g., gemini-2.0-flash, gemini-2.5-pro)",
    )

    parser.add_argument(
        "--checks",
        type=str,
        help="Override validation checks (comma-separated). "
             "Available: question_format,grade_level,accuracy,distractors,turkish,solvability,curriculum_alignment",
    )

    parser.add_argument(
        "--max-fix-iterations",
        type=int,
        help="Override max retry attempts for validation failures",
    )

    # PDF extraction utility
    parser.add_argument(
        "--extract-question-types",
        type=Path,
        help="Extract all distinct question stem templates from a PDF and exit",
    )

    parser.add_argument(
        "--extract-out",
        type=Path,
        default=Path("question_types_extracted.json"),
        help="Output JSON path for --extract-question-types (default: question_types_extracted.json)",
    )

    parser.add_argument(
        "--extract-model",
        type=str,
        default="gemini-2.5-pro",
        help="Gemini model for --extract-question-types",
    )

    # Output options
    parser.add_argument(
        "--no-png",
        action="store_true",
        help="Skip PNG rendering",
    )

    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress progress output",
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable detailed logging",
    )

    parser.add_argument(
        "--parallel",
        type=int,
        default=None,
        help="Number of parallel workers for batch mode (overrides config)",
    )

    # Stem registry management
    parser.add_argument(
        "--reset-stem-usage",
        action="store_true",
        help="Reset stem usage tracking to start fresh",
    )

    parser.add_argument(
        "--show-stem-stats",
        action="store_true",
        help="Display stem usage statistics",
    )

    return parser.parse_args()


def list_templates():
    """Print available templates."""
    print("\nMevcut sablonlar:\n")
    loader = TemplateLoader()
    templates = loader.list_templates()

    if not templates:
        print("  (Sablon bulunamadi)")
        print(f"  Sablon dizini: {loader.templates_dir}")
        return

    for template_id in templates:
        try:
            template = loader.load(template_id)
            print(f"  {template_id:15} - {template.meta.ad}")
            print(f"                   Format: {template.format.type}")
            if template.meta.aciklama:
                print(f"                   Aciklama: {template.meta.aciklama}")
            print(f"                   Soru kokleri: {len(template.soru_kokleri)} varyasyon")

            # Handle stem that can be string or dict
            first_stem = template.soru_kokleri[0] if template.soru_kokleri else ""
            if isinstance(first_stem, dict):
                first_stem = first_stem.get("pattern", str(first_stem))
            stem_preview = first_stem[:50] if len(first_stem) > 50 else first_stem
            print(f"                   Ornek: \"{stem_preview}...\"")
            print()
        except Exception as e:
            print(f"  {template_id:15} - (Hata: {e})")
            print()


async def run_template_generation(
    template_id: str,
    topic: str,
    grade: int,
    verbose: bool = False,
    default_models: dict[str, str] | None = None,
    required_checks: list[str] | None = None,
    max_fix_iterations: int = 3,
    curriculum_context: "MEBCurriculumContext | None" = None,
    output_dir: Path | None = None,
    render_png: bool = True,
    image_config: ImageGeneratorConfig | None = None,
    subject: str = "turkce",
) -> int:
    """Run template-driven question generation."""
    # Set up output directory
    save_dir = output_dir or Path("output")

    # Set up detailed file logging
    log_path = setup_file_logging(save_dir, verbose=verbose)

    print("\n" + "=" * 60)
    print("TEMPLATE-DRIVEN SORU URETICI")
    print("=" * 60)
    print(f"Sablon: {template_id}")
    print(f"Konu: {topic}")
    print(f"Sinif: {grade}. sinif")
    if default_models:
        models_str = ", ".join(f"{k}={v}" for k, v in default_models.items())
        print(f"Modeller: {models_str}")
    if required_checks:
        print(f"Kalite kontrolleri: {', '.join(required_checks)}")
    print(f"Max duzeltme: {max_fix_iterations}")
    if curriculum_context:
        print(f"MEB PDF: {curriculum_context.pdf_path.name}")
    print(f"Cikti dizini: {save_dir}")
    print(f"Log dosyasi: {log_path}")
    print(f"PNG olustur: {'Evet' if render_png else 'Hayir'}")
    if image_config and image_config.enabled:
        print(f"[IMAGE] Gorsel uretim aktif: model={image_config.model}")
    print("=" * 60 + "\n")

    # Get logger for this module
    workflow_logger = logging.getLogger("agentic.workflow")

    def on_progress(msg: str):
        print(msg)
        workflow_logger.info(msg)

    try:
        # Check if template uses multi-question per context
        loader = TemplateLoader()
        tmpl = loader.load(template_id)
        qpc = tmpl.format.questions_per_context

        if qpc > 1:
            # Multi-question generation
            workflow = GenericQuestionWorkflow(
                curriculum_context=curriculum_context,
                default_models=default_models,
                required_checks=required_checks,
                max_fix_iterations=max_fix_iterations,
                image_config=image_config,
            )
            multi_result = await workflow.generate_multi_question(
                template_id=template_id,
                topic=topic,
                grade=grade,
                subject=subject,
                on_progress=on_progress,
            )

            print("\n" + "=" * 60)
            if multi_result.success:
                print("SONUC: BASARILI")
                print("=" * 60)
                print(f"\nPARAGRAF:\n{multi_result.paragraph}\n")
                for i, q in enumerate(multi_result.questions, 1):
                    print(f"SORU {i}: {q.question}")
                    print(f"\nSIKLAR:")
                    for letter in sorted(q.options.keys()):
                        marker = " *" if letter == q.correct_answer else ""
                        print(f"  {letter}) {q.options.get(letter, '')}{marker}")
                    print(f"\nDOGRU CEVAP: {q.correct_answer}")
                    if q.answer_explanation:
                        print(f"ACIKLAMA: {q.answer_explanation}")
                    if q.skill_tag:
                        print(f"BECERI: {q.skill_tag}")
                    print()

                created_files = await save_multi_question_output(
                    result=multi_result,
                    output_dir=save_dir,
                    render_png=render_png,
                )

                print(f"Kaydedilen dosyalar:")
                print(f"  JSON: {created_files.get('json', 'N/A')}")
                if created_files.get("html"):
                    print(f"  HTML: {created_files['html']}")
                if created_files.get("png"):
                    print(f"  PNG: {created_files['png']}")
                elif created_files.get("png_error"):
                    print(f"  PNG: (hata: {created_files['png_error']})")
            else:
                print("SONUC: BASARISIZ")
                print("=" * 60)
                print(f"Hata: {multi_result.error}")
                return 1

            return 0

        # Standard single-question generation
        result = await generate_question_from_template(
            template_id=template_id,
            topic=topic,
            grade=grade,
            subject=subject,
            curriculum_context=curriculum_context,
            default_models=default_models,
            required_checks=required_checks,
            max_fix_iterations=max_fix_iterations,
            on_progress=on_progress,
            image_config=image_config,
        )

        print("\n" + "=" * 60)
        if result.success:
            print("SONUC: BASARILI")
            print("=" * 60)
            print(f"\nPARAGRAF:\n{result.paragraph}\n")
            print(f"SORU: {result.question}")
            print(f"\nSIKLAR:")
            for letter in sorted(result.options.keys()):
                marker = " *" if letter == result.correct_answer else ""
                print(f"  {letter}) {result.options.get(letter, '')}{marker}")
            print(f"\nDOGRU CEVAP: {result.correct_answer}")
            if result.has_image:
                print(f"\n[IMAGE] Diyagram basariyla eklendi")

            # Save using save_question_output (creates JSON, HTML, PNG, detailed PNG)
            created_files = await save_question_output(
                result=result,
                output_dir=save_dir,
                render_png=render_png,
            )

            print(f"\nKaydedilen dosyalar:")
            print(f"  JSON: {created_files.get('json', 'N/A')}")
            if created_files.get("html"):
                print(f"  HTML: {created_files['html']}")
            if created_files.get("png"):
                print(f"  PNG: {created_files['png']}")
            elif created_files.get("png_error"):
                print(f"  PNG: (hata: {created_files['png_error']})")
            if created_files.get("detailed_png"):
                print(f"  Detayli PNG: {created_files['detailed_png']}")
            elif created_files.get("detailed_png_error"):
                print(f"  Detayli PNG: (hata: {created_files['detailed_png_error']})")
        else:
            print("SONUC: BASARISIZ")
            print("=" * 60)
            print(f"Hata: {result.error}")
            return 1

        return 0

    except Exception as e:
        print(f"\n[ERROR] {e}")
        if verbose:
            import traceback
            traceback.print_exc()
        return 1


@dataclass
class BatchTask:
    """A single task in a batch generation run."""
    task_idx: int
    topic: str
    template_id: str
    image_config: ImageGeneratorConfig | None = None
    subject: str = "turkce"
    skip_existing: bool = False
    has_generation_plan: bool = False
    visual_context: bool = False  # If True, generate question-aware visual
    template_position: int = 0  # 0-based position of this task within its template group


async def _run_batch_core(
    tasks: list[BatchTask],
    workflow: GenericQuestionWorkflow,
    grade: int,
    save_dir: Path,
    render_png: bool,
    verbose: bool,
    parallel_workers: int,
    questions_per_topic: int,
    config: dict | None = None,
) -> tuple[int, int, list]:
    """
    Shared batch processing core for both simple and planned generation.

    Returns:
        (successful_count, failed_count, results_list)
    """
    total = len(tasks)
    workflow_logger = logging.getLogger("agentic.workflow")

    semaphore = asyncio.Semaphore(parallel_workers)
    results: list = [None] * total
    successful = 0
    failed = 0
    completed_count = 0
    print_lock = asyncio.Lock()

    async def process_task(task: BatchTask):
        nonlocal successful, failed, completed_count

        async with semaphore:
            for q_num in range(1, questions_per_topic + 1):
                q_suffix = (
                    f" (Soru {q_num}/{questions_per_topic})"
                    if questions_per_topic > 1 else ""
                )
                idx_label = f"[{task.task_idx + 1}/{total}]"

                # Skip logic for planned generation
                # Check both exact match (topic+template) and topic-only match
                # to handle shuffle_topics reordering topics across templates
                if task.skip_existing:
                    safe_topic = _sanitize_filename(task.topic)
                    prefix = _get_section_prefix(task.template_id)
                    subdir = _get_section_subdir(task.template_id)
                    _base = save_dir / subdir if subdir else save_dir
                    if questions_per_topic > 1:
                        q_dir = _base / f"{prefix}{safe_topic}_{task.template_id}_{q_num}"
                    else:
                        q_dir = _base / f"{prefix}{safe_topic}_{task.template_id}"
                    # Exact match (same topic + same template)
                    already_exists = (q_dir / "question.json").exists()
                    # Topic-only match: any folder starting with this topic
                    # ONLY for single-template mode (no generation_plan)
                    # When generation_plan is active, same topic with different
                    # template is intentional, so only exact match applies
                    if not already_exists and not task.has_generation_plan:
                        for existing in save_dir.iterdir():
                            if (
                                existing.is_dir()
                                and existing.name.startswith(safe_topic + "_")
                                and (existing / "question.json").exists()
                            ):
                                already_exists = True
                                break
                    if already_exists:
                        async with print_lock:
                            print(f"\n{'─' * 60}")
                            print(f"{idx_label} Konu: {task.topic}{q_suffix}")
                            print(f"  Sablon: {task.template_id}")
                            print(f"{'─' * 60}")
                            print(
                                f"  {idx_label}{q_suffix} "
                                f"⏭ Atlaniyor (mevcut)"
                            )
                        successful += 1
                        continue

                async with print_lock:
                    print(f"\n{'─' * 60}")
                    print(f"{idx_label} Konu: {task.topic}{q_suffix}")
                    if task.skip_existing:
                        print(f"  Sablon: {task.template_id}")
                    print(f"{'─' * 60}")

                def on_progress(
                    msg: str,
                    _topic=task.topic,
                    _idx_label=idx_label,
                    _q_suffix=q_suffix,
                ):
                    print(f"  {_idx_label}{_q_suffix} {msg}")
                    workflow_logger.info(
                        f"[{_topic}]{_q_suffix} {msg}"
                    )

                try:
                    # Check if template has multi-question support
                    tmpl = workflow.template_loader.load(task.template_id)
                    _bg_color = getattr(tmpl.format.paragraph, "background_color", None)
                    qpc = tmpl.format.questions_per_context

                    # Context template (has `context:` section) → use context group flow
                    if tmpl.is_context_template and q_num == 1:
                        group_result = await workflow.generate_context_group(
                            template_id=task.template_id,
                            topic=task.topic,
                            grade=grade,
                            subject=task.subject,
                            on_progress=on_progress,
                        )

                        results[task.task_idx] = group_result

                        if group_result.success:
                            successful += 1
                            q_count = len([q for q in group_result.questions if q.success])
                            answers = ",".join(
                                q.correct_answer for q in group_result.questions if q.success
                            )
                            print(
                                f"  {idx_label}{q_suffix} "
                                f"✓ Basarili — {q_count} soru, cevaplar: {answers}"
                            )
                            try:
                                created_files = await save_context_group_output(
                                    result=group_result,
                                    output_dir=save_dir,
                                    render_png=render_png,
                                    background_color=_bg_color,
                                )
                                if created_files.get("json"):
                                    print(
                                        f"  {idx_label}{q_suffix} "
                                        f"Kaydedildi: {created_files['json']}"
                                    )
                            except Exception as save_err:
                                print(
                                    f"  {idx_label}{q_suffix} "
                                    f"[WARNING] Kayit hatasi: {save_err}"
                                )
                        else:
                            failed += 1
                            err_msg = group_result.error or "bilinmeyen"
                            print(
                                f"  {idx_label}{q_suffix} "
                                f"✗ Basarisiz — {err_msg}"
                            )
                        break

                    elif tmpl.is_context_template and q_num > 1:
                        break

                    if qpc > 1 and q_num == 1:
                        # Multi-question: generate all questions from one paragraph
                        multi_result = await workflow.generate_multi_question(
                            template_id=task.template_id,
                            topic=task.topic,
                            grade=grade,
                            subject=task.subject,
                            on_progress=on_progress,
                            image_config_override=task.image_config,
                        )

                        results[task.task_idx] = multi_result

                        if multi_result.success:
                            successful += 1
                            q_count = len(multi_result.questions)
                            answers = ", ".join(
                                q.correct_answer for q in multi_result.questions
                            )
                            print(
                                f"  {idx_label}{q_suffix} "
                                f"✓ Basarili — {q_count} soru, "
                                f"Dogru cevaplar: {answers}"
                            )
                            try:
                                created_files = await save_multi_question_output(
                                    result=multi_result,
                                    output_dir=save_dir,
                                    render_png=render_png,
                                )
                                if created_files.get("json"):
                                    print(
                                        f"  {idx_label}{q_suffix} "
                                        f"Kaydedildi: {created_files['json']}"
                                    )
                            except Exception as save_err:
                                print(
                                    f"  {idx_label}{q_suffix} "
                                    f"[WARNING] Kayit hatasi: {save_err}"
                                )
                        else:
                            failed += 1
                            print(
                                f"  {idx_label}{q_suffix} "
                                f"✗ Basarisiz — {multi_result.error}"
                            )
                        # Skip remaining q_num iterations for multi-question
                        break

                    elif qpc > 1 and q_num > 1:
                        # Already handled in q_num == 1
                        break

                    # Standard single-question generation
                    # Pass image_config to workflow only if NOT using post-save illustration
                    # (post-save illustration replaces in-workflow diagram generation)
                    workflow_image_cfg = task.image_config
                    if task.image_config and task.image_config.enabled:
                        # Disable diagram in workflow — illustration will be generated after save
                        workflow_image_cfg = None
                    # Deterministic rotation: hikaye_unsurlari_yoktur must balance
                    # correct answer across {Yer, Zaman, Kisi}. Olay never missing.
                    _target_missing_element = None
                    if "hikaye_unsurlari_yoktur" in task.template_id:
                        _rotation = ["Yer", "Zaman", "Kisi"]
                        _target_missing_element = _rotation[task.template_position % 3]
                    result = await workflow.generate(
                        template_id=task.template_id,
                        topic=task.topic,
                        grade=grade,
                        subject=task.subject,
                        on_progress=on_progress,
                        image_config_override=workflow_image_cfg,
                        visual_context=task.visual_context,
                        target_missing_element=_target_missing_element,
                    )

                    if q_num == 1:
                        results[task.task_idx] = result

                    if result.success:
                        successful += 1
                        print(
                            f"  {idx_label}{q_suffix} "
                            f"✓ Basarili — Dogru cevap: "
                            f"{result.correct_answer}"
                        )
                        # Generate paragraph illustration BEFORE save
                        # so it gets embedded in HTML and saved as question_image.png
                        # Skip if template uses image_description options (gorsel siklar) —
                        # those already have visual options, no context illustration needed
                        effective_img_cfg = task.image_config or getattr(workflow, 'image_config', None)
                        _has_option_images = getattr(result, 'option_images', None)
                        _has_critical_image = getattr(result, 'has_image', False)
                        if result.paragraph and effective_img_cfg and effective_img_cfg.enabled and not _has_option_images and not _has_critical_image:
                            try:
                                from .tools.image_tools import generate_paragraph_illustration
                                illust_result = await generate_paragraph_illustration(
                                    paragraph=result.paragraph,
                                    topic=task.topic,
                                    grade=grade,
                                    cfg=effective_img_cfg,
                                    beceri_etiketi=result.beceri_etiketi,
                                )
                                if illust_result.success and illust_result.png_base64:
                                    result.has_image = True
                                    result.image_base64 = illust_result.png_base64
                                    print(
                                        f"  {idx_label}{q_suffix} "
                                        f"Illustrasyon olusturuldu"
                                    )
                                else:
                                    workflow_logger.warning(
                                        f"Illustration failed for '{task.topic}': "
                                        f"{illust_result.error or 'unknown'}"
                                    )
                            except Exception as illust_err:
                                workflow_logger.warning(
                                    f"Illustration error for '{task.topic}': {illust_err}"
                                )

                        try:
                            created_files = await save_question_output(
                                result=result,
                                output_dir=save_dir,
                                render_png=render_png,
                                question_index=(
                                    q_num - 1
                                    if questions_per_topic > 1
                                    else None
                                ),
                                background_color=_bg_color,
                            )
                            if created_files.get("json"):
                                print(
                                    f"  {idx_label}{q_suffix} "
                                    f"Kaydedildi: {created_files['json']}"
                                )
                                if result.template_id and result.stem_reservation_id:
                                    commit_reserved_stem(
                                        result.template_id,
                                        result.stem_reservation_id,
                                    )
                                    result.stem_reservation_status = "committed"
                                if (
                                    result.used_stem_index is not None
                                    and result.template_id
                                    and os.environ.get("ENABLE_STEM_COMMENT_OUT") == "1"
                                ):
                                    commented = workflow.template_loader.comment_out_used_stem(
                                        result.template_id, result.used_stem_index
                                    )
                                    if commented:
                                        result.commented_stem_index = result.used_stem_index
                                _refresh_saved_result_json(created_files["json"], result)
                        except Exception as save_err:
                            if result.template_id and result.stem_reservation_id:
                                released = release_reserved_stem(
                                    result.template_id,
                                    result.stem_reservation_id,
                                )
                                if released is not None:
                                    result.stem_reservation_status = "released"
                            print(
                                f"  {idx_label}{q_suffix} "
                                f"[WARNING] Kayit hatasi: {save_err}"
                            )
                            workflow_logger.warning(
                                f"Save error for '{task.topic}' "
                                f"Q{q_num}: {save_err}"
                            )
                    else:
                        if result.template_id and result.stem_reservation_id:
                            released = release_reserved_stem(
                                result.template_id,
                                result.stem_reservation_id,
                            )
                            if released is not None:
                                result.stem_reservation_status = "released"
                        failed += 1
                        print(
                            f"  {idx_label}{q_suffix} "
                            f"✗ Basarisiz — {result.error}"
                        )

                except Exception as e:
                    failed += 1
                    print(
                        f"  {idx_label}{q_suffix} ✗ Hata: {e}"
                    )
                    workflow_logger.error(
                        f"Exception for '{task.topic}'"
                        f"{q_suffix}: {e}"
                    )
                    if verbose:
                        import traceback
                        traceback.print_exc()

            completed_count += 1
            async with print_lock:
                print(
                    f"  --- Ilerleme: {completed_count}/{total} "
                    f"konu tamamlandi "
                    f"({successful} basarili, {failed} basarisiz) ---"
                )

    aws = [process_task(t) for t in tasks]
    await asyncio.gather(*aws)

    return successful, failed, results


def _print_batch_summary(
    title: str,
    total: int,
    questions_per_topic: int,
    successful: int,
    failed: int,
    results: list,
    save_dir: Path,
    config: dict | None,
    groups: list[GenerationGroup] | None = None,
    task_list: list | None = None,
):
    """Print batch summary and save summary file."""
    print(f"\n{'=' * 60}")
    print(title)
    print(f"{'=' * 60}")
    total_questions = total * questions_per_topic
    print(f"Toplam konu: {total}")
    if questions_per_topic > 1:
        print(f"Konu basina soru: {questions_per_topic}")
    print(f"Toplam soru: {total_questions}")
    print(f"Basarili: {successful}")
    print(f"Basarisiz: {failed}")
    if total_questions > 0:
        print(f"Basari orani: %{successful * 100 // total_questions}")

    if groups and task_list:
        print(f"\n{'─' * 40}")
        print("Grup bazli sonuclar:")
        for i, group in enumerate(groups, start=1):
            group_results = [
                results[task_idx]
                for task_idx, (tidx, _, g) in enumerate(task_list)
                if g is group and results[task_idx] is not None
            ]
            group_ok = sum(1 for r in group_results if r and r.success)
            group_total = len(group.topic_indices) * questions_per_topic
            print(
                f"  Grup {i} ({group.template_id}): "
                f"{group_ok}/{group_total} basarili"
            )
        print(f"{'─' * 40}")

    valid_results = [r for r in results if r is not None]
    if valid_results:
        summary_path = save_batch_summary(valid_results, save_dir, config)
        print(f"\nOzet dosyasi: {summary_path}")

    print(f"{'=' * 60}\n")


async def run_batch_generation(
    template_id: str,
    topics: list[str],
    grade: int,
    verbose: bool = False,
    default_models: dict[str, str] | None = None,
    required_checks: list[str] | None = None,
    max_fix_iterations: int = 3,
    curriculum_context: "MEBCurriculumContext | None" = None,
    output_dir: Path | None = None,
    render_png: bool = True,
    image_config: ImageGeneratorConfig | None = None,
    config: dict | None = None,
    parallel_workers: int = 1,
    questions_per_topic: int = 1,
    subject: str = "turkce",
) -> int:
    """Run batch question generation for multiple topics."""
    save_dir = output_dir or Path("output")
    log_path = setup_file_logging(save_dir, verbose=verbose)

    total = len(topics)
    print("\n" + "=" * 60)
    print("TOPLU SORU URETICI (BATCH MODE)")
    print("=" * 60)
    print(f"Sablon: {template_id}")
    print(f"Toplam konu: {total}")
    if questions_per_topic > 1:
        print(
            f"Konu basina soru: {questions_per_topic} "
            f"(toplam {total * questions_per_topic} soru)"
        )
    print(f"Sinif: {grade}. sinif")
    if parallel_workers > 1:
        print(f"Paralel isci: {parallel_workers}")
    if default_models:
        models_str = ", ".join(f"{k}={v}" for k, v in default_models.items())
        print(f"Modeller: {models_str}")
    if curriculum_context:
        print(f"MEB PDF: {curriculum_context.pdf_path.name}")
    print(f"Cikti dizini: {save_dir}")
    print(f"Log dosyasi: {log_path}")
    if image_config and image_config.enabled:
        print(f"[IMAGE] Gorsel uretim aktif: model={image_config.model}")
    print("=" * 60 + "\n")

    workflow = GenericQuestionWorkflow(
        curriculum_context=curriculum_context,
        default_models=default_models,
        required_checks=required_checks,
        max_fix_iterations=max_fix_iterations,
        image_config=image_config,
    )

    batch_tasks = [
        BatchTask(task_idx=i, topic=topic, template_id=template_id, subject=subject)
        for i, topic in enumerate(topics)
    ]

    successful, failed, results = await _run_batch_core(
        tasks=batch_tasks,
        workflow=workflow,
        grade=grade,
        save_dir=save_dir,
        render_png=render_png,
        verbose=verbose,
        parallel_workers=parallel_workers,
        questions_per_topic=questions_per_topic,
        config=config,
    )

    _print_batch_summary(
        "TOPLU URETIM SONUCLARI", total, questions_per_topic,
        successful, failed, results, save_dir, config,
    )

    return 0 if failed == 0 else 1


async def run_planned_generation(
    groups: list[GenerationGroup],
    all_topics: list[str],
    grade: int,
    subject: str = "turkce",
    verbose: bool = False,
    default_models: dict[str, str] | None = None,
    required_checks: list[str] | None = None,
    max_fix_iterations: int = 3,
    curriculum_context: "MEBCurriculumContext | None" = None,
    output_dir: Path | None = None,
    render_png: bool = True,
    base_image_config: ImageGeneratorConfig | None = None,
    image_gen_raw: dict | None = None,
    config: dict | None = None,
    parallel_workers: int = 1,
    questions_per_topic: int = 1,
) -> int:
    """Run planned batch generation with different templates per group."""
    save_dir = output_dir or Path("output")
    log_path = setup_file_logging(save_dir, verbose=verbose)
    image_gen_raw = image_gen_raw or {}

    # Build flat task list (carries 0-based position within its group for rotation logic)
    task_list: list[tuple[int, str, GenerationGroup, int]] = []
    for group in groups:
        for pos, idx in enumerate(group.topic_indices):
            task_list.append((idx, all_topics[idx], group, pos))

    total = len(task_list)

    # Print header
    print("\n" + "=" * 60)
    print("PLANLI TOPLU SORU URETICI (PLANNED BATCH MODE)")
    print("=" * 60)
    print(f"Toplam konu: {total} ({len(groups)} grup)")
    if questions_per_topic > 1:
        print(
            f"Konu basina soru sayisi: {questions_per_topic} "
            f"(toplam {total * questions_per_topic} soru)"
        )
    else:
        print(f"Toplam soru: {total}")

    for i, group in enumerate(groups, start=1):
        indices_1 = [idx + 1 for idx in group.topic_indices]
        if len(indices_1) <= 6:
            range_display = ", ".join(str(x) for x in indices_1)
        else:
            range_display = f"{indices_1[0]}-{indices_1[-1]}"
        img_status = "evet" if group.image_override is True else "hayir"
        print(
            f"  Grup {i}: {group.template_id:30} "
            f"→ konular {range_display:12} "
            f"(gorsel: {img_status})"
        )

    print(f"Sinif: {grade}. sinif")
    if parallel_workers > 1:
        print(f"Paralel isci: {parallel_workers}")
    if default_models:
        models_str = ", ".join(f"{k}={v}" for k, v in default_models.items())
        print(f"Modeller: {models_str}")
    if curriculum_context:
        print(f"MEB PDF: {curriculum_context.pdf_path.name}")
    print(f"Cikti dizini: {save_dir}")
    print(f"Log dosyasi: {log_path}")
    print("=" * 60 + "\n")

    workflow = GenericQuestionWorkflow(
        curriculum_context=curriculum_context,
        default_models=default_models,
        required_checks=required_checks,
        max_fix_iterations=max_fix_iterations,
        image_config=base_image_config,
    )

    batch_tasks = [
        BatchTask(
            task_idx=task_idx,
            topic=topic,
            template_id=group.template_id,
            image_config=_resolve_image_config(
                base_image_config, group.image_override, image_gen_raw
            ),
            subject=subject,
            skip_existing=True,
            has_generation_plan=True,
            visual_context=group.visual_context,
            template_position=pos,
        )
        for task_idx, (_, topic, group, pos) in enumerate(task_list)
    ]

    successful, failed, results = await _run_batch_core(
        tasks=batch_tasks,
        workflow=workflow,
        grade=grade,
        save_dir=save_dir,
        render_png=render_png,
        verbose=verbose,
        parallel_workers=parallel_workers,
        questions_per_topic=questions_per_topic,
        config=config,
    )

    _print_batch_summary(
        "PLANLI URETIM SONUCLARI", total, questions_per_topic,
        successful, failed, results, save_dir, config,
        groups=groups, task_list=task_list,
    )

    # Cost summary
    from .client import get_cost_tracker
    tracker = get_cost_tracker()
    tracker.print_summary()
    # Save cost_summary.json
    try:
        import json as _json
        from datetime import datetime as _dt
        cost_path = save_dir / f"cost_{_dt.now().strftime('%Y%m%d_%H%M%S')}.json"
        cost_path.write_text(_json.dumps(tracker.estimate_cost(), indent=2, ensure_ascii=False))
        print(f"Maliyet raporu: {cost_path}")
    except Exception as e:
        print(f"Maliyet raporu yazılamadı: {e}")

    return 0 if failed == 0 else 1


async def run_context_batch_generation(
    plan: list[dict],
    all_topics: list[str],
    grade: int,
    subject: str = "turkce",
    verbose: bool = False,
    default_models: dict[str, str] | None = None,
    required_checks: list[str] | None = None,
    max_fix_iterations: int = 3,
    curriculum_context: "MEBCurriculumContext | None" = None,
    output_dir: Path | None = None,
    render_png: bool = True,
    config: dict | None = None,
    parallel_workers: int = 1,
    image_config: "ImageGeneratorConfig | None" = None,
) -> int:
    """Run context-based batch generation from a context_generation_plan.

    Each plan entry has: topics (range string), template (context template ID).
    """
    save_dir = output_dir or Path("output")
    log_path = setup_file_logging(save_dir, verbose=verbose)

    # Build flat task list: (topic_idx, topic_str, template_id)
    task_list: list[tuple[int, str, str]] = []
    for entry in plan:
        template_id = entry.get("template")
        topics_str = str(entry.get("topics", ""))

        try:
            indices = parse_topic_ranges(topics_str, len(all_topics))
        except ValueError as e:
            print(f"Hata: Gecersiz konu araligi: {e}")
            return 1

        for idx in indices:
            task_list.append((idx, all_topics[idx], template_id))

    total = len(task_list)

    # Print header
    print("\n" + "=" * 60)
    print("BAGLAM TEMELLI TOPLU SORU URETICI")
    print("=" * 60)
    print(f"Toplam grup: {total}")
    for entry in plan:
        t_id = entry.get("template", "?")
        t_topics = entry.get("topics", "?")
        print(f"  {t_id}: konular {t_topics}")
    print(f"Sinif: {grade}. sinif")
    if default_models:
        models_str = ", ".join(f"{k}={v}" for k, v in default_models.items())
        print(f"Modeller: {models_str}")
    if curriculum_context:
        print(f"MEB PDF: {curriculum_context.pdf_path.name}")
    print(f"Cikti dizini: {save_dir}")
    print(f"Log dosyasi: {log_path}")
    print("=" * 60 + "\n")

    workflow = GenericQuestionWorkflow(
        curriculum_context=curriculum_context,
        default_models=default_models,
        required_checks=required_checks,
        max_fix_iterations=max_fix_iterations,
        image_config=image_config,
    )

    workflow_logger = logging.getLogger("agentic.workflow")
    successful = 0
    failed = 0

    semaphore = asyncio.Semaphore(parallel_workers)

    async def process_group(task_idx: int, topic: str, template_id: str):
        nonlocal successful, failed

        async with semaphore:
            idx_label = f"[{task_idx + 1}/{total}]"
            print(f"\n{'─' * 60}")
            print(f"{idx_label} Konu: {topic}")
            print(f"  Sablon: {template_id}")
            print(f"{'─' * 60}")

            # Check if already exists
            safe_topic = _sanitize_filename(topic)
            prefix = _get_section_prefix(template_id)
            subdir = _get_section_subdir(template_id)
            _base = save_dir / subdir if subdir else save_dir
            group_dir = _base / f"{prefix}{safe_topic}_{template_id}_group"
            if (group_dir / "group.json").exists():
                print(f"  {idx_label} ⏭ Atlaniyor (mevcut)")
                successful += 1
                return

            def on_progress(msg: str, _idx=idx_label):
                print(f"  {_idx} {msg}")
                workflow_logger.info(f"[{topic}] {msg}")

            try:
                # Load template to get background_color
                _ctx_tmpl = workflow.template_loader.load(template_id)
                _ctx_bg = getattr(_ctx_tmpl.format.paragraph, "background_color", None)

                group_result = await workflow.generate_context_group(
                    template_id=template_id,
                    topic=topic,
                    grade=grade,
                    subject=subject,
                    on_progress=on_progress,
                )

                if group_result.success:
                    successful += 1
                    q_count = len([q for q in group_result.questions if q.success])
                    answers = [q.correct_answer for q in group_result.questions if q.success]
                    print(f"  {idx_label} ✓ Basarili — {q_count} soru, cevaplar: {','.join(answers)}")

                    try:
                        created_files = await save_context_group_output(
                            result=group_result,
                            output_dir=save_dir,
                            render_png=render_png,
                            background_color=_ctx_bg,
                        )
                        if created_files.get("json"):
                            print(f"  {idx_label} Kaydedildi: {created_files['json']}")
                    except Exception as save_err:
                        print(f"  {idx_label} [WARNING] Kayit hatasi: {save_err}")
                else:
                    failed += 1
                    print(f"  {idx_label} ✗ Basarisiz — {group_result.error}")

            except Exception as e:
                failed += 1
                print(f"  {idx_label} ✗ Hata: {e}")
                workflow_logger.error(f"Exception for '{topic}': {e}")

    aws = [
        process_group(i, topic, template_id)
        for i, (_, topic, template_id) in enumerate(task_list)
    ]
    await asyncio.gather(*aws)

    # Print summary
    print(f"\n{'=' * 60}")
    print("BAGLAM TEMELLI URETIM SONUCLARI")
    print(f"{'=' * 60}")
    print(f"Toplam grup: {total}")
    print(f"Basarili: {successful}")
    print(f"Basarisiz: {failed}")
    if total > 0:
        print(f"Basari orani: %{successful * 100 // total}")
    print(f"{'=' * 60}\n")

    # Cost summary
    from .client import get_cost_tracker
    tracker = get_cost_tracker()
    tracker.print_summary()
    try:
        import json as _json
        from datetime import datetime as _dt
        cost_path = save_dir / f"cost_{_dt.now().strftime('%Y%m%d_%H%M%S')}.json"
        cost_path.write_text(_json.dumps(tracker.estimate_cost(), indent=2, ensure_ascii=False))
        print(f"Maliyet raporu: {cost_path}")
    except Exception as e:
        print(f"Maliyet raporu yazılamadı: {e}")

    return 0 if failed == 0 else 1


def setup_file_logging(output_dir: Path, verbose: bool = False) -> Path:
    """
    Set up file logging for detailed debug output.

    Creates a timestamped log file in the output directory.
    Returns the path to the log file.
    """
    from datetime import datetime

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = output_dir / f"generation_{timestamp}.log"

    # Create formatters
    file_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:\n%(message)s\n",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )

    # Get root logger for agentic
    agentic_logger = logging.getLogger("agentic")
    agentic_logger.setLevel(logging.DEBUG)  # Capture all levels

    # File handler - always detailed
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(file_formatter)
    agentic_logger.addHandler(file_handler)

    # Console handler - based on verbose flag
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console_handler.setFormatter(console_formatter)
    agentic_logger.addHandler(console_handler)

    # Prevent propagation to root logger
    agentic_logger.propagate = False

    return log_path


def _handle_reset_stem_usage() -> int:
    """Handle --reset-stem-usage command."""
    from .templates import reset_stem_registry
    reset_stem_registry()
    print("✓ Stem usage registry cleared.")
    registry_path = Path.home() / '.cache' / 'agentic' / 'stem_usage.json'
    print(f"  Registry location: {registry_path}")
    return 0


def _handle_show_stem_stats() -> int:
    """Handle --show-stem-stats command."""
    from .templates import get_stem_statistics
    stats = get_stem_statistics()

    if not stats:
        print("\nNo stem usage data found.")
        print("Generate some questions first, then check stats again.")
        return 0

    print("\n" + "=" * 80)
    print("STEM USAGE STATISTICS")
    print("=" * 80)
    header = (
        f"\n{'Template':<25} {'Total':>6} {'Min':>5} "
        f"{'Max':>5} {'Avg':>6} {'Unused':>7}"
    )
    print(header)
    print("-" * 80)

    for template_id, data in sorted(stats.items()):
        print(
            f"{template_id:<25} "
            f"{data['total']:>6} "
            f"{data['min']:>5} "
            f"{data['max']:>5} "
            f"{data['avg']:>6.1f} "
            f"{data['unused']:>7}"
        )

    print("-" * 80)
    registry_path = Path.home() / '.cache' / 'agentic' / 'stem_usage.json'
    print(f"\nRegistry location: {registry_path}")
    print(
        "\nNote: 'Unused' shows stems with 0 uses. "
        "Balanced selection prioritizes these.\n"
    )
    return 0


async def _handle_extract_question_types(args) -> int:
    """Handle --extract-question-types command."""
    pdf_path = Path(args.extract_question_types)
    if not pdf_path.exists():
        print(f"Hata: PDF bulunamadı: {pdf_path}")
        return 1

    out_path = Path(args.extract_out)
    model = str(args.extract_model)

    print(f"PDF okunuyor: {pdf_path}")
    print(f"Model: {model}")
    print(f"Çıktı: {out_path}")

    result = await extract_question_types_from_pdf(
        pdf_path=pdf_path,
        output_json_path=out_path,
        model=model,
    )

    print("\nBulunan soru kökü kalıpları (benzersiz):\n")
    for stem in result.stems:
        pages = (
            ", ".join(str(p) for p in stem.example_pages[:3])
            if stem.example_pages else "-"
        )
        count = (
            str(stem.count_estimate)
            if stem.count_estimate is not None else "-"
        )
        print(f"- [{stem.category}] {stem.stem}  (ör: s.{pages}, ~{count})")

    print(f"\n✓ Kaydedildi: {out_path}")
    return 0


async def main_async():
    """Async main entry point."""
    args = parse_args()

    # Basic logging setup (will be enhanced if running generation)
    if args.verbose:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        logging.getLogger("agentic").setLevel(logging.DEBUG)
        print("[DEBUG] Verbose logging enabled")
    else:
        logging.basicConfig(level=logging.WARNING)

    # Handle simple commands
    if args.list_templates:
        list_templates()
        return 0

    if args.reset_stem_usage:
        return _handle_reset_stem_usage()

    if args.show_stem_stats:
        return _handle_show_stem_stats()

    if args.extract_question_types:
        return await _handle_extract_question_types(args)

    # Load config file if provided
    config = {}
    if args.config:
        if not args.config.exists():
            print(f"Hata: Config dosyası bulunamadı: {args.config}")
            return 1
        try:
            config = load_template_config(args.config)
            print(f"[CONFIG] Loaded: {args.config}")
        except Exception as e:
            print(f"Hata: Config yüklenemedi: {e}")
            return 1

    # Get template/topic/grade/subject from CLI args or config file
    template_id = args.template or config.get("template")
    topic = args.topic or config.get("topic")
    grade = args.grade if args.grade != 5 else config.get("grade", 5)  # 5 is default
    # Normalize subject: "Fen Bilimleri" → "fen_bilimleri" for matching with required_subjects
    subject_raw = config.get("subject", "turkce")
    subject = subject_raw.lower().replace(" ", "_") if subject_raw else "turkce"

    # Check for batch mode: topics_file in config (CLI --topic overrides to single mode)
    topics_file = config.get("topics_file") if not args.topic else None

    # Check for generation_plan in config
    generation_plan = config.get("generation_plan") if not args.topic else None

    # Check for context_generation_plan in config
    context_generation_plan = config.get("context_generation_plan") if not args.topic else None

    # Handle template-driven generation (primary mode)
    # generation_plan / context_generation_plan also trigger this path (template_id optional when plan is present)
    if template_id or generation_plan or context_generation_plan:
        if not topic and not topics_file and not generation_plan and not context_generation_plan:
            print("Hata: --topic parametresi, config'de 'topic' veya 'topics_file' alanı gerekli")
            print("Ornek: python -m legacy_app.kadir_hoca.agentic --template ana_fikir --topic \"OYUN DUNYASI / Okuma\"")
            print("Veya: template_config.yaml dosyasına 'topic: ...' veya 'topics_file: ...' ekleyin")
            return 1

        if (generation_plan or context_generation_plan) and not topics_file:
            print("Hata: generation_plan kullanildiginda 'topics_file' alani zorunludur")
            return 1

        # Build default_models from config, with CLI override
        models_config = config.get("models", {})
        if args.model:
            # CLI --model overrides all
            default_models = {
                "paragraph_writer": args.model,
                "question_crafter": args.model,
                "validator": args.model,
            }
        else:
            default_models = {
                "paragraph_writer": models_config.get("paragraph_writer", "gemini-3-flash-preview"),
                "question_crafter": models_config.get("question_crafter", "gemini-3-flash-preview"),
                "validator": models_config.get("validator", "gemini-3-flash-preview"),
            }

        # Get validation settings from config, with CLI overrides
        validation_config = config.get("validation", {})
        if args.checks:
            required_checks = [c.strip() for c in args.checks.split(",")]
        else:
            required_checks = validation_config.get("required_checks", None)

        if args.max_fix_iterations is not None:
            max_fix_iterations = args.max_fix_iterations
        else:
            max_fix_iterations = validation_config.get("max_fix_iterations", 3)

        # Build curriculum context if grounding is configured
        curriculum_context = None
        grounding_config = config.get("grounding", {})
        if grounding_config.get("enabled", False) and grounding_config.get("pdf_path"):
            pdf_path = Path(grounding_config["pdf_path"])
            if pdf_path.exists():
                cache_ttl = grounding_config.get("cache_ttl", 3600)
                curriculum_context = MEBCurriculumContext(
                    pdf_path=pdf_path,
                    cache_config=CacheConfig(ttl_seconds=cache_ttl),
                )
                print(f"[GROUNDING] MEB PDF: {pdf_path.name}")

                # Optional data PDFs (topic-specific)
                for dp_str in grounding_config.get("data_pdf_paths", []):
                    dp = Path(dp_str)
                    if dp.exists():
                        curriculum_context.data_pdf_paths.append(dp)
                        print(f"[GROUNDING] Data PDF: {dp.name}")
                    else:
                        print(f"[WARNING] Data PDF not found: {dp}")
            else:
                print(f"[WARNING] Grounding PDF not found: {pdf_path}")

        # Get output directory from config or use default
        output_config = config.get("output", {})
        output_dir = Path(output_config.get("dir", "output"))

        # Build image generation config if present
        image_config = None
        image_gen_config = config.get("image_generation", {})
        if image_gen_config.get("enabled", False):
            image_config = ImageGeneratorConfig(
                enabled=True,
                model=image_gen_config.get("model", "gemini-3-pro-image-preview"),
                judge_model=image_gen_config.get("judge_model", "gemini-3.1-pro-preview"),
                temperature=image_gen_config.get("temperature", 0.2),
                max_retries=image_gen_config.get("max_retries", 2),
                max_judge_iterations=image_gen_config.get("max_judge_iterations", 3),
                required_subjects=image_gen_config.get("required_subjects", []),
            )
            print(f"[IMAGE] Gorsel uretim aktif: model={image_config.model}, judge={image_config.judge_model}")

        # Batch mode: topics_file is set
        if topics_file:
            # Path already resolved by load_template_config()
            topics_path = Path(topics_file)

            if not topics_path.exists():
                print(f"Hata: Topics dosyası bulunamadı: {topics_path}")
                return 1

            # "#" ile baslayan yorumlu satirlari atla (ornek: "# KULLANILDI: ...")
            topics = [
                line.strip()
                for line in topics_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]

            if not topics:
                print(f"Hata: Topics dosyası boş: {topics_path}")
                return 1

            print(f"[BATCH] {len(topics)} konu yüklendi: {topics_path.name}")

            # ── Shuffle topics for random selection ──
            shuffle_topics = config.get("shuffle_topics", False)
            if shuffle_topics:
                random.shuffle(topics)
                print(f"[BATCH] Konular karistirildi (shuffle_topics: true)")

            parallel_workers = args.parallel or config.get("parallel_workers", 1)
            questions_per_topic = config.get("questions_per_topic", 1)

            # ── Context-based generation: context_generation_plan present ──
            if context_generation_plan:
                return await run_context_batch_generation(
                    plan=context_generation_plan,
                    all_topics=topics,
                    grade=grade,
                    subject=subject,
                    verbose=args.verbose,
                    default_models=default_models,
                    required_checks=required_checks,
                    max_fix_iterations=max_fix_iterations,
                    curriculum_context=curriculum_context,
                    output_dir=output_dir,
                    render_png=not args.no_png,
                    config=config,
                    parallel_workers=parallel_workers,
                    image_config=image_config,
                )

            # ── Planned generation: generation_plan present ──
            if generation_plan:
                try:
                    groups = parse_generation_plan(generation_plan, len(topics))
                except ValueError as e:
                    print(f"Hata: generation_plan gecersiz — {e}")
                    return 1

                # Validate all template IDs exist
                loader = TemplateLoader()
                available = loader.list_templates()
                for group in groups:
                    if group.template_id not in available:
                        print(
                            f"Hata: Gecersiz sablon '{group.template_id}' "
                            f"(mevcut sablonlar: {', '.join(available)})"
                        )
                        return 1

                return await run_planned_generation(
                    groups=groups,
                    all_topics=topics,
                    grade=grade,
                    subject=subject,
                    verbose=args.verbose,
                    default_models=default_models,
                    required_checks=required_checks,
                    max_fix_iterations=max_fix_iterations,
                    curriculum_context=curriculum_context,
                    output_dir=output_dir,
                    render_png=not args.no_png,
                    base_image_config=image_config,
                    image_gen_raw=config.get("image_generation", {}),
                    config=config,
                    parallel_workers=parallel_workers,
                    questions_per_topic=questions_per_topic,
                )

            # ── Regular batch: single template for all topics ──
            if not template_id:
                print("Hata: 'template' alani gerekli (veya generation_plan kullanin)")
                return 1

            return await run_batch_generation(
                template_id=template_id,
                topics=topics,
                grade=grade,
                verbose=args.verbose,
                default_models=default_models,
                required_checks=required_checks,
                max_fix_iterations=max_fix_iterations,
                curriculum_context=curriculum_context,
                output_dir=output_dir,
                render_png=not args.no_png,
                image_config=image_config,
                config=config,
                parallel_workers=parallel_workers,
                questions_per_topic=questions_per_topic,
                subject=subject,
            )

        # Single topic mode (existing behavior)
        return await run_template_generation(
            template_id=template_id,
            topic=topic,
            grade=grade,
            verbose=args.verbose,
            default_models=default_models,
            required_checks=required_checks,
            max_fix_iterations=max_fix_iterations,
            curriculum_context=curriculum_context,
            output_dir=output_dir,
            render_png=not args.no_png,
            image_config=image_config,
            subject=subject,
        )

    # No action specified - show help
    print("Hata: Bir işlem belirtilmedi.")
    print("\nKullanım:")
    print("  python -m legacy_app.kadir_hoca.agentic -c template_config.yaml")
    print("  python -m legacy_app.kadir_hoca.agentic --list-templates")
    print("  python -m legacy_app.kadir_hoca.agentic --extract-question-types <pdf>")
    print("\nYardım için: python -m legacy_app.kadir_hoca.agentic --help")
    return 1


def main():
    """Main entry point."""
    try:
        exit_code = asyncio.run(main_async())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nİptal edildi.")
        sys.exit(130)


if __name__ == "__main__":
    main()
