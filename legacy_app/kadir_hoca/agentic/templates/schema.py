"""
Template Schema - Pydantic models for template-driven question generation.

Template content (YAML values) are in Turkish because they go to the LLM.
Python code uses standard English naming for the schema structure.

The new template system has embedded format configuration:
- format is an object (FormatConfig) containing paragraph, stem, options specs
- celdirici_stratejileri has rich examples with ornekler list
- dogru_cevap has kurallar and ornekler
- Optional konu_kaynagi for topic hierarchy configuration
"""

from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel, Field, model_validator

__all__ = [
    # Format config (embedded in template)
    "FormatConfig",
    "FormatParagraphConfig",
    "FormatPremisesConfig",
    "FormatStemConfig",
    "FormatOptionsConfig",
    "FormatTopicInStemConfig",
    "FormatTitlesInStemConfig",
    # Context config (context-based questions)
    "ContextQuestionSlot",
    "ContextGenerationConfig",
    "ContextConfig",
    # Question template schema
    "QuestionTemplate",
    "TemplateMeta",
    "CorrectAnswerConfig",
    "CorrectAnswerExample",
    "DistractorStrategy",
    "DistractorExample",
    "ModelConfig",
    # Topic source config
    "TopicSourceConfig",
    "TopicHierarchy",
    "TopicHierarchyLevel",
    # Beceri config
    "BeceriConfig",
]


# ============================================================================
# FORMAT CONFIG (EMBEDDED IN TEMPLATE)
# ============================================================================


class FormatParagraphConfig(BaseModel):
    """Paragraph format configuration."""

    required: bool = Field(default=True, description="Whether paragraph is required")
    count: int = Field(default=1, description="Number of paragraphs (2 for multi-text comparison)")
    labels: list[str] | None = Field(
        default=None,
        description="Paragraph labels (e.g., ['1. Metin', '2. Metin'])",
    )
    numbered_sentences: bool = Field(
        default=False,
        description="Whether to number sentences with Roman numerals (I, II, III, IV)",
    )
    word_count_min: int = Field(default=55, description="Minimum word count")
    word_count_max: int = Field(default=90, description="Maximum word count")
    sentence_count_min: int = Field(default=4, description="Minimum sentence count")
    sentence_count_max: int = Field(default=7, description="Maximum sentence count")
    stil: str = Field(default="bilgilendirici", description="Paragraph style")
    kurallar: list[str] = Field(
        default_factory=list,
        description="List of paragraph generation rules (Turkish)",
    )
    background_color: str | None = Field(
        default=None,
        description=(
            "CSS background color for the paragraph div (e.g. '#e8f8e8' for green, "
            "'#f8f0e0' for yellow). When set, paragraph is rendered with colored "
            "background, rounded corners and border."
        ),
    )


class FormatStemConfig(BaseModel):
    """Stem format configuration."""

    required: bool = Field(default=True, description="Whether stem is required")
    description: str = Field(default="", description="Description of stem format")
    pattern: str | None = Field(
        default=None,
        description="Pattern for inverse templates (e.g., '{topic} konulu...')",
    )


class FormatOptionsConfig(BaseModel):
    """Options format configuration."""

    count: int = Field(default=4, description="Number of options")
    labels: list[str] = Field(
        default=["A", "B", "C", "D"],
        description="Option labels",
    )
    word_count_min: int = Field(default=2, description="Min words per option")
    word_count_max: int = Field(default=6, description="Max words per option")
    style: str = Field(
        default="topic_phrase",
        description="Option style (topic_phrase, headline_title, complete_sentence, mini_paragraph, image_description)",
    )
    correct_count: int = Field(default=1, description="Number of correct options")
    # For inverse templates
    type: str | None = Field(
        default=None,
        description="Option type for inverse (e.g., 'mini_paragraph')",
    )
    sentence_count_min: int | None = Field(
        default=None,
        description="Min sentences for mini_paragraph options",
    )
    sentence_count_max: int | None = Field(
        default=None,
        description="Max sentences for mini_paragraph options",
    )
    correct_type: str = Field(
        default="matches",
        description="Logic type: 'matches' (standard) or 'does_not_belong' (inverse)",
    )
    # For roman numeral combination options
    preserve_order: bool = Field(
        default=False,
        description="If True, skip shuffle to preserve option order (for roman_numeral_combination style)",
    )
    layout: str | None = Field(
        default=None,
        description="Option layout: 'two_column' for 2x2 grid (A-B / C-D), None for vertical",
    )
    # For image option templates (gorsel_siklar_*)
    image_style: str | None = Field(
        default=None,
        description="Image generation style: 'photo', 'chart', 'table', 'mockup'. Only used when style='image_description'.",
    )


class FormatTopicInStemConfig(BaseModel):
    """Configuration for topic embedded in stem (inverse templates)."""

    required: bool = Field(default=True, description="Whether topic in stem is required")
    description: str = Field(default="", description="Description")


class FormatTitlesInStemConfig(BaseModel):
    """Configuration for multiple titles embedded in stem (inverse title templates)."""

    required: bool = Field(default=True, description="Whether titles in stem is required")
    count: int = Field(default=3, description="Number of titles to include")
    description: str = Field(default="", description="Description")


class FormatPremisesConfig(BaseModel):
    """Configuration for premises (öncüller) displayed before the question.

    Used by templates like hikaye_unsurlari_reverse where structured
    premises (Yer, Zaman, Kişiler, Olay) are given and the student
    must find the matching paragraph.
    """

    required: bool = Field(default=True, description="Whether premises are required")
    structure: list[str] = Field(
        default_factory=list,
        description="Premise structure templates (e.g., ['Yer: {location}', 'Zaman: {time}'])",
    )


class FormatConfig(BaseModel):
    """
    Complete format configuration (replaces format string).

    This is now embedded in each template YAML file, not loaded separately.

    The html_template field allows templates to specify their own HTML structure,
    enabling the LLM to generate HTML directly instead of JSON that gets converted.
    """

    type: str = Field(
        ...,
        description="Format type (e.g., 'llm_generated_html', 'single_paragraph_mc')",
    )
    description: str = Field(default="", description="Format description")
    paragraph: FormatParagraphConfig = Field(
        default_factory=FormatParagraphConfig,
        description="Paragraph configuration",
    )
    stem: FormatStemConfig = Field(
        default_factory=FormatStemConfig,
        description="Question stem configuration",
    )
    options: FormatOptionsConfig = Field(
        default_factory=FormatOptionsConfig,
        description="Options configuration",
    )
    # For inverse templates
    topic_in_stem: FormatTopicInStemConfig | None = Field(
        default=None,
        description="Topic embedded in stem (inverse topic templates)",
    )
    titles_in_stem: FormatTitlesInStemConfig | None = Field(
        default=None,
        description="Titles embedded in stem (inverse title templates)",
    )
    # For premises-based templates (e.g., hikaye_unsurlari_reverse)
    premises: FormatPremisesConfig | None = Field(
        default=None,
        description="Premises configuration for reverse/matching templates",
    )
    # HTML template for LLM-generated HTML
    html_template: str | None = Field(
        default=None,
        description="HTML template with {placeholders} for LLM to fill. When set, LLM generates HTML directly.",
    )
    # Multi-question support
    questions_per_context: int = Field(
        default=1,
        description="Number of questions per context/paragraph (1-3). Default 1 for existing templates.",
    )


# ============================================================================
# CONTEXT CONFIGURATION (Context-Based Questions)
# ============================================================================


class ContextQuestionSlot(BaseModel):
    """A sub-question slot definition within a context group."""

    slot: int = Field(..., description="1-indexed slot number")
    type: str = Field(..., description="Sub-question type (e.g., problem_cozme, yorum_hareket)")
    soru_kokleri: list[str] = Field(
        default_factory=list,
        description="Stem variations for this slot",
    )
    options_style: str = Field(
        default="complete_sentence",
        description="Option style for this slot",
    )
    image_style: str | None = Field(
        default=None,
        description="Image generation style for option images: 'table', 'chart', 'photo'. Only used when options_style='image_description'.",
    )
    word_count_min: int = Field(default=2, description="Min words per option")
    word_count_max: int = Field(default=15, description="Max words per option")
    options_format_rule: str | None = Field(
        default=None,
        description="Optional format rule for options (e.g., vertical character listing with <br>)",
    )
    beceri: dict[str, Any] | None = Field(
        default=None,
        description="Beceri etiketi: {katman, bilesenler, surec_bileseni}",
    )
    slot_rules: list[str] = Field(
        default_factory=list,
        description="Slot-specific rules that apply only to this question slot",
    )
    # Slot-level correct-answer rules (richer than global dogru_cevap)
    dogru_cevap_kurallari: list[str] = Field(
        default_factory=list,
        description="Slot-specific correct-answer rules (appended to prompt's correct_section)",
    )
    # Slot-level distractor strategies (richer than global celdirici_stratejileri)
    celdirici_stratejileri: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Slot-specific distractor strategies (override template-level for this slot)",
    )
    # Slot-level options override (count, labels, word bounds)
    options_override: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional overrides for options at this slot: "
            "{count, labels, word_count_min, word_count_max}. "
            "If provided, wins over template-level format.options."
        ),
    )


class ContextGenerationConfig(BaseModel):
    """Context text generation configuration."""

    word_count_min: int = Field(default=80, description="Min word count for context")
    word_count_max: int = Field(default=200, description="Max word count for context")
    structure: list[str] = Field(
        default_factory=list,
        description="Structure instructions for context generation",
    )
    kurallar: list[str] = Field(
        default_factory=list,
        description="Generation rules for context text",
    )
    image_type: str | None = Field(
        default=None,
        description="AI image type: infografik, poster, afis. None = no image generation.",
    )
    visual_format: str | None = Field(
        default=None,
        description="Visual format for post-processing: feature_table, data_table, bar_chart, grouped_bar_chart, newspaper. None = default.",
    )


class ContextConfig(BaseModel):
    """Context group configuration — only in context templates."""

    type: str = Field(..., description="Context type (senaryo_tablo, coklu_gorus, etc.)")
    question_count: int = Field(..., description="Number of sub-questions in group")
    question_count_min: int = Field(default=1, description="Minimum sub-questions")
    question_count_max: int = Field(default=5, description="Maximum sub-questions")
    generation: ContextGenerationConfig = Field(
        default_factory=ContextGenerationConfig,
        description="Context text generation config",
    )
    questions: list[ContextQuestionSlot] = Field(
        default_factory=list,
        description="Sub-question slot definitions",
    )


# ============================================================================
# MODEL CONFIGURATION
# ============================================================================


class ModelConfig(BaseModel):
    """
    Model configuration for template-level model overrides.

    Allows templates to specify which models to use for each agent.
    If not specified, falls back to config defaults or hardcoded fallback.
    """

    paragraph_writer: str | None = Field(
        default=None,
        description="Model for paragraph generation",
    )
    question_crafter: str | None = Field(
        default=None,
        description="Model for question generation",
    )
    validator: str | None = Field(
        default=None,
        description="Model for validation checks",
    )


# ============================================================================
# TEMPLATE METADATA
# ============================================================================


class TemplateMeta(BaseModel):
    """Extended metadata about a question template."""

    id: str = Field(..., description="Unique template identifier")
    ad: str = Field(..., description="Turkish display name")
    sinif_seviyesi: int = Field(default=5, description="Target grade level")
    aciklama: str = Field(default="", description="Template description (Turkish)")
    kaynak: str = Field(default="", description="Source PDF reference")
    frequency: str = Field(default="", description="Usage frequency note")


# ============================================================================
# CORRECT ANSWER CONFIGURATION
# ============================================================================


class CorrectAnswerExample(BaseModel):
    """Example for correct answer demonstration."""

    # Standard format
    paragraf: str | None = Field(default=None, description="Example paragraph")
    dogru: str | None = Field(default=None, description="Correct answer text")
    # Inverse format
    konu: str | None = Field(default=None, description="Topic for inverse")
    dogru_cevap: str | None = Field(default=None, description="Correct answer (inverse)")
    neden: str | None = Field(default=None, description="Why this is correct")


class CorrectAnswerConfig(BaseModel):
    """Configuration for correct answer generation with examples."""

    tanim: str = Field(
        ...,
        description="Definition of what makes a correct answer (Turkish)",
    )
    mantik: str | None = Field(
        default=None,
        description="Logic note (e.g., 'INVERSE' for inverse templates)",
    )
    kurallar: list[str] = Field(
        default_factory=list,
        description="Rules for correct answer (Turkish)",
    )
    ornekler: list[CorrectAnswerExample] = Field(
        default_factory=list,
        description="Examples demonstrating correct answers",
    )


# ============================================================================
# DISTRACTOR STRATEGIES
# ============================================================================


class DistractorExample(BaseModel):
    """Single distractor example with context."""

    # Standard format fields
    paragraf_konusu: str | None = Field(
        default=None, description="Paragraph topic for context"
    )
    celdirici: str | None = Field(default=None, description="Distractor text")
    neden_yanlis: str | None = Field(
        default=None, description="Why this is wrong"
    )
    # Inverse format fields
    konu: str | None = Field(default=None, description="Topic for inverse")
    paragraf: str | None = Field(default=None, description="Mini-paragraph text")
    neden_dogru: str | None = Field(
        default=None, description="Why this is correct (inverse)"
    )


class DistractorStrategy(BaseModel):
    """Distractor strategy with rich examples."""

    ad: str = Field(
        ...,
        description="Strategy name in Turkish (e.g., 'detay_tuzagi')",
    )
    aciklama: str = Field(
        ...,
        description="Strategy description in Turkish",
    )
    nasil_olusturulur: str = Field(
        default="",
        description="How to create this type of distractor",
    )
    kacinilacaklar: str = Field(
        default="",
        description="Things to avoid when using this strategy",
    )
    tip: str | None = Field(
        default=None,
        description="Type for inverse: 'distractor' or 'correct_answer'",
    )
    kategori: str | None = Field(
        default=None,
        description=(
            "Strategy category (semantic, content, scope, linguistic, "
            "cognitive, logical, temporal, inference, inverse_fitting, "
            "application, completeness, surface)"
        ),
    )
    bilissel_hata: str | None = Field(
        default=None,
        description=(
            "Cognitive error type this strategy targets: "
            "yuzeysel_okuma, yanlis_cikarim, eksik_analiz, "
            "asiri_genelleme, kavram_karisikligi"
        ),
    )
    rol: str | None = Field(
        default=None,
        description="Role for inverse templates: 'dogru_cevap' or 'yanlis_cevap'. None = standard distractor.",
    )
    templates: list[str] = Field(
        default_factory=list,
        description="List of template IDs this strategy applies to. Empty = all templates.",
    )
    # Legacy single example (for backward compat during transition)
    ornek: str | DistractorExample | None = Field(
        default=None,
        description="Single example (legacy or simple)",
    )
    # Rich examples list
    ornekler: list[DistractorExample] = Field(
        default_factory=list,
        description="Multiple examples for this strategy",
    )


# ============================================================================
# TOPIC SOURCE CONFIGURATION
# ============================================================================


class TopicHierarchyLevel(BaseModel):
    """Definition of a hierarchy level."""

    name: str = Field(..., description="Level name (e.g., 'unite', 'konu')")
    description: str = Field(default="", description="Level description")


class TopicHierarchy(BaseModel):
    """Topic hierarchy configuration."""

    separator: str = Field(default=" / ", description="Hierarchy separator")
    levels: list[TopicHierarchyLevel] = Field(
        default_factory=list,
        description="Hierarchy level definitions",
    )


class TopicSourceConfig(BaseModel):
    """Configuration for topic source files and hierarchy."""

    klasor: str = Field(default="legacy_app/kadir_hoca/konular/", description="Topics folder")
    dosyalar: list[str] = Field(
        default_factory=list,
        description="List of topic files",
    )
    hierarchy: TopicHierarchy = Field(
        default_factory=TopicHierarchy,
        description="Hierarchy configuration",
    )
    generation_rules: list[str] = Field(
        default_factory=list,
        description="Rules for standard generation",
    )
    inverse_generation_rules: list[str] = Field(
        default_factory=list,
        description="Rules for inverse generation",
    )


# ============================================================================
# BECERI (SKILL-BASED) CONFIGURATION
# ============================================================================


class BeceriConfig(BaseModel):
    """Configuration for beceri temelli (skill-based) question templates."""

    context_type: str = Field(
        ...,
        description="Context type (SENARYO, HIKAYE, AFIS, TABLO, DIYALOG, SIIR, etc.)",
    )
    context_label: str = Field(
        default="",
        description="Display label for context type",
    )
    skill_areas: list[str] = Field(
        default_factory=list,
        description="Measurable skill areas (e.g., anlama, cikarimlama, degerlendirme)",
    )
    skill_level: str = Field(
        default="KB2",
        description="Cognitive skill level: KB1 (temel), KB2 (butunlesik), KB3 (ust duzey)",
    )
    process_component: str = Field(
        default="",
        description="Bilissel surec bileseni - olculecek dusunme sureci aciklamasi",
    )
    answer_key_explanation: bool = Field(
        default=True,
        description="Whether to generate answer key explanation",
    )
    question_patterns: list[str] = Field(
        default_factory=list,
        description="Typical question patterns for this context type",
    )
    image_context: bool = Field(
        default=False,
        description="If True, generate image (poster/afis) as primary context. Paragraph hidden in HTML, image shown instead.",
    )


# ============================================================================
# MAIN TEMPLATE MODEL
# ============================================================================


class QuestionTemplate(BaseModel):
    """
    Question Template - defines content rules for a specific question type.

    Templates contain Turkish content because that content goes directly
    to the LLM for question generation.

    The new template structure has:
    - format as FormatConfig object (not string)
    - Rich distractor strategies with ornekler list
    - Correct answer config with examples
    - Optional konu_kaynagi for topic hierarchy
    - Optional generation_logic, validation_checklist, ornekler
    """

    model_config = {"extra": "allow"}

    @model_validator(mode="before")
    @classmethod
    def _split_celdirici_dict(cls, data: Any) -> Any:
        """If celdirici_stratejileri is a dict (rich format), extract stratejiler list
        and move the rest to celdirici_rehberi."""
        if not isinstance(data, dict):
            return data
        cs = data.get("celdirici_stratejileri")
        if isinstance(cs, dict):
            stratejiler = cs.pop("stratejiler", [])
            data["celdirici_rehberi"] = cs
            data["celdirici_stratejileri"] = stratejiler
        return data

    # Metadata
    meta: TemplateMeta = Field(..., description="Template metadata")

    # Format configuration (embedded, not referenced)
    format: FormatConfig = Field(
        ...,
        description="Format configuration (type, paragraph, stem, options specs)",
    )

    # Model configuration (optional - falls back to defaults)
    models: ModelConfig | None = Field(
        default=None,
        description="Optional model overrides for this template",
    )

    # Question stem variations (Turkish)
    # Can be simple strings or StemPattern dicts with pattern/example
    # Empty for context templates (stems are per-slot in context.questions)
    soru_kokleri: list[str | dict[str, str]] = Field(
        default_factory=list,
        description="List of question stem variations or patterns",
    )

    # Correct answer rules (Turkish)
    dogru_cevap: CorrectAnswerConfig = Field(
        ...,
        description="Correct answer configuration with examples",
    )

    # Distractor strategies (Turkish)
    # Accepts either a list of strategies OR a dict with 'stratejiler' key + extra guidance
    celdirici_stratejileri: list[DistractorStrategy] = Field(
        default_factory=list,
        description="Distractor generation strategies with examples",
    )

    # Extra distractor guidance (temel_ilke, ana_prensipler, yasaklar, etc.)
    # Auto-populated from celdirici_stratejileri dict format
    celdirici_rehberi: dict = Field(
        default_factory=dict,
        description="Extra distractor guidance extracted from dict-format celdirici_stratejileri",
    )

    # Shared strategies flag (when True, strategies loaded from _strategies.yaml)
    use_shared_strategies: bool = Field(
        default=False,
        description="If True, load distractor strategies from shared pool (_strategies.yaml)",
    )

    # Context-based question configuration
    context: ContextConfig | None = Field(
        default=None,
        description="Context group config — only for context-based templates",
    )
    header_template: str | None = Field(
        default=None,
        description="Header text template for context groups (e.g., '(1-{n}). soruları ... cevaplayınız.')",
    )

    # Beceri configuration: supports both simple dict (capture1/2 beceri etiketi)
    # and full BeceriConfig (beceri_* skill-based templates)
    beceri: BeceriConfig | dict[str, Any] | None = Field(
        default=None,
        description=(
            "Beceri config — either BeceriConfig for skill-based templates "
            "(context_type, skill_areas, etc.) or simple dict for beceri etiketi "
            "(katman, bilesenler, surec_bileseni)"
        ),
    )

    # Optional: Topic source configuration
    konu_kaynagi: TopicSourceConfig | None = Field(
        default=None,
        description="Topic source and hierarchy configuration",
    )

    # Optional: Generation logic (for generator reference)
    generation_logic: dict[str, Any] | None = Field(
        default=None,
        description="Generation logic steps and rules",
    )

    # Optional: Validation checklist
    validation_checklist: dict[str, Any] | None = Field(
        default=None,
        description="Validation checklist for quality checks",
    )

    # Optional: Example questions from PDF
    ornekler: list[dict[str, Any]] | None = Field(
        default=None,
        description="Example questions extracted from source PDF",
    )

    # Visual requirement metadata (Bolum 7 — görsel-bağımlı sorular için)
    # "none": hiçbir görsel; "illustration": süs niteliğinde (non-blocking);
    # "answer_critical": cevap görsele bağımlı (hard fail + answer-aware judge).
    visual_requirement: Literal["none", "illustration", "answer_critical"] | None = Field(
        default=None,
        description=(
            "Visual requirement level. 'answer_critical' triggers the answer-aware "
            "image generator + judge and hard-fails if image is not produced."
        ),
    )
    visual_type: str | None = Field(
        default=None,
        description=(
            "Visual type hint (e.g. symbol_pair, scene, table, chart, infographic, "
            "logic_diagram). Used by the image generator to choose a specialized prompt."
        ),
    )
    visual_spec: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Free-form visual specification forwarded to the image generator "
            "(e.g. {'sembol_sayisi': 2, 'tablo_satir': 4}). Typically mirrors the "
            "template's 'gorsel' YAML block."
        ),
    )
    hide_paragraph_after_visual: bool = Field(
        default=False,
        description=(
            "When True, paragraph is cleared from output after answer-critical visual "
            "generation succeeds. Used for visual-only question types (e.g., 7.2 gorsel_inceleme) "
            "where the paragraph serves only as an internal scene description."
        ),
    )

    @property
    def is_context_template(self) -> bool:
        """Whether this template is a context-based (multi-question) template."""
        return self.context is not None

    @staticmethod
    def _materialize_stem_text(stem: str | dict[str, str]) -> str:
        """Return the actual stem text from a raw YAML stem entry."""
        if isinstance(stem, dict):
            return stem.get("pattern", str(stem))
        return stem

    def reserve_stem(
        self,
        template_id: str | None = None,
    ) -> dict[str, str | int | None]:
        """
        Reserve a balanced stem for this generation attempt.

        The reservation is committed only after the generated question is saved.
        """
        import logging

        logger = logging.getLogger(__name__)

        if template_id is None:
            raise ValueError("[STEM] template_id is required for stem reservation")

        from .stem_registry import reserve_balanced_stem

        reservation = reserve_balanced_stem(template_id, len(self.soru_kokleri))
        stem = self.soru_kokleri[reservation.stem_index]
        stem_text = self._materialize_stem_text(stem)

        logger.debug(
            f"[STEM] Reserved index {reservation.stem_index} for {template_id} "
            f"(reservation={reservation.reservation_id})"
        )

        return {
            "template_id": template_id,
            "selected_stem_index": reservation.stem_index,
            "selected_stem_text": stem_text,
            "stem_source": reservation.stem_source,
            "stem_reservation_id": reservation.reservation_id,
            "stem_reservation_status": reservation.reservation_status,
        }

    def get_random_stem(
        self,
        template_id: str | None = None,
    ) -> str:
        """
        Return a stem using balanced selection (least-used-first).

        Args:
            template_id: Template identifier for registry tracking (required)

        Returns:
            Selected question stem string

        Raises:
            ValueError: If template_id is None
            Exception: On any registry errors (no silent fallback)

        Handles both simple strings and pattern dicts.
        """
        import logging

        logger = logging.getLogger(__name__)

        if template_id is None:
            raise ValueError(
                "[STEM] template_id is required for balanced stem selection"
            )

        from .stem_registry import select_balanced_stem

        idx = select_balanced_stem(template_id, len(self.soru_kokleri))
        stem = self.soru_kokleri[idx]
        logger.debug(f"[STEM] Selected index {idx} for {template_id}")
        return self._materialize_stem_text(stem)
