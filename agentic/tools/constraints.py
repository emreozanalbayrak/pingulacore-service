"""
Deterministic constraint evaluation utilities.

This module provides programmatic validation for:
1. Paragraph structure (sentence/word/char counts)
2. Option balance (visual line equality across A/B/C/D)
3. Text formatting (whitespace normalization, question length)

These constraints run AFTER LLM generation to enforce consistency
that LLMs are unreliable at (counting, visual formatting).
"""

from __future__ import annotations

import re
import textwrap
from pathlib import Path
from typing import TYPE_CHECKING
from typing import Literal

from pydantic import BaseModel, Field, model_validator

if TYPE_CHECKING:
    from ..templates.schema import QuestionTemplate
    from ..batch_validator import BatchValidationResult

__all__ = [
    # Paragraph constraints
    "ParagraphConstraintsConfig",
    "ParagraphMetrics",
    "ParagraphConstraintReport",
    "evaluate_paragraph_constraints",
    # Option constraints (word count from template)
    "OptionWordCountConfig",
    "OptionWordCountReport",
    "evaluate_option_word_count",
    # Formatting constraints
    "FormattingConstraintsConfig",
    "FormattingReport",
    "normalize_text",
    "evaluate_formatting",
    # Option length balance
    "OptionLengthBalanceReport",
    "evaluate_option_length_balance",
    # Context constraints
    "ContextConstraintsConfig",
    "evaluate_context_constraints",
    "build_context_constraints_from_template",
    # Template bridge
    "build_constraints_from_template",
    # Çeldirici bilişsel hata kategorileri
    "STRATEGY_TO_BILISSSEL_HATA",
    "map_option_error_categories",
    # Hepsi/Hiçbiri yasağı
    "BANNED_OPTION_PATTERNS",
    "check_banned_options",
    # Hikaye unsur secenek kontrolu
    "HIKAYE_UNSUR_ALLOWED",
    "check_hikaye_unsur_options",
    # Metin turu secenek kontrolu
    "METIN_TURU_ALLOWED",
    "check_metin_turu_options",
    # Mutlak ifade yasağı
    "ABSOLUTE_EXPRESSION_PATTERNS",
    "check_absolute_expressions",
    # Köşeli parantez kalıntısı
    "check_bracket_remnants",
    # Karar ağacı — yayınlanma durumu
    "compute_publication_status",
]


# ============================================================================
# SHARED REGEX PATTERNS
# ============================================================================

# Turkish word pattern (includes special chars: Ç, Ğ, İ, Ö, Ş, Ü)
_TURKISH_WORD_RE: re.Pattern[str] = re.compile(
    r"[0-9A-Za-zÇĞİÖŞÜçğıöşü]+(?:[''][0-9A-Za-zÇĞİÖŞÜçğıöşü]+)?",
    flags=re.UNICODE,
)

# Sentence-ending punctuation
_SENTENCE_SPLIT_RE: re.Pattern[str] = re.compile(r"[.!?]+", flags=re.UNICODE)

# Multiple paragraphs (blank line between them)
_MULTI_PARAGRAPH_RE: re.Pattern[str] = re.compile(r"\n\s*\n", flags=re.UNICODE)

# Whitespace patterns
_MULTI_SPACE_RE: re.Pattern[str] = re.compile(r" {2,}")
_TAB_RE: re.Pattern[str] = re.compile(r"\t")
_BLANK_LINE_RE: re.Pattern[str] = re.compile(r"\n\s*\n")
_LINE_LEADING_WS_RE: re.Pattern[str] = re.compile(r"(?<=\n) +")
_LINE_TRAILING_WS_RE: re.Pattern[str] = re.compile(r" +(?=\n)")
_CONSECUTIVE_PUNCT_RE: re.Pattern[str] = re.compile(r"([.!?,;:]){2,}")

# HTML tags (for stripping before word count)
_HTML_TAG_RE: re.Pattern[str] = re.compile(r"</?[a-zA-Z][^>]*>")

# Match <br>, <br/>, <br /> with optional whitespace (defined early — used by
# _normalize_text_for_metrics; re-defined later with same pattern for other code paths).
_BR_TAG_RE: re.Pattern[str] = re.compile(r"<\s*br\s*/?\s*>", flags=re.IGNORECASE)


# ============================================================================
# SHARED HELPER FUNCTIONS
# ============================================================================

def _normalize_text_for_metrics(text: str) -> str:
    """Normalize line endings, strip HTML tags, and strip whitespace."""
    # Replace <br> (and variants) with space so adjacent sentences don't merge
    # together (e.g. "...başladı.<br>2. ..." must become "...başladı. 2. ...").
    text = _BR_TAG_RE.sub(" ", text)
    # Strip HTML tags before measuring — infographic/poster content uses
    # HTML tables, cards, divs etc. that inflate word counts unfairly.
    text = _HTML_TAG_RE.sub("", text)
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def _wrapped_line_count(text: str, width: int) -> int:
    """
    Count lines after wrapping text to specified width.

    Args:
        text: Text to wrap
        width: Maximum characters per line

    Returns:
        Number of lines after wrapping (minimum 1 for non-empty text)
    """
    text = text.strip()
    if not text:
        return 0

    # Flatten to single line for wrapping
    flattened = re.sub(r"\s+", " ", text.replace("\n", " ")).strip()
    if not flattened:
        return 0

    lines = textwrap.wrap(
        flattened,
        width=width,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return len(lines) if lines else 1


# Turkish abbreviations whose trailing dot is NOT a sentence end
_ABBREV_RE: re.Pattern[str] = re.compile(
    r"\b(Hz|Dr|Prof|Doç|Yrd|Öğr|Gör|Arş|Uzm|Op|Av|Müh|Alb|Gen|Org|Bnb|Yzb|Bkz|vb|vs|vd|Mah|Cad|Sok|Blv|No|Apt|Kat)\.",
    flags=re.UNICODE,
)


def _sentence_count(text: str) -> int:
    """Count sentences by splitting on . ! ?

    Handles Turkish abbreviations (Hz., Dr., Prof., vb., etc.) and
    Roman numeral labels (I. II. III. IV. V.) by replacing their
    trailing dot with a placeholder before splitting.
    """
    text = _HTML_TAG_RE.sub(" ", text)  # strip HTML tags (e.g. <br>)
    text = text.replace("\n", " ").strip()
    # Replace Roman numeral label dots (I. II. III. IV. V. VI.) so they
    # are not treated as sentence endings
    clean = re.sub(
        r"(?:^|\s)(I{1,3}|IV|VI{0,3}|V)\.\s",
        lambda m: " " + m.group(1) + "\x00 ",
        text,
    )
    # Replace Arabic numeral label dots (1. 2. 3. 4. ...) used for numbered
    # sentence templates so they are not treated as sentence endings
    clean = re.sub(
        r"(?:^|\s)(\d{1,2})\.\s",
        lambda m: " " + m.group(1) + "\x00 ",
        clean,
    )
    # Replace abbreviation dots so they are not treated as sentence endings
    clean = _ABBREV_RE.sub(lambda m: m.group(1) + "\x00", clean)
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(clean)]
    # Only count parts containing actual words
    meaningful = [p for p in parts if _TURKISH_WORD_RE.search(p)]
    return len(meaningful)


# Match <br>, <br/>, <br /> with optional whitespace
_BR_TAG_RE: re.Pattern[str] = re.compile(r"<\s*br\s*/?\s*>", flags=re.IGNORECASE)


def _line_count_poem(text: str) -> int:
    """Count dize (lines) in a poem by counting <br> tags + newlines.

    Poems don't use standard sentence-ending punctuation — each dize is
    separated by <br> or newline. Counts non-empty segments after splitting.
    """
    # Normalize: convert <br> variants to \n
    normalized = _BR_TAG_RE.sub("\n", text)
    # Strip remaining HTML tags
    normalized = _HTML_TAG_RE.sub("", normalized)
    # Split on newlines and count non-empty lines with actual words
    lines = [ln.strip() for ln in normalized.split("\n")]
    meaningful = [ln for ln in lines if _TURKISH_WORD_RE.search(ln)]
    return len(meaningful)


def _word_count(text: str) -> int:
    """Count all Turkish words in text."""
    return len(_TURKISH_WORD_RE.findall(text))


def _range_distance(value: int, min_v: int, max_v: int) -> int:
    """Return 0 if value in range, else distance to nearest bound."""
    if value < min_v:
        return min_v - value
    if value > max_v:
        return value - max_v
    return 0


# ============================================================================
# PARAGRAPH CONSTRAINTS
# ============================================================================

class ParagraphConstraintsConfig(BaseModel):
    """
    Configuration for paragraph length/structure constraints.

    Validates sentence count, word count, character count, and visual line count.
    """
    enabled: bool = False
    enforcement: Literal["soft", "strict"] = "soft"
    max_attempts: int = 3

    # Optionally limit to specific question types
    apply_to_question_types: list[str] | None = None

    # Sentence count bounds
    sentence_min: int = 5
    sentence_max: int = 7

    # Word count bounds
    word_min: int = 65
    word_max: int = 80

    # Character count bounds (including spaces)
    char_min: int = 450
    char_max: int = 550

    # Visual line count bounds (after wrapping)
    wrapped_line_min: int = 7
    wrapped_line_max: int = 9
    wrap_width: int = 70

    # Content restrictions
    forbid_multiple_paragraphs: bool = True

    # Text type (for sentence counting behavior)
    # "siir" → count <br> tags as line separators, relax sentence-ending punctuation
    # other → standard sentence counting via . ! ?
    text_type: str = "prose"

    @model_validator(mode="after")
    def _validate_ranges(self) -> "ParagraphConstraintsConfig":
        """Ensure min <= max for all ranges."""
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.sentence_min > self.sentence_max:
            raise ValueError("sentence_min must be <= sentence_max")
        if self.word_min > self.word_max:
            raise ValueError("word_min must be <= word_max")
        if self.char_min > self.char_max:
            raise ValueError("char_min must be <= char_max")
        if self.wrapped_line_min > self.wrapped_line_max:
            raise ValueError("wrapped_line_min must be <= wrapped_line_max")
        if self.wrap_width < 10:
            raise ValueError("wrap_width must be >= 10")
        return self



class ParagraphMetrics(BaseModel):
    """Measured metrics from a paragraph."""
    sentence_count: int = Field(ge=0)
    word_count: int = Field(ge=0)
    character_count: int = Field(ge=0)
    wrapped_line_count: int = Field(ge=0)
    has_multiple_paragraphs: bool


class ParagraphConstraintReport(BaseModel):
    """Result of evaluating paragraph against constraints."""
    passed: bool
    metrics: ParagraphMetrics
    violations: list[str] = Field(default_factory=list)
    score: int = Field(ge=0)  # Lower is better

    def to_feedback_text(self, cfg: ParagraphConstraintsConfig) -> str:
        """Generate Turkish feedback for LLM revision."""
        lines = [
            "Paragraf aşağıdaki ölçütleri karşılamıyor. Lütfen paragrafı yeniden yaz ve ölçütleri TAM karşıla:",
            f"- Cümle sayısı hedefi: {cfg.sentence_min}-{cfg.sentence_max} (senin: {self.metrics.sentence_count})",
            f"- Kelime sayısı hedefi: {cfg.word_min}-{cfg.word_max} (senin: {self.metrics.word_count})",
            f"- Karakter sayısı hedefi: {cfg.char_min}-{cfg.char_max} (senin: {self.metrics.character_count})",
            (
                f"- Satır sayısı hedefi (~{cfg.wrap_width} karakter/satır): "
                f"{cfg.wrapped_line_min}-{cfg.wrapped_line_max} (senin: {self.metrics.wrapped_line_count})"
            ),
        ]
        if cfg.forbid_multiple_paragraphs:
            lines.append("- Tek paragraf olmalı (boş satır/ikinci paragraf olmamalı)")
        if self.violations:
            lines.append("Uymayanlar: " + "; ".join(self.violations[:5]))
        return "\n".join(lines)


def evaluate_paragraph_constraints(
    paragraph: str,
    cfg: ParagraphConstraintsConfig,
) -> ParagraphConstraintReport:
    """
    Evaluate a paragraph against the given constraints.

    Returns:
        ParagraphConstraintReport with pass/fail, metrics, violations, and score
    """
    text = _normalize_text_for_metrics(paragraph)

    # Measure all metrics
    # For poems: count <br> + newlines as line separators (each dize = 1 sentence).
    # Auto-detect: if text_type allows siir OR paragraph has 3+ <br> and few periods
    # (classic poem shape), switch to line counting so we don't undercount dize-only text.
    _period_count = text.count(".") + text.count("!") + text.count("?")
    _br_count = len(_BR_TAG_RE.findall(paragraph or ""))
    _looks_like_poem = _br_count >= 3 and _period_count <= 1
    if cfg.text_type == "siir" or _looks_like_poem:
        sentence_count = _line_count_poem(paragraph)
    else:
        sentence_count = _sentence_count(text)
    word_count = _word_count(text)
    character_count = len(text)
    wrapped_line_count = _wrapped_line_count(text, width=cfg.wrap_width)

    has_multiple_paragraphs = bool(_MULTI_PARAGRAPH_RE.search(text))

    metrics = ParagraphMetrics(
        sentence_count=sentence_count,
        word_count=word_count,
        character_count=character_count,
        wrapped_line_count=wrapped_line_count,
        has_multiple_paragraphs=has_multiple_paragraphs,
    )

    # Check constraints
    violations: list[str] = []
    score = 0

    sentence_dist = _range_distance(sentence_count, cfg.sentence_min, cfg.sentence_max)
    if sentence_dist:
        violations.append("cümle sayısı")
        score += sentence_dist

    word_dist = _range_distance(word_count, cfg.word_min, cfg.word_max)
    if word_dist:
        violations.append("kelime sayısı")
        score += word_dist

    char_dist = _range_distance(character_count, cfg.char_min, cfg.char_max)
    if char_dist:
        violations.append("karakter sayısı")
        score += char_dist

    line_dist = _range_distance(wrapped_line_count, cfg.wrapped_line_min, cfg.wrapped_line_max)
    if line_dist:
        violations.append("satır sayısı")
        score += line_dist

    if cfg.forbid_multiple_paragraphs and has_multiple_paragraphs:
        violations.append("çoklu paragraf")
        score += 1000

    return ParagraphConstraintReport(
        passed=len(violations) == 0,
        metrics=metrics,
        violations=violations,
        score=score,
    )


# ============================================================================
# OPTION CONSTRAINTS
# ============================================================================

# ============================================================================
# FORMATTING CONSTRAINTS
# ============================================================================

class FormattingConstraintsConfig(BaseModel):
    """
    Configuration for formatting validation and normalization.

    Handles whitespace cleanup and question stem length limits.
    """
    enabled: bool = True
    max_attempts: int = 2

    # Text normalization rules
    max_consecutive_spaces: int = 1
    forbid_leading_whitespace: bool = True
    forbid_trailing_whitespace: bool = True
    forbid_tabs: bool = True
    forbid_blank_lines: bool = True
    forbid_consecutive_punctuation: bool = True

    # Question stem limits
    question_max_lines: int = 3
    question_max_chars: int = 200
    wrap_width: int = 48

    # Visual validation (after PNG render)
    visual_validation_enabled: bool = True
    png_min_height: int = 200
    png_max_height: int = 500
    max_blank_rows_ratio: float = 0.15

    @model_validator(mode="after")
    def _validate_ranges(self) -> "FormattingConstraintsConfig":
        """Ensure values are sensible."""
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.max_consecutive_spaces < 1:
            raise ValueError("max_consecutive_spaces must be >= 1")
        if self.question_max_lines < 1:
            raise ValueError("question_max_lines must be >= 1")
        if self.question_max_chars < 10:
            raise ValueError("question_max_chars must be >= 10")
        if self.wrap_width < 10:
            raise ValueError("wrap_width must be >= 10")
        if not 0 <= self.max_blank_rows_ratio <= 1:
            raise ValueError("max_blank_rows_ratio must be between 0 and 1")
        return self



class FormattingReport(BaseModel):
    """Result of formatting validation."""
    passed: bool
    text_issues: list[str] = Field(default_factory=list)
    visual_issues: list[str] = Field(default_factory=list)
    normalized_paragraph: str = ""
    normalized_question: str = ""
    normalized_options: dict[str, str] = Field(default_factory=dict)
    affected_components: list[str] = Field(default_factory=list)
    normalization_applied: list[str] = Field(default_factory=list)

    def to_feedback_text(self, cfg: FormattingConstraintsConfig) -> str:
        """Generate Turkish feedback for regeneration."""
        lines = ["Formatlama sorunları tespit edildi. Lütfen düzelt:"]
        for issue in self.text_issues[:5]:
            lines.append(f"  - {issue}")
        if self.affected_components:
            lines.append(f"Etkilenen bileşenler: {', '.join(self.affected_components)}")
        return "\n".join(lines)


def normalize_text(text: str, cfg: FormattingConstraintsConfig | None = None) -> tuple[str, list[str]]:
    """
    Normalize text by fixing common formatting issues.

    Returns:
        Tuple of (normalized_text, list_of_normalizations_applied)
    """
    if cfg is None:
        cfg = FormattingConstraintsConfig()

    applied: list[str] = []
    result = text

    # Strip leading/trailing whitespace
    if cfg.forbid_leading_whitespace or cfg.forbid_trailing_whitespace:
        stripped = result.strip()
        if stripped != result:
            applied.append("baş/son boşluk temizlendi")
            result = stripped

    # Convert tabs to spaces
    if cfg.forbid_tabs and _TAB_RE.search(result):
        result = _TAB_RE.sub(" ", result)
        applied.append("tab → boşluk")

    # Collapse multiple spaces
    if cfg.max_consecutive_spaces == 1 and _MULTI_SPACE_RE.search(result):
        result = _MULTI_SPACE_RE.sub(" ", result)
        applied.append("çift boşluklar birleştirildi")

    # Remove blank lines
    if cfg.forbid_blank_lines and _BLANK_LINE_RE.search(result):
        result = _BLANK_LINE_RE.sub("\n", result)
        applied.append("boş satırlar kaldırıldı")

    # Clean up per-line whitespace
    if _LINE_LEADING_WS_RE.search(result):
        result = _LINE_LEADING_WS_RE.sub("", result)
        applied.append("satır başı boşluklar temizlendi")

    if _LINE_TRAILING_WS_RE.search(result):
        result = _LINE_TRAILING_WS_RE.sub("", result)
        applied.append("satır sonu boşluklar temizlendi")

    # Handle consecutive punctuation
    if cfg.forbid_consecutive_punctuation and _CONSECUTIVE_PUNCT_RE.search(result):
        result = _CONSECUTIVE_PUNCT_RE.sub(r"\1", result)
        applied.append("ardışık noktalama düzeltildi")

    return result, applied


def evaluate_formatting(
    paragraph: str,
    question: str,
    options: dict[str, str],
    cfg: FormattingConstraintsConfig,
) -> FormattingReport:
    """
    Evaluate and normalize text content for formatting issues.

    Returns:
        FormattingReport with normalized text and any issues found
    """
    text_issues: list[str] = []
    affected_components: list[str] = []
    all_normalizations: list[str] = []

    # Normalize paragraph
    normalized_paragraph, para_normalizations = normalize_text(paragraph, cfg)
    all_normalizations.extend(para_normalizations)

    # Normalize question stem
    normalized_question, question_normalizations = normalize_text(question, cfg)
    all_normalizations.extend(question_normalizations)

    # Normalize options
    normalized_options: dict[str, str] = {}
    for letter, text in options.items():
        normalized_opt, opt_normalizations = normalize_text(text, cfg)
        normalized_options[letter] = normalized_opt
        all_normalizations.extend(opt_normalizations)

    # Check question stem length (can't be auto-fixed)
    question_line_count = _wrapped_line_count(normalized_question, cfg.wrap_width)
    question_char_count = len(normalized_question)

    if question_line_count > cfg.question_max_lines:
        text_issues.append(
            f"Soru kökü çok uzun ({question_line_count} satır, max {cfg.question_max_lines})"
        )
        affected_components.append("question_stem")

    if question_char_count > cfg.question_max_chars:
        text_issues.append(
            f"Soru kökü çok uzun ({question_char_count} karakter, max {cfg.question_max_chars})"
        )
        if "question_stem" not in affected_components:
            affected_components.append("question_stem")

    # Check if paragraph still has blank lines
    if _BLANK_LINE_RE.search(normalized_paragraph):
        text_issues.append("Paragraf içinde hala boş satır var")
        affected_components.append("paragraph")

    # Deduplicate normalizations
    unique_normalizations = list(dict.fromkeys(all_normalizations))

    return FormattingReport(
        passed=len(text_issues) == 0,
        text_issues=text_issues,
        visual_issues=[],
        normalized_paragraph=normalized_paragraph,
        normalized_question=normalized_question,
        normalized_options=normalized_options,
        affected_components=affected_components,
        normalization_applied=unique_normalizations,
    )


# ============================================================================
# OPTION WORD COUNT CONSTRAINTS (from template)
# ============================================================================


def _strip_html(text: str) -> str:
    """Remove HTML tags (<b>, <u>, etc.) before counting words."""
    return _HTML_TAG_RE.sub("", text)


class OptionWordCountConfig(BaseModel):
    """
    Per-option word count constraints derived from template FormatConfig.

    Different styles count differently:
    - keyword_set: counts keywords split by " - "
    - roman_numeral_combination: skipped entirely (options are labels like "I ve II")
    - mini_paragraph: also checks sentence count
    - everything else: standard word count
    """

    enabled: bool = True
    style: str = Field(default="topic_phrase", description="Option style from template")
    word_count_min: int = Field(default=2, description="Min words per option")
    word_count_max: int = Field(default=6, description="Max words per option")
    sentence_count_min: int | None = Field(default=None, description="Min sentences (mini_paragraph)")
    sentence_count_max: int | None = Field(default=None, description="Max sentences (mini_paragraph)")

    @model_validator(mode="after")
    def _validate_ranges(self) -> "OptionWordCountConfig":
        if self.word_count_min > self.word_count_max:
            raise ValueError("word_count_min must be <= word_count_max")
        if (
            self.sentence_count_min is not None
            and self.sentence_count_max is not None
            and self.sentence_count_min > self.sentence_count_max
        ):
            raise ValueError("sentence_count_min must be <= sentence_count_max")
        return self


class OptionWordCountReport(BaseModel):
    """Result of evaluating option word counts."""

    passed: bool
    per_option: dict[str, dict[str, int]] = Field(
        default_factory=dict,
        description="Per-option metrics: {label: {word_count: N, ...}}",
    )
    violations: list[str] = Field(default_factory=list)

    def to_feedback_text(self, cfg: OptionWordCountConfig) -> str:
        """Generate Turkish feedback for LLM revision."""
        lines = [
            "Secenek kelime sayilari sinir disinda. Lutfen secenekleri yeniden yaz:",
            f"- Hedef: {cfg.word_count_min}-{cfg.word_count_max} kelime/secenek (stil: {cfg.style})",
        ]
        if cfg.sentence_count_min is not None and cfg.sentence_count_max is not None:
            lines.append(
                f"- Cumle sayisi hedefi: {cfg.sentence_count_min}-{cfg.sentence_count_max}"
            )
        for v in self.violations[:6]:
            lines.append(f"  - {v}")
        return "\n".join(lines)


def evaluate_option_word_count(
    options: dict[str, str],
    cfg: OptionWordCountConfig,
) -> OptionWordCountReport:
    """
    Evaluate option word counts against template-defined bounds.

    Handles style-specific counting:
    - roman_numeral_combination → always passes (options are labels)
    - keyword_set → counts keywords split by " - "
    - mini_paragraph → checks word count AND sentence count
    - others → standard Turkish word count
    """
    # Roman numeral options are labels ("I ve II"), image descriptions are generation prompts — skip
    if cfg.style in ("roman_numeral_combination", "image_description"):
        return OptionWordCountReport(passed=True, per_option={}, violations=[])

    if not options:
        return OptionWordCountReport(passed=True, per_option={}, violations=[])

    per_option: dict[str, dict[str, int]] = {}
    violations: list[str] = []

    for label, text in sorted(options.items()):
        clean = _strip_html(text).strip()
        metrics: dict[str, int] = {}

        if cfg.style == "keyword_set":
            # Count keywords separated by " - "
            keywords = [k.strip() for k in clean.split(" - ") if k.strip()]
            wc = len(keywords)
        else:
            wc = _word_count(clean)

        metrics["word_count"] = wc

        # Check word count bounds
        dist = _range_distance(wc, cfg.word_count_min, cfg.word_count_max)
        if dist:
            direction = "az" if wc < cfg.word_count_min else "fazla"
            violations.append(
                f"Sik {label}: {wc} kelime ({direction}, hedef {cfg.word_count_min}-{cfg.word_count_max})"
            )

        # For mini_paragraph, also check sentence count
        if cfg.style == "mini_paragraph" and cfg.sentence_count_min is not None and cfg.sentence_count_max is not None:
            sc = _sentence_count(clean)
            metrics["sentence_count"] = sc
            s_dist = _range_distance(sc, cfg.sentence_count_min, cfg.sentence_count_max)
            if s_dist:
                direction = "az" if sc < cfg.sentence_count_min else "fazla"
                violations.append(
                    f"Sik {label}: {sc} cumle ({direction}, hedef {cfg.sentence_count_min}-{cfg.sentence_count_max})"
                )

        per_option[label] = metrics

    return OptionWordCountReport(
        passed=len(violations) == 0,
        per_option=per_option,
        violations=violations,
    )


# ============================================================================
# OPTION LENGTH BALANCE CHECK
# ============================================================================


class OptionLengthBalanceReport(BaseModel):
    """Result of evaluating option length balance."""
    passed: bool
    correct_word_count: int = 0
    avg_distractor_word_count: float = 0.0
    ratio: float = 1.0
    violations: list[str] = Field(default_factory=list)

    def to_feedback_text(self) -> str:
        lines = [
            "SECENEK UZUNLUK DENGESI IHLALI (DETERMINISTIK):",
            f"- Dogru cevap: {self.correct_word_count} kelime",
            f"- Celdirici ortalamasi: {self.avg_distractor_word_count:.1f} kelime",
            f"- Oran: {self.ratio:.2f} (hedef: 0.70-1.30)",
            "- Tum secenekleri AYNI uzunlukta yaz (±1-2 kelime fark)",
        ]
        for v in self.violations[:4]:
            lines.append(f"  - {v}")
        return "\n".join(lines)


def evaluate_option_length_balance(
    options: dict[str, str],
    correct_answer: str,
    style: str = "",
) -> OptionLengthBalanceReport:
    """
    Check that correct answer is not significantly longer/shorter than distractors.

    Skips roman_numeral_combination style (options are labels).

    Thresholds:
    - Short options (correct ≤ 3 words AND avg distractor ≤ 3 words):
      Allow up to 2 words absolute difference. For very short options like
      "Sayısal veriler" (2w) vs "Tanımlama" (1w), ratio-based comparison
      is too sensitive — 1 word difference creates ratio 2.0 but is
      acceptable in practice.
    - Standard options: ratio-based threshold 1.30/0.70 (30% tolerance).
    """
    if style in ("roman_numeral_combination", "image_description"):
        return OptionLengthBalanceReport(passed=True)

    if not options or correct_answer not in options:
        return OptionLengthBalanceReport(passed=True)

    correct_text = _strip_html(options[correct_answer]).strip()
    correct_wc = _word_count(correct_text)

    distractor_wcs = []
    for letter, text in options.items():
        if letter != correct_answer:
            clean = _strip_html(text).strip()
            distractor_wcs.append(_word_count(clean))

    if not distractor_wcs or correct_wc == 0:
        return OptionLengthBalanceReport(passed=True)

    avg_distractor = sum(distractor_wcs) / len(distractor_wcs)
    if avg_distractor == 0:
        return OptionLengthBalanceReport(passed=True)

    ratio = correct_wc / avg_distractor
    abs_diff = abs(correct_wc - avg_distractor)
    violations = []

    # Short options: use absolute difference threshold (≤2 words OK)
    is_short = correct_wc <= 3 and avg_distractor <= 3
    if is_short:
        if abs_diff > 2:
            violations.append(
                f"Dogru cevap ({correct_wc} kelime) celdiricilerden "
                f"cok {'uzun' if correct_wc > avg_distractor else 'kisa'} "
                f"(ort: {avg_distractor:.0f} kelime, fark: {abs_diff:.0f})"
            )
    else:
        # Standard options: ratio-based threshold (tightened from 1.30/0.70)
        if ratio > 1.20:
            violations.append(
                f"Dogru cevap ({correct_wc} kelime) celdiricilerden "
                f"cok uzun (ort: {avg_distractor:.0f} kelime, oran: {ratio:.2f}, hedef: 0.80-1.20)"
            )
        elif ratio < 0.80:
            violations.append(
                f"Dogru cevap ({correct_wc} kelime) celdiricilerden "
                f"cok kisa (ort: {avg_distractor:.0f} kelime, oran: {ratio:.2f}, hedef: 0.80-1.20)"
            )

    # Additional check: correct answer should NOT be the longest option
    if distractor_wcs and correct_wc > 0:
        max_dist = max(distractor_wcs)
        if correct_wc > max_dist and correct_wc - max_dist >= 2:
            violations.append(
                f"Dogru cevap ({correct_wc} kelime) en uzun secenek "
                f"(en uzun celdirici: {max_dist} kelime) — dengeli olmali"
            )

    return OptionLengthBalanceReport(
        passed=len(violations) == 0,
        correct_word_count=correct_wc,
        avg_distractor_word_count=avg_distractor,
        ratio=ratio,
        violations=violations,
    )


# ============================================================================
# CONTEXT CONSTRAINTS
# ============================================================================


class ContextConstraintsConfig(BaseModel):
    """Word count constraints for context text (scenario + data)."""

    word_count_min: int = 80
    word_count_max: int = 200


def evaluate_context_constraints(
    context_text: str,
    cfg: ContextConstraintsConfig,
) -> tuple[bool, str]:
    """Evaluate context text word count against constraints.

    Returns:
        (passed, feedback_text) — feedback_text is empty if passed.
    """
    clean = _HTML_TAG_RE.sub("", context_text)
    wc = _word_count(clean)

    if cfg.word_count_min <= wc <= cfg.word_count_max:
        return True, ""

    direction = "az" if wc < cfg.word_count_min else "fazla"
    feedback = (
        f"BAGLAM METNI KELIME SAYISI IHLALI (DETERMINISTIK):\n"
        f"- Hedef: {cfg.word_count_min}-{cfg.word_count_max} kelime\n"
        f"- Mevcut: {wc} kelime ({direction})\n"
        f"- Baglam metnini {cfg.word_count_min}-{cfg.word_count_max} kelime arasina getir.\n"
    )
    return False, feedback


def build_context_constraints_from_template(
    template: "QuestionTemplate",
) -> ContextConstraintsConfig | None:
    """Build context constraints from a context template.

    Returns None if the template is not a context template.
    """
    if not hasattr(template, "context") or template.context is None:
        return None

    gen = template.context.generation
    return ContextConstraintsConfig(
        word_count_min=gen.word_count_min,
        word_count_max=gen.word_count_max,
    )


# ============================================================================
# TEMPLATE → CONSTRAINT BRIDGE
# ============================================================================


def build_constraints_from_template(
    template: "QuestionTemplate",
) -> tuple[ParagraphConstraintsConfig | None, OptionWordCountConfig]:
    """
    Auto-build deterministic constraint configs from a loaded template.

    Reads format.paragraph.* and format.options.* from the template's
    FormatConfig and creates corresponding constraint objects.

    Returns:
        (paragraph_cfg, option_wc_cfg) — paragraph_cfg is None for
        inverse templates where paragraph.required=false.
    """
    fmt = template.format

    # --- Paragraph constraints ---
    if fmt.paragraph.required:
        para_count = getattr(fmt.paragraph, "count", 1) or 1
        # For multi-paragraph templates, multiply ranges by count
        word_min = fmt.paragraph.word_count_min * para_count
        word_max = fmt.paragraph.word_count_max * para_count
        sentence_min = fmt.paragraph.sentence_count_min * para_count
        sentence_max = fmt.paragraph.sentence_count_max * para_count

        # Detect poem: template.format.paragraph.stil is EXACTLY "siir"
        # (substring match would false-positive templates like
        # "bilgilendirici_veya_oykuleyici_veya_siir" which can also be plain prose —
        # runtime auto-detection in evaluate_paragraph_constraints handles those).
        stil = (getattr(fmt.paragraph, "stil", "") or "").lower().strip()
        text_type = "siir" if stil == "siir" else "prose"

        para_cfg = ParagraphConstraintsConfig(
            enabled=True,
            enforcement="soft",
            sentence_min=sentence_min,
            sentence_max=sentence_max,
            word_min=word_min,
            word_max=word_max,
            # Template doesn't define char/line limits — use wide ranges to disable
            char_min=0,
            char_max=99999,
            wrapped_line_min=0,
            wrapped_line_max=99,
            # Multi-paragraph templates need multiple paragraphs
            forbid_multiple_paragraphs=(para_count <= 1),
            # Text type for sentence counting (siir → count <br>, prose → count . ! ?)
            text_type=text_type,
        )
    else:
        para_cfg = None

    # --- Option word count constraints ---
    opt_cfg = OptionWordCountConfig(
        enabled=True,
        style=fmt.options.style,
        word_count_min=fmt.options.word_count_min,
        word_count_max=fmt.options.word_count_max,
        sentence_count_min=fmt.options.sentence_count_min,
        sentence_count_max=fmt.options.sentence_count_max,
    )

    return para_cfg, opt_cfg


# ============================================================================
# ÇELDİRİCİ BİLİŞSEL HATA KATEGORİLERİ
# ============================================================================

STRATEGY_TO_BILISSSEL_HATA: dict[str, str] = {
    # kavram_karisikligi
    "KAVRAM_YANILGISI": "kavram_karisikligi",
    "DEGERI_EYLEME_INDIRME": "kavram_karisikligi",
    # eksik_analiz
    "EKSIK_ANALIZ": "eksik_analiz",
    "KAPSAM_DARALTMA": "eksik_analiz",
    "KISMI_DOGRUYU_MERKEZE_ALMA": "eksik_analiz",
    "KAPSAM_KAYDIRMA": "eksik_analiz",
    # asiri_genelleme
    "HATALI_GENELLEME": "asiri_genelleme",
    "ASIRI_SOYUTLAMA": "asiri_genelleme",
    "KOSUL_SILME": "asiri_genelleme",
    # yanlis_cikarim
    "VERI_YANLIS_YORUMLAMA": "yanlis_cikarim",
    "ASIRI_CIKARIM": "yanlis_cikarim",
    "AMAC_SONUC_KARISTIRMASI": "yanlis_cikarim",
    "KRITER_KAYDIRMA": "yanlis_cikarim",
    "NICEL_ABARTI": "yanlis_cikarim",
    "EN_IYIYI_EN_KOTU_GOSTERME": "yanlis_cikarim",
    "NEDENSELLIK_ZINCIRI_ATLAMASI": "yanlis_cikarim",
    # yuzeysel_okuma_hatasi
    "KISISEL_ONYARGI_TUZAGI": "yuzeysel_okuma_hatasi",
    # paragraf_siralama_ikiye_bolme custom
    "YAKIN_BOLME_NOKTASI": "yuzeysel_okuma_hatasi",
    "KONU_DEVAMLILIK_TUZAGI": "eksik_analiz",
    "GECIS_SOZCUGU_ALDATMACASI": "kavram_karisikligi",
    # sozel_mantik_standard + sozel_mantik_baglam_2q custom
    "MANTIKSAL_TERSINE_CEVIRME": "yanlis_cikarim",
    "ASIRI_CIKARIM_MANTIK": "asiri_genelleme",
    "KISMI_DOGRU_ONERME": "eksik_analiz",
    # metinler_arasi_baglam_2q custom
    "TEK_METNE_ODAKLANMA": "eksik_analiz",
    "YUZEY_FARK": "yuzeysel_okuma_hatasi",
    "DETAY_YANILTMASI": "yuzeysel_okuma_hatasi",
}


def map_option_error_categories(
    option_reasoning: dict[str, dict],
    correct_answer: str,
) -> dict[str, str]:
    """Map each distractor option to its bilişsel hata category.

    Uses the strategy field from option_reasoning to look up the category.
    Skips the correct answer (maps to "dogru_cevap").
    For combined strategies (list), uses the first strategy's category.

    Args:
        option_reasoning: {letter: {strategy: str|list, reasoning: str}}
        correct_answer: The correct answer letter (e.g., "A")

    Returns:
        {letter: category_name} for all options
    """
    result: dict[str, str] = {}

    for letter, reasoning in sorted(option_reasoning.items()):
        if letter == correct_answer:
            result[letter] = "dogru_cevap"
            continue

        strategy = reasoning.get("strategy", "")

        # Handle list of strategies (combined)
        if isinstance(strategy, list):
            first_strategy = strategy[0] if strategy else ""
        else:
            first_strategy = strategy

        # Normalize: strip whitespace, uppercase
        first_strategy = first_strategy.strip().upper()

        # Skip "DOGRU_CEVAP" labels
        if first_strategy in ("DOGRU_CEVAP", "CORRECT_ANSWER"):
            result[letter] = "dogru_cevap"
            continue

        category = STRATEGY_TO_BILISSSEL_HATA.get(first_strategy, "diger")
        result[letter] = category

    return result


# ============================================================================
# HEPSİ/HİÇBİRİ YASAĞI
# ============================================================================

BANNED_OPTION_PATTERNS: list[str] = [
    "hepsi",
    "hiçbiri",
    "hicbiri",
    "hiç biri",
    "yukarıdakilerin hepsi",
    "yukaridakilerin hepsi",
    "yukarıdakilerin hiçbiri",
    "yukaridakilerin hicbiri",
    "hepsi doğrudur",
    "hepsi dogrudur",
    "hiçbiri doğru değildir",
    "hicbiri dogru degildir",
    "bunların hepsi",
    "bunlarin hepsi",
    "bunların hiçbiri",
    "bunlarin hicbiri",
]


def check_context_bold_leak(context_text: str) -> tuple[bool, str]:
    """Check if context text contains bold/strong tags that may reveal answers.

    Bold text in context scenarios draws attention to specific information
    and can give away the correct answer.

    Returns:
        (passed, feedback_text) — passed=False if bold tags found.
    """
    if not context_text:
        return True, ""

    bold_match = re.search(r'<(?:b|strong)\b[^>]*>(.+?)</(?:b|strong)>', context_text, re.IGNORECASE | re.DOTALL)
    if bold_match:
        snippet = bold_match.group(1)[:60]
        return False, (
            "BAGLAM METNI KALIN YAZI IHLALI (DETERMINISTIK): "
            f"Baglam/senaryo metninde <b> veya <strong> etiketi kullanilmis: \"{snippet}...\". "
            "Kalin yazi cevabi belli eder. Baglam metninde KALIN YAZI KULLANMA, "
            "tum metin ayni font agirliginda olmali."
        )
    return True, ""


def check_banned_options(options: dict[str, str]) -> tuple[bool, str]:
    """Check options for banned 'hepsi/hiçbiri' patterns.

    Args:
        options: {letter: option_text}

    Returns:
        (passed, feedback_text) — passed=True if no banned options found.
        feedback_text is empty if passed, otherwise describes violations.
    """
    violations: list[str] = []

    for letter, text in sorted(options.items()):
        clean = text.strip().lower()
        # Strip HTML tags before checking
        clean = _HTML_TAG_RE.sub("", clean).strip()

        for pattern in BANNED_OPTION_PATTERNS:
            if clean == pattern or clean.startswith(pattern + " ") or clean.endswith(" " + pattern):
                violations.append(
                    f"Sik {letter}: '{text}' yasakli ifade iceriyor ('{pattern}')"
                )
                break

    if not violations:
        return True, ""

    feedback = (
        "YASAKLI SECENEK IHLALI (DETERMINISTIK):\n"
        "- 'Hepsi', 'Hicbiri', 'Yukaridakilerin hepsi/hicbiri' gibi secenekler YASAKTIR.\n"
        "- Bu secenekleri FARKLI, ozgun ifadelerle degistir.\n"
    )
    for v in violations:
        feedback += f"  - {v}\n"

    return False, feedback


# ============================================================================
# HIKAYE UNSUR KONTROLU (sadece hangi_hikaye_unsuru_belirtilmemistir templates)
# ============================================================================

HIKAYE_UNSUR_ALLOWED: set[str] = {
    "zaman", "yer", "mekan", "mekân",
    "kişi", "kisi", "kişiler", "kisiler",
    "olay",
}
# Canonical UPPERCASE forms after normalization
HIKAYE_UNSUR_CANONICAL: set[str] = {"ZAMAN", "MEKAN", "KİŞİ", "OLAY"}


def check_hikaye_unsur_options(options: dict[str, str]) -> tuple[bool, str]:
    """Verify that each option is EXACTLY one of the 4 hikaye unsurs.

    For templates where options must be single-word hikaye unsur labels
    (Zaman, Yer/Mekan, Kişi/Kişiler, Olay). Rejects forbidden words like
    'Sorun', 'Çatışma', 'Tema', or any option containing description/values.

    Returns:
        (passed, feedback_text)
    """
    violations: list[str] = []

    for letter, text in sorted(options.items()):
        clean = _HTML_TAG_RE.sub("", text).strip().lower()
        # Strip trailing punctuation / parentheses content
        clean = re.sub(r"[().:,;]", "", clean).strip()
        if clean not in HIKAYE_UNSUR_ALLOWED:
            violations.append(f"Sik {letter}: '{text}' — izinli degil")

    if not violations:
        return True, ""

    feedback = (
        "HIKAYE UNSUR SECENEK IHLALI (DETERMINISTIK):\n"
        "- Secenekler SADECE sunlardan biri olmali: Zaman, Yer (veya Mekan), "
        "Kişi (veya Kişiler), Olay.\n"
        "- YASAK: 'Sorun', 'Çatışma', 'Tema', 'Anlatıcı', 'Olay örgüsü', 'Duygu' — "
        "bunlar hikaye unsuru DEGILDIR.\n"
        "- YASAK: Somut icerik degeri (ornek: 'Cumartesi sabahi', 'Ali', 'Bahçede').\n"
        "- Her secenek TEK KELIME olmalı, aciklama/icerik icermemeli.\n"
    )
    for v in violations:
        feedback += f"  - {v}\n"

    return False, feedback


# ============================================================================
# METIN TURU SECENEK KONTROLU (metin_turleri_standard templates)
# ============================================================================

METIN_TURU_ALLOWED: set[str] = {
    "hikâye", "hikaye",
    "masal",
    "fabl",
    "anı", "ani",
    "günlük", "gunluk",
    "şiir", "siir",
}


def check_metin_turu_options(options: dict[str, str]) -> tuple[bool, str]:
    """Verify options are from the allowed 6 text-type set: Hikâye/Masal/Fabl/Anı/Günlük/Şiir."""
    violations: list[str] = []
    for letter, text in sorted(options.items()):
        clean = _HTML_TAG_RE.sub("", text).strip().lower()
        clean = re.sub(r"[().:,;]", "", clean).strip()
        if clean not in METIN_TURU_ALLOWED:
            violations.append(f"Sik {letter}: '{text}' — izinli degil")
    if not violations:
        return True, ""
    feedback = (
        "METIN TURU SECENEK IHLALI (DETERMINISTIK):\n"
        "- Secenekler SADECE sunlardan biri olmali: Hikâye, Masal, Fabl, Anı, Günlük, Şiir.\n"
        "- YASAK: Roman, deneme, makale, mektup, haber, biyografi, destan, efsane, tiyatro, mani, ninni.\n"
        "- YASAK: Somut icerik veya aciklama. Her secenek TEK KELIME olmali (tur adi).\n"
    )
    for v in violations:
        feedback += f"  - {v}\n"
    return False, feedback


# ============================================================================
# MUTLAK İFADE YASAĞI
# ============================================================================

ABSOLUTE_EXPRESSION_PATTERNS: list[str] = [
    "her zaman",
    "asla",
    "tamamen",
    "kesinlikle",
    "mutlaka",
    "hiçbir zaman",
    "hicbir zaman",
    "daima",
    "hiç şüphesiz",
    "hic suphesiz",
    "her durumda",
    "istisnasız",
    "istisnaiz",
    "tümüyle",
    "tumuyle",
]


def _match_absolute_pattern(text: str, pattern: str) -> bool:
    """Check if pattern exists as whole word(s) in text.

    Uses regex word boundaries to avoid false positives like
    'maslahat' matching 'asla'.
    """
    escaped = re.escape(pattern)
    return bool(re.search(rf"\b{escaped}\b", text, flags=re.IGNORECASE | re.UNICODE))


def check_verbatim_copy(
    paragraph: str,
    correct_answer: str,
    correct_letter: str,
    threshold: float = 0.70,
) -> tuple[bool, str]:
    """Doğru cevabın paragraftan birebir kopyalanıp kopyalanmadığını kontrol et.

    Paragraftaki her cümleyle doğru cevap arasındaki kelime örtüşme oranını hesaplar.
    Eşik değeri aşılırsa FAIL döner.

    Args:
        paragraph: Paragraf/bağlam metni (HTML tagleri olabilir).
        correct_answer: Doğru cevap metni.
        correct_letter: Doğru cevap harfi (A/B/C/D).
        threshold: Örtüşme eşiği (0.60 = %60).

    Returns:
        (passed, feedback_text) — passed=False if verbatim copy detected.
    """
    if not paragraph or not correct_answer:
        return True, ""

    # Strip HTML tags
    clean_para = _HTML_TAG_RE.sub(" ", paragraph).strip()
    clean_answer = _HTML_TAG_RE.sub(" ", correct_answer).strip()

    # Normalize: lowercase, collapse whitespace
    clean_para = re.sub(r'\s+', ' ', clean_para.lower())
    clean_answer = re.sub(r'\s+', ' ', clean_answer.lower())

    # Filter out stop words and proper nouns (short words, numbers, common connectors)
    _STOP_WORDS = {
        "bir", "bu", "ve", "ile", "için", "de", "da", "den", "dan", "dır", "dir",
        "olan", "olarak", "gibi", "kadar", "daha", "en", "çok", "az", "her",
        "ise", "ki", "ne", "hem", "ama", "ancak", "fakat", "ya", "veya",
        "mi", "mı", "mu", "mü", "the", "a", "an",
    }

    def _filter_words(words: set) -> set:
        """Remove stop words and very short words from overlap calculation."""
        return {w for w in words if len(w) > 2 and w not in _STOP_WORDS}

    # Tokenize answer (filtered)
    answer_words_raw = set(clean_answer.split())
    answer_words = _filter_words(answer_words_raw)
    if len(answer_words) < 3:
        return True, ""  # Too short to check meaningfully

    # Split paragraph into sentences
    sentences = re.split(r'[.!?;]\s*', clean_para)

    max_overlap = 0.0
    worst_sentence = ""
    for sent in sentences:
        sent = sent.strip()
        if not sent or len(sent.split()) < 3:
            continue
        sent_words = _filter_words(set(sent.split()))
        if not sent_words:
            continue
        overlap = len(answer_words & sent_words) / len(answer_words)
        if overlap > max_overlap:
            max_overlap = overlap
            worst_sentence = sent

    if max_overlap >= 0.92:
        feedback = (
            f"DOGRU CEVAP BİREBİR KOPYALAMA (DETERMİNİSTİK): "
            f"Doğru cevap ({correct_letter}) paragraftaki/tablodaki bir cümleyle %{int(max_overlap*100)} "
            f"kelime örtüşmesine sahip — BİREBİR KOPYALAMA YASAK. "
            f"Doğru cevap eş anlamlı sözcüklerle yeniden ifade edilmeli, "
            f"en az %40 kelime farklılığı olmalı."
        )
        return False, feedback
    elif max_overlap >= threshold:
        feedback = (
            f"DOGRU CEVAP TEKRAR UYARISI (DETERMİNİSTİK): "
            f"Doğru cevap ({correct_letter}) paragraftaki/tablodaki bir ifadeyle %{int(max_overlap*100)} "
            f"kelime benzerliği gösteriyor. Eş anlamlı sözcüklerle yeniden ifade edilmeli."
        )
        return False, feedback

    return True, ""


def check_absolute_expressions(
    question: str,
    options: dict[str, str],
    template_id: str = "",
) -> tuple[bool, str]:
    """Soru kökü ve seçeneklerde mutlak ifade kontrolü.

    Soru kökünde mutlak ifade bulunursa → FAIL.
    Seçeneklerde bulunursa → Sadece uyarı (çeldirici stratejisi olabilir:
    OLASILIK_KESINLIK_CELISKISI, SARTLI_DOGRULUK_TUZAGI).

    Öncüllü sorularda (I., II., III., IV. yargılar stem içinde):
    Yargılardaki mutlak ifadeler kontrol dışıdır — yanlış yargılarda
    mutlak ifade kullanımı pedagojik olarak doğru bir tekniktir.

    Args:
        question: Soru kökü metni (HTML tagleri olabilir).
        options: {letter: option_text}

    Returns:
        (passed, feedback_text) — passed=True if no violations in question stem.
        feedback_text is empty if passed.
    """
    # Sözel mantık template'lerinde "kesinlikle" soru kökünün doğal parçasıdır — istisna
    if template_id.startswith("sozel_mantik_"):
        return True, ""

    # Strip HTML tags before checking
    clean_question = _HTML_TAG_RE.sub("", question).strip()

    # For numbered format questions, strip out embedded statements (I. through IV.)
    # These are pedagogical judgments where absolute expressions may be intentional
    _NUMBERED_STATEMENT_RE = re.compile(
        r"(?:^|\n)\s*(?:I{1,3}V?|IV)\.\s.*?(?=\n\s*(?:I{1,3}V?|IV)\.|$)",
        re.MULTILINE | re.DOTALL,
    )
    # Also handle <br>-separated format (common in HTML stems)
    if re.search(r"(?:^|<br\s*/?>)\s*I\.\s", question, re.IGNORECASE):
        # Extract only non-statement parts of the stem
        parts = re.split(r"<br\s*/?>", question)
        non_statement_parts = [
            p for p in parts
            if not re.match(r"\s*(?:I{1,3}V?|IV)\.\s", _HTML_TAG_RE.sub("", p).strip())
        ]
        clean_question = _HTML_TAG_RE.sub("", " ".join(non_statement_parts)).strip()
    else:
        # For non-<br> format, try newline-based extraction
        clean_question = _NUMBERED_STATEMENT_RE.sub("", clean_question).strip()

    stem_violations: list[str] = []
    option_warnings: list[str] = []

    # Check question stem (strict — FAIL)
    for pattern in ABSOLUTE_EXPRESSION_PATTERNS:
        if _match_absolute_pattern(clean_question, pattern):
            stem_violations.append(f"Soru kokunde mutlak ifade: '{pattern}'")

    # Check options (soft — warning only)
    for letter, text in sorted(options.items()):
        clean = _HTML_TAG_RE.sub("", text).strip()
        for pattern in ABSOLUTE_EXPRESSION_PATTERNS:
            if _match_absolute_pattern(clean, pattern):
                option_warnings.append(
                    f"Sik {letter}: mutlak ifade '{pattern}' iceriyor (uyari)"
                )
                break  # One warning per option

    if not stem_violations:
        return True, ""

    feedback = "MUTLAK IFADE IHLALI (DETERMINISTIK):\n"
    feedback += (
        "- Soru kokunde 'her zaman', 'asla', 'kesinlikle', 'mutlaka' gibi "
        "mutlak ifadeler YASAKTIR.\n"
        "- Soru kokunu mutlak ifade OLMADAN yeniden yaz.\n"
    )
    for v in stem_violations:
        feedback += f"  - {v}\n"
    for w in option_warnings:
        feedback += f"  - {w}\n"

    return False, feedback


# ============================================================================
# KÖŞELİ PARANTEZ KALINTISI KONTROLÜ
# ============================================================================

_BRACKET_RE: re.Pattern[str] = re.compile(r'\[([^\]]*)\]')


def check_bracket_remnants(
    question: str,
    options: dict[str, str],
) -> tuple[bool, str]:
    """Soru kökü ve seçeneklerde köşeli parantez kalıntısı kontrolü.

    LLM çıktısında bazen [söz öbeği] kalıntıları kalıyor.
    Bu fonksiyon bunları tespit eder ve deterministik feedback üretir.

    Args:
        question: Soru kökü metni (HTML tagleri olabilir).
        options: {letter: option_text}

    Returns:
        (passed, feedback_text) — passed=True if no bracket remnants found.
    """
    violations: list[str] = []

    # Check question stem
    if _BRACKET_RE.search(question):
        matches = _BRACKET_RE.findall(question)
        violations.append(
            f"Soru kokunde koseli parantez kalintisi: {matches}"
        )

    # Check options
    for letter, text in sorted(options.items()):
        if _BRACKET_RE.search(text):
            matches = _BRACKET_RE.findall(text)
            violations.append(
                f"Sik {letter}: koseli parantez kalintisi: {matches}"
            )

    if not violations:
        return True, ""

    feedback = "KOSELI PARANTEZ KALINTISI (DETERMINISTIK):\n"
    feedback += "- Soru kokunde ve seceneklerde [...] isaretleri KALMAMALI.\n"
    feedback += "- Koseli parantezleri KALDIR, icindeki metni AYNEN birak.\n"
    for v in violations:
        feedback += f"  - {v}\n"

    return False, feedback


# ============================================================================
# KARAR AĞACI — YAYINLANMA DURUMU
# ============================================================================


def compute_publication_status(
    validation_result: "BatchValidationResult",
    constraint_feedback: str,
    ethics_passed: bool,
    cross_validation_passed: bool | None = None,
) -> str:
    """5-aşamalı karar ağacı → yayınlanma durumu etiketi.

    Kontrol Listesi'ndeki karar ağacını uygular:
    - Etik gate (en yüksek öncelik): etik FAIL → "revizyon_zorunlu"
    - Aşama 1: Bağlam seçimi (grade_level + solvability)
    - Aşama 2: Soru ve seçenekler (question_format + distractors + html_technical)
    - Aşama 3: Dil (turkish)
    - Deterministik kısıtlama ihlalleri
    - Çapraz doğrulama (sadece context grupları)

    Args:
        validation_result: Batch validation sonucu.
        constraint_feedback: Deterministik kısıtlama feedback metni (boş = ihlal yok).
        ethics_passed: Etik kontrol geçti mi?
        cross_validation_passed: Çapraz doğrulama sonucu (None = standalone soru).

    Returns:
        "yayina_hazir" | "revizyon_gerekli" | "revizyon_zorunlu"
    """
    # Etik gate (en yüksek öncelik)
    if not ethics_passed:
        return "revizyon_zorunlu"

    # Tüm check'lerin fail sayısı
    fail_count = 0

    # Aşama 1: Bağlam seçimi (grade_level + solvability)
    for check_type in ("grade_level", "solvability"):
        if check_type in validation_result.checks:
            if validation_result.checks[check_type].status == "FAIL":
                fail_count += 1

    # Aşama 2: Soru ve seçenekler (question_format + distractors + html_technical)
    for check_type in ("question_format", "distractors", "html_technical"):
        if check_type in validation_result.checks:
            if validation_result.checks[check_type].status == "FAIL":
                fail_count += 1

    # Deterministik kısıtlama ihlalleri
    if constraint_feedback:
        fail_count += 1

    # Aşama 3: Dil (turkish)
    if "turkish" in validation_result.checks:
        if validation_result.checks["turkish"].status == "FAIL":
            fail_count += 1

    # Çapraz doğrulama (sadece context grupları)
    if cross_validation_passed is not None and not cross_validation_passed:
        fail_count += 1

    # Karar — tüm check'ler PASS olmalı
    if fail_count == 0:
        return "yayina_hazir"
    else:
        return "revizyon_gerekli"
