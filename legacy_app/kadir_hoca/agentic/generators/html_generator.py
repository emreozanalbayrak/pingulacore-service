"""
HTML Question Generator - LLM generates HTML directly from template.

This generator simplifies the question generation flow by having the LLM
produce HTML output directly using the template's html_template field.

Key benefits:
- Code reduction: ~150 lines instead of 804
- Single question prompt: template config drives all behavior
- New templates: Just add YAML, no code changes

The generator still:
- Generates paragraphs separately (with MEB PDF caching)
- Embeds template rules (dogru_cevap, celdirici_stratejileri) in the prompt
- Returns structured output for validation
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING
from typing import Literal

from pydantic import BaseModel, Field

from .base import BaseQuestionGenerator, GeneratorOutput
from ..prompts.paragraph_prompts import PARAGRAPH_SYSTEM_PROMPT
from ..prompts.beceri_prompts import BECERI_SYSTEM_PROMPT, CONTEXT_TYPE_PROMPTS
from ..schemas import ParagraphOutput

if TYPE_CHECKING:
    from ..client import GeminiClient
    from ..templates.schema import QuestionTemplate

__all__ = ["HTMLQuestionGenerator"]

logger = logging.getLogger(__name__)


# ============================================================================
# OUTPUT SCHEMA FOR HTML GENERATION
# ============================================================================


class HTMLOutput(BaseModel):
    """Output schema for HTML question generation."""

    correct_answer: Literal["A", "B", "C", "D", "E"] = Field(
        ...,
        description="The correct answer letter",
    )
    question: str = Field(
        ...,
        description="The question stem text",
    )
    key_word: str = Field(
        default="hangisidir",
        description="Key word from <u> tags in question stem, or 'hangisidir' if none",
    )
    option_a: str = Field(
        ...,
        description="Option A text",
    )
    option_b: str = Field(
        ...,
        description="Option B text",
    )
    option_c: str = Field(
        ...,
        description="Option C text",
    )
    option_d: str = Field(
        default="",
        description="Option D text (optional for 3-option templates)",
    )
    # Reasoning for each option
    option_a_strategy: list[str] | str = Field(
        ...,
        description=(
            "Strategy(ies) used for option A. Can be single string or "
            "list for combined strategies "
            "(e.g., ['YAKIN_ANLAM', 'DETAY_TUZAGI'])"
        ),
    )
    option_a_reasoning: str = Field(
        ...,
        description="Why this option was created with this strategy",
    )
    option_b_strategy: list[str] | str = Field(
        ...,
        description="Strategy(ies) used for option B. Can be single string or list for combined strategies",
    )
    option_b_reasoning: str = Field(
        ...,
        description="Why this option was created with this strategy",
    )
    option_c_strategy: list[str] | str = Field(
        ...,
        description="Strategy(ies) used for option C. Can be single string or list for combined strategies",
    )
    option_c_reasoning: str = Field(
        ...,
        description="Why this option was created with this strategy",
    )
    option_d_strategy: list[str] | str = Field(
        default="",
        description="Strategy(ies) used for option D (optional for 3-option templates)",
    )
    option_d_reasoning: str = Field(
        default="",
        description="Reasoning for option D (optional for 3-option templates)",
    )
    # Option E (optional, for 5-option templates)
    option_e: str = Field(
        default="",
        description="Option E text (5-option templates only)",
    )
    option_e_strategy: list[str] | str = Field(
        default="",
        description="Strategy(ies) used for option E (5-option templates only)",
    )
    option_e_reasoning: str = Field(
        default="",
        description="Reasoning for option E (5-option templates only)",
    )
    # Beceri temelli fields (optional)
    answer_explanation: str = Field(
        default="",
        description="Why this answer is correct (beceri temelli templates)",
    )
    skill_tag: str = Field(
        default="",
        description="Skill area being measured (beceri temelli templates)",
    )
    # Shared visual format for image option templates (gorsel_siklar)
    shared_visual_format: str = Field(
        default="",
        description=(
            "For image option templates ONLY: the SHARED visual format that all 4 options must use. "
            "Describes what is IDENTICAL across all options (chart type, device type, color scheme, layout). "
            "Example: 'Dikey bar grafik, mavi cubuklar, beyaz arka plan, 0-50 Y ekseni, grid cizgileri var'"
        ),
    )
    # Optional titles paragraph for inverse title format
    titles_paragraph: str = Field(
        default="",
        description="For inverse title format: numbered list of titles. Empty for other formats.",
    )
    # Optional numbered statements for roman numeral format
    statement_I: str = Field(
        default="",
        description="Numbered statement/question I (for roman numeral format)",
    )
    statement_II: str = Field(
        default="",
        description="Numbered statement/question II (for roman numeral format)",
    )
    statement_III: str = Field(
        default="",
        description="Numbered statement/question III (for roman numeral format)",
    )
    statement_IV: str = Field(
        default="",
        description="Numbered statement/question IV (for roman numeral format)",
    )


# ============================================================================
# SYSTEM PROMPT
# ============================================================================


_GRADE_AGE_MAP = {
    1: "6-7", 2: "7-8", 3: "8-9", 4: "9-10",
    5: "10-11", 6: "11-12", 7: "12-13", 8: "13-14",
}


def grade_to_age_range(grade: int) -> str:
    """Return age range string for a given grade level."""
    return _GRADE_AGE_MAP.get(grade, f"{grade + 5}-{grade + 6}")


def get_html_generation_system_prompt(grade: int) -> str:
    """Build system prompt with dynamic grade/age info."""
    age_range = grade_to_age_range(grade)
    return f"""Sen bir Turkce ogretmenisin ve MEB mufredat uyumlu soru hazirlama uzmanisin.

TURKCE KURALLARI:
- Turkce karakterleri dogru yaz (ş, ı, ğ, ü, ö, ç). Karakter degistirme (s→ş, i→ı gibi) YASAK.
- Bilesik sozcukleri dogru yaz (birlesik/ayri/tire kurallarina uy).
- Buyuk/kucuk harf kurallarina uy (ozel isimler, cumle basi).

NOKTALAMA:
- Noktalama isaretlerinden ONCE bosluk YOK, SONRA bosluk VAR.
- Ardisik noktalama YASAK (.., !!, ?!).
- Virgul ve nokta kullanimi Turkce kurallarina uygun olsun.
- Soru isareti gereken yerde olmali.

DILBILGISI:
- Ozne-yuklem uyumu sagla.
- Zaman uyumu tutarli olsun (gecmis/genis/gelecek KARISMAMALI).
- Ek yigilmasi (gereksiz ekler) YASAK.
- Devrik cumle gereksiz yere KULLANMA.
- Ayni kelimeyi ayni cumlede TEKRARLAMA.
- Cumle yapisi {grade}. sinif ogrencisi icin dogal olmali.

HTML KISITLAMALARI:
- IZIN VERILEN tag'ler: <b>, <u>, <br> — SADECE bunlar.
- YASAK tag'ler: <ol>, <li>, <ul>, <div>, <span>, <p>, <strong>, <em> — validation FAIL olur!
- <strong> yerine <b>, <em> yerine <u> kullan. Markdown **kalin** KULLANMA, HTML <b>kalin</b> kullan!

ETIK KURALLAR:
- Cinsiyet, irk, etnisite, din, engellilik hakkinda olumsuz cagrisim veya stereotip YASAK.
- Politik/ideolojik yonlendirme YASAK. Dislayici ifade YASAK.
- Icerik {age_range} yas grubuna ({grade}. sinif) uygun olmali. Siddet, korku, travmatik icerik YASAK.

Verilen kurallara KESINLIKLE uy."""


# ============================================================================
# HTML QUESTION GENERATOR
# ============================================================================


class HTMLQuestionGenerator(BaseQuestionGenerator):
    """
    Generator that uses LLM to produce HTML directly from template.

    The template's html_template field provides the HTML structure,
    and the LLM fills in the placeholders based on template rules.
    """

    @property
    def format_id(self) -> str:
        return "llm_generated_html"

    async def generate(
        self,
        template: "QuestionTemplate",
        topic: str,
        client: "GeminiClient",
        grade: int,
        subject: str = "turkce",
        cache_name: str | None = None,
        paragraph_model: str = "gemini-3-flash-preview",
        question_model: str = "gemini-3-flash-preview",
        validation_feedback: str | None = None,
        stem_text: str | None = None,
        stem_metadata: dict[str, str | int | None] | None = None,
        target_missing_element: str | None = None,
    ) -> GeneratorOutput:
        """
        Generate a complete question (paragraph + question).

        Delegates to generate_paragraph() and generate_question().

        target_missing_element: For `hikaye_unsurlari_yoktur` templates, forces
        which element (Yer/Zaman/Kisi) the paragraph must omit so the correct
        answer rotates deterministically across the batch.
        """
        logger.info(f"[HTML_GENERATOR] Generating {template.meta.id} for: {topic[:50]}...")

        # Step 1: Generate paragraph (if required)
        paragraph_text = ""
        paragraph_result = None

        if template.format.paragraph.required:
            logger.info("[HTML_GENERATOR] Generating paragraph...")
            paragraph_result = await self.generate_paragraph(
                template=template,
                topic=topic,
                subject=subject,
                grade=grade,
                client=client,
                cache_name=cache_name,
                model=paragraph_model,
                target_missing_element=target_missing_element,
            )
            paragraph_text = paragraph_result.paragraph
        else:
            logger.info("[HTML_GENERATOR] Skipping paragraph (inverse format)")

        # Step 2: Generate question
        output = await self.generate_question(
            template=template,
            topic=topic,
            paragraph=paragraph_text,
            client=client,
            grade=grade,
            subject=subject,
            cache_name=cache_name,
            question_model=question_model,
            validation_feedback=validation_feedback,
            stem_text=stem_text,
            stem_metadata=stem_metadata,
            target_missing_element=target_missing_element,
        )

        # Overlay paragraph metadata from paragraph_result
        if paragraph_result:
            output.key_concepts = paragraph_result.key_concepts
            output.difficulty_level = paragraph_result.difficulty_level
            output.curriculum_source = paragraph_result.curriculum_source
            output.curriculum_reasoning = paragraph_result.reasoning

        return output

    # ========================================================================
    # PARAGRAPH GENERATION
    # ========================================================================

    async def generate_paragraph(
        self,
        template: "QuestionTemplate",
        topic: str,
        subject: str,
        grade: int,
        client: "GeminiClient",
        cache_name: str | None = None,
        model: str = "gemini-3-flash-preview",
        target_missing_element: str | None = None,
    ) -> ParagraphOutput:
        """Generate paragraph using template.format.paragraph config."""
        prompt = self._build_paragraph_prompt(
            template, topic, subject, grade,
            target_missing_element=target_missing_element,
        )

        logger.info(f"[HTML_GENERATOR] Generating paragraph for: {template.meta.id}")
        logger.debug(
            f"[PARAGRAPH PROMPT]\n{'='*80}\n"
            f"Template: {template.meta.id}\n"
            f"Topic: {topic}\n"
            f"Subject: {subject}, Grade: {grade}\n"
            f"Model: {model}, Cache: {cache_name or 'none'}\n"
            f"{'-'*80}\n{prompt}\n{'='*80}"
        )

        if cache_name:
            result = await client.generate(
                model=model,
                prompt=prompt,
                output_schema=ParagraphOutput,
                cache_name=cache_name,
            )
        else:
            result = await client.generate(
                model=model,
                prompt=prompt,
                output_schema=ParagraphOutput,
                system_instruction=PARAGRAPH_SYSTEM_PROMPT,
            )

        logger.debug(
            f"[PARAGRAPH OUTPUT]\n{'='*80}\n"
            f"Paragraph ({len(result.paragraph.split())} words):\n{result.paragraph}\n\n"
            f"Key concepts: {result.key_concepts}\n"
            f"Difficulty: {result.difficulty_level}\n"
            f"Curriculum source: {result.curriculum_source}\n"
            f"Reasoning: {result.reasoning}\n{'='*80}"
        )

        return result

    def _build_multi_paragraph_prompt(
        self,
        template: "QuestionTemplate",
        topic: str,
        subject: str,
        grade: int,
    ) -> str:
        """Build prompt for multi-paragraph (2-text comparison) generation."""
        para_config = template.format.paragraph
        rules = para_config.kurallar
        min_words = para_config.word_count_min
        max_words = para_config.word_count_max
        labels = para_config.labels or ["1. Metin", "2. Metin"]

        rules_text = "\n".join(f"  - {rule}" for rule in rules) if rules else "  - Bilgilendirici paragraflar yaz"

        return f"""Asagidaki konu hakkinda IKI AYRI metin yaz:

KONU: {topic}
KAYNAK DERS: {subject}
SINIF SEVIYESI: {grade}. sinif

COKLU METIN FORMATI:
- Tam olarak 2 metin olustur
- Her metin {min_words}-{max_words} kelime arasinda olmali
- Metinleri su etiketlerle ayir:

{labels[0]}:
[ilk metin icerigi]

{labels[1]}:
[ikinci metin icerigi]

OZEL KURALLAR (Bu template icin):
{rules_text}

GENEL KURALLAR:
1. {grade}. sinif ogrencisinin anlayabilecegi kelimeler kullan
2. Bilimsel olarak dogru bilgiler ver
3. Turkce dilbilgisi kurallarina dikkat et
4. Her metin bagimsiz ve anlasilir olmali
5. "paragraph" alanina her iki metni etiketleriyle birlikte BIRLESIK olarak yaz
6. Metinlerde SORU CUMLESI YASAK — soru isareti (?) iceren cumle OLMAMALI! Tum cumleler bilgilendirici/anlatisal olmali."""

    # ========================================================================
    # QUESTION GENERATION (stem + options from paragraph)
    # ========================================================================

    async def generate_question(
        self,
        template: "QuestionTemplate",
        topic: str,
        paragraph: str,
        client: "GeminiClient",
        grade: int,
        subject: str = "turkce",
        cache_name: str | None = None,
        question_model: str = "gemini-3-flash-preview",
        validation_feedback: str | None = None,
        stem_text: str | None = None,
        stem_metadata: dict[str, str | int | None] | None = None,
        target_missing_element: str | None = None,
    ) -> GeneratorOutput:
        """
        Generate only the question component (stem + options) from a given paragraph.

        Args:
            template: QuestionTemplate with question rules
            topic: Topic string
            paragraph: Pre-generated paragraph text
            client: GeminiClient for API calls
            grade: Target grade level
            subject: Subject code
            cache_name: Optional cache name for PDF grounding
            question_model: Model to use for question generation
            validation_feedback: Optional feedback from previous validation failure

        Returns:
            GeneratorOutput with question, options, and default paragraph metadata
        """
        is_inverse = not template.format.paragraph.required

        logger.info("[HTML_GENERATOR] Generating question...")
        logger.debug(
            f"[QUESTION GEN START]\n{'='*80}\n"
            f"Template: {template.meta.id}\n"
            f"Topic: {topic}\n"
            f"Is inverse: {is_inverse}\n"
            f"Option style: {template.format.options.style}\n"
            f"Paragraph:\n{paragraph}\n"
            f"Validation feedback:\n{validation_feedback or 'none'}\n"
            f"{'='*80}"
        )
        prompt = self._build_html_prompt(
            template,
            paragraph,
            topic,
            grade,
            validation_feedback,
            stem_override=stem_text,
            target_missing_element=target_missing_element,
        )

        # Determine system prompt: use beceri prompt for beceri templates (BeceriConfig, not plain dict)
        from ..templates.schema import BeceriConfig
        is_beceri = isinstance(getattr(template, 'beceri', None), BeceriConfig)
        system_prompt = BECERI_SYSTEM_PROMPT if is_beceri else get_html_generation_system_prompt(grade)

        # Use cache if available for consistent MEB content
        if cache_name and not is_inverse:
            output = await client.generate(
                model=question_model,
                prompt=prompt,
                output_schema=HTMLOutput,
                cache_name=cache_name,
            )
        else:
            output = await client.generate(
                model=question_model,
                prompt=prompt,
                output_schema=HTMLOutput,
                system_instruction=system_prompt,
            )

        # Build options dynamically based on template labels
        labels = template.format.options.labels  # ["A","B","C","D"] or ["A","B","C","D","E"]

        # Log raw question output
        option_log_lines = "\n".join(
            f"Option {l}: {getattr(output, f'option_{l.lower()}', '')}" for l in labels
        )
        strategy_log_lines = "\n".join(
            f"Strategy {l}: {getattr(output, f'option_{l.lower()}_strategy', '')} — "
            f"{getattr(output, f'option_{l.lower()}_reasoning', '')}" for l in labels
        )
        logger.debug(
            f"[QUESTION OUTPUT]\n{'='*80}\n"
            f"Question: {output.question}\n"
            f"Key word: {output.key_word}\n"
            f"Correct answer: {output.correct_answer}\n"
            f"{option_log_lines}\n"
            f"{strategy_log_lines}\n"
            f"Titles paragraph: {output.titles_paragraph or '(none)'}\n"
            f"Statements: I={output.statement_I or '-'}, II={output.statement_II or '-'}, "
            f"III={output.statement_III or '-'}, IV={output.statement_IV or '-'}\n"
            f"{'='*80}"
        )

        # Package output dynamically
        options = {}
        option_reasoning = {}
        for label in labels:
            options[label] = getattr(output, f"option_{label.lower()}", "")
            option_reasoning[label] = {
                "strategy": getattr(output, f"option_{label.lower()}_strategy", ""),
                "reasoning": getattr(output, f"option_{label.lower()}_reasoning", ""),
            }

        # For inverse title format, use titles_paragraph
        final_paragraph = paragraph
        if is_inverse and output.titles_paragraph:
            final_paragraph = output.titles_paragraph

        # For numbered format, embed statements into question if {statements} present
        final_question = output.question
        opt_style = template.format.options.style
        _tmpl_id = getattr(getattr(template, "meta", None), "id", "") or ""
        _use_arabic_nums = (
            "paragraf_olusturma_sinif2" in _tmpl_id
            or "yardimci_fikir_numarali_sinif4" in _tmpl_id
        )
        if opt_style == "roman_numeral_combination" and output.statement_I:
            # Strip any leading number prefix that LLM may have added (e.g., "1. ..." → "...")
            def _strip_num_prefix(s: str) -> str:
                if not s:
                    return s
                return re.sub(r'^\s*(?:[1-4IV]+\s*[.)]\s*)+', '', s).strip()
            s1 = _strip_num_prefix(output.statement_I)
            s2 = _strip_num_prefix(output.statement_II)
            s3 = _strip_num_prefix(output.statement_III)
            s4 = _strip_num_prefix(output.statement_IV)
            if _use_arabic_nums:
                statements_text = (
                    f"1. {s1}<br>"
                    f"2. {s2}<br>"
                    f"3. {s3}<br>"
                    f"4. {s4}"
                )
            else:
                statements_text = (
                    f"I. {s1}<br>"
                    f"II. {s2}<br>"
                    f"III. {s3}<br>"
                    f"IV. {s4}"
                )
            if "{statements}" in final_question:
                # Ensure <br> before and after statements block
                final_question = final_question.replace(
                    "{statements}", f"<br>{statements_text}<br>"
                )
            final_question = final_question.replace("\n", "<br>")
            # Clean up duplicate <br> tags from double insertion
            while "<br><br>" in final_question:
                final_question = final_question.replace("<br><br>", "<br>")

        # Arabic-numeral normalization:
        # (a) For paragraf_olusturma_sinif2: strip Roman statement block from question
        #     (paragraph already has numbered sentences).
        # (b) For all _use_arabic_nums templates: convert any Roman labels (in question
        #     and options) to Arabic digits.
        if _use_arabic_nums:
            _is_olusturma = "paragraf_olusturma_sinif2" in _tmpl_id
            if _is_olusturma:
                # Strip duplicate statement block: truncate at first "<br>I. " occurrence
                _stmt_match = re.search(r"<br>\s*(?:I|II|III|IV)\.\s", final_question)
                if _stmt_match:
                    final_question = final_question[: _stmt_match.start()].rstrip()
            _roman_to_arabic = [("IV", "4"), ("III", "3"), ("II", "2"), ("I", "1")]
            def _convert_roman(text: str) -> str:
                if not text:
                    return text
                for roman, arabic in _roman_to_arabic:
                    text = re.sub(rf"(?<![A-Za-z]){re.escape(roman)}(?![A-Za-z])", arabic, text)
                return text
            # Convert in options
            options = {k: _convert_roman(v) for k, v in options.items()}
            # For numarali_sinif4: convert Roman numerals in question text too
            if not _is_olusturma:
                final_question = _convert_roman(final_question)

        # Safeguard: strip any leading paragraph-like text that LLM embedded before the stem.
        # Only applies to NON-numbered, NON-multi-paragraph templates.
        # Numbered templates intentionally put statements (1./2./3./4.) before <b>Soru?</b>.
        if opt_style != "roman_numeral_combination":
            _first_b = final_question.find("<b>")
            if _first_b > 30:  # only strip if >30 chars of pre-<b> text (likely full paragraph)
                pre = final_question[:_first_b].strip()
                # If pre-text is substantial (looks like a paragraph), drop it
                if len(pre) > 40 and "." in pre:
                    final_question = final_question[_first_b:].strip()

        return GeneratorOutput(
            paragraph=final_paragraph,
            key_concepts=[topic],
            difficulty_level="orta",
            question=final_question,
            key_word=output.key_word or "hangisidir",
            options=options,
            correct_answer=output.correct_answer,
            option_reasoning=option_reasoning,
            template_id=template.meta.id,
            format_id="llm_generated_html",
            answer_explanation=getattr(output, "answer_explanation", "") or "",
            skill_tag=getattr(output, "skill_tag", "") or "",
            shared_visual_format=getattr(output, "shared_visual_format", "") or "",
            selected_stem_index=(
                int(stem_metadata["selected_stem_index"])
                if stem_metadata and stem_metadata.get("selected_stem_index") is not None
                else None
            ),
            selected_stem_text=stem_text or "",
            stem_source=str(stem_metadata.get("stem_source", "")) if stem_metadata else "",
            stem_reservation_id=(
                str(stem_metadata["stem_reservation_id"])
                if stem_metadata and stem_metadata.get("stem_reservation_id")
                else None
            ),
            stem_reservation_status=(
                str(stem_metadata.get("stem_reservation_status", ""))
                if stem_metadata
                else ""
            ),
        )

    def _build_paragraph_prompt(
        self,
        template: "QuestionTemplate",
        topic: str,
        subject: str,
        grade: int,
        target_missing_element: str | None = None,
    ) -> str:
        """Build prompt for paragraph generation."""
        para_config = template.format.paragraph
        rules = para_config.kurallar
        style = para_config.stil
        min_words = para_config.word_count_min
        max_words = para_config.word_count_max
        min_sentences = getattr(para_config, 'sentence_count_min', None)
        max_sentences = getattr(para_config, 'sentence_count_max', None)

        rules_text = "\n".join(f"  - {rule}" for rule in rules) if rules else "  - Bilgilendirici bir paragraf yaz"

        style_map = {
            "tartismaci": "Tartismaci/goruslu bir paragraf yaz - bir tez savun",
            "bilgilendirici": "Bilgilendirici/ders kitabi tarzi bir paragraf yaz",
            "hikaye": "Hikaye tarzi, gercek hayat ornegi iceren bir paragraf yaz",
            "karisik": "Bilgilendirici ve hikaye karisimi bir paragraf yaz",
            "betimleyici": "Betimleyici/tasvirci bir paragraf yaz - duyusal detaylar kullan",
            "senaryo": "Gercek hayat senaryosu olustur - somut bir durum/olay anlat, karakterler ve mekan belirt",
            "diyalog": "Iki veya daha fazla kisi arasinda dogal bir konusma yaz - konusmacilarin adlarini belirt. ONEMLI: Her yeni konusmacinin sozune gecerken <br> etiketi kullan. Ornek: 'Ayse: Bence...<br>Mehmet: Katiliyorum ama...<br>Ayse: Evet, haklisin.'",
            "siir": "Siir/manzume biciminde yaz - dizeler halinde, kafiye ve olcu kullan",
            "mektup": "Mektup formati kullan - hitap, govde ve kapaniis cumlesi ile yaz",
            "haber": "Gazete haberi tarzi nesnel bir paragraf yaz",
            "tablo": "Konuyla ilgili verileri HTML <table> formatinda olustur. TABLO FORMATI: Tablo basligini tablonun UZERINDE duz metin olarak yaz, ardindan <table><thead><tr><th>Baslik1</th><th>Baslik2</th></tr></thead><tbody><tr><td>Veri1</td><td>Veri2</td></tr></tbody></table> seklinde tablo olustur. 3-6 veri satiri, 2-4 sutun olmali. Veriler sayisal ve karsilastirmaya uygun olmali.",
            "infografik": "Konuyla ilgili verileri HTML yatay cubuk grafik formatinda olustur. GRAFIK FORMATI: Grafik basligini grafigin UZERINDE duz metin olarak yaz, ardindan <div class=\"chart\"> konteyneri icinde her veri satiri icin <div class=\"chart-row\"><span class=\"chart-label\">Etiket</span><span class=\"chart-bar\" style=\"width:XX%\"></span><span class=\"chart-val\">Deger</span></div> seklinde grafik olustur. 4-6 veri satiri olmali. En buyuk deger width:100%, digerleri oranli. Veriler sayisal ve karsilastirmaya uygun olmali.",
        }
        style_instruction = style_map.get(style, style_map["bilgilendirici"])

        # Check for multi-paragraph
        para_count = getattr(para_config, "count", 1) or 1
        if para_count > 1:
            return self._build_multi_paragraph_prompt(template, topic, subject, grade)

        # Check for numbered sentences
        numbered_sentences = getattr(para_config, "numbered_sentences", False)
        numbered_instruction = ""
        if numbered_sentences:
            # Use Arabic numerals for paragraf_olusturma_sinif2 templates; Roman for others
            _tmpl_id = getattr(getattr(template, "meta", None), "id", "") or ""
            _use_arabic = "paragraf_olusturma_sinif2" in _tmpl_id
            if _use_arabic:
                numbered_instruction = """
NUMARALAMA KURALLARI (KRITIK!):
- Cumleler ARAP RAKAMLARIYLA numaralanmali: 1., 2., 3., 4.
- Roma rakami (I, II, III) KULLANMA — SADECE Arap rakami!
- Bu numaralar cumlelerin DOGRU sirasini DEGIL, sadece rastgele etiketini gosterir
- Once orijinal paragrafi dogru sirada planla, sonra her cumleye rastgele Arap numarasi ata
- Ogrenciye cumleler numara sirasinda gosterilir: 1., 2., 3., 4.
- Her cumleyi ayri satirda yaz ve <br> ile ayir (ornek: "1. ...<br>2. ...<br>3. ...<br>4. ...")
- SADECE numarali cumleleri uret — soru veya secenek YAZMA, onlar ayri uretilecek!
- Paragraftaki metni TEKRARLAMA — tek seferlik yaz, duplicate YASAK!
"""
            else:
                numbered_instruction = """
NUMARALAMA KURALLARI (KRITIK!):
- Cumleler ROMA RAKAMLARIYLA numaralanmali: (I), (II), (III), (IV), (V)
- Arap rakami (1, 2, 3) KULLANMA — SADECE Roma rakami!
- Bu numaralar cumlelerin DOGRU sirasini DEGIL, sadece rastgele etiketini gosterir
- Once orijinal paragrafi dogru sirada planla, sonra her cumleye rastgele Roma numarasi ata
- Ogrenciye cumleler numara sirasinda gosterilir: (I), (II), (III), (IV), (V)
- SADECE numarali cumleleri uret — soru veya secenek YAZMA, onlar ayri uretilecek!
- Paragraftaki metni TEKRARLAMA — tek seferlik yaz, duplicate YASAK!
"""

        # Pick a random diversity angle for variety
        diversity_angles = [
            "Gercek hayattan bir ORNEK ile baslayan bir paragraf yaz (bir cocuk, aile, okul ortami).",
            "SEBEP-SONUC iliskisi uzerine kurulu bir paragraf yaz (X oldugu icin Y olur).",
            "KARSILASTIRMA iceren bir paragraf yaz (iki kavram, iki durum, iki donemi kiyasla).",
            "Kisa bir OLAY/ANEKDOT ile baslayan sonra bilgi veren bir paragraf yaz.",
            "TANIMLAMA ve ACIKLAMA odakli bir paragraf yaz (kavramlari tanimla, ornekle).",
            "KRONOLOJIK SIRALAMA ile bir sureci anlatan bir paragraf yaz (once, sonra, en son).",
            "GOZLEM ve DENEYIM aktaran bir paragraf yaz (bir ogrencinin gozunden).",
            "Bir OLGUNUN FARKLI YONLERINI ele alan bir paragraf yaz (bir yandan... diger yandan...).",
        ]
        import random as _rnd
        diversity_hint = _rnd.choice(diversity_angles)

        # Dual-source rule if this is an answer-critical (Bolum 7) template
        _dual_source_para = ""
        if getattr(template, "visual_requirement", None) == "answer_critical":
            _dual_source_para = """
CIFT-KAYNAK PARAGRAF KURALLARI (KRITIK — BU SORU GORSELE BAGLI!):
- Paragraf dogru cevabi DOGRUDAN VERMEMELI. Sadece baglam/ipucu sunmali.
- Paragrafta "... anlamina gelir", "bu isaret ... gosterir", "sembol ... demektir" gibi acik cevaplama YASAK.
- Paragrafta kategori/alan bilgisi olabilir (orn: "Kitabimizda farkli islemler icin farkli isaretler var") ama dogru cevaba tek basina goturen detay YAZILMAMALI.
- TEST: Sadece paragrafi okuyan ogrenci dogru cevabi KESIN secemeyecek sekilde 2+ secenek arasinda kalmali.
"""

        # Inject target missing element directive for hikaye_unsurlari_yoktur
        _target_missing_block_text = ""
        if target_missing_element and "hikaye_unsurlari_yoktur" in (getattr(getattr(template, "meta", None), "id", "") or ""):
            _target_missing_block_text = (
                f"\n\n## ★★★ HEDEF EKSIK UNSUR (ZORUNLU) ★★★\n"
                f"Bu paragrafta **{target_missing_element}** unsuru EKSIK olmak ZORUNDA.\n"
                f"- Paragrafta {target_missing_element} ile ilgili HIÇBIR bilgi verme (ad, tarif, ima, zaman dilimi, mekân adi — yok).\n"
                f"- Diger 3 unsur (Olay + kalan iki unsur) NET ve acikca paragrafta bulunsun.\n"
                f"- Bu kural KESINDIR: dogru cevap = {target_missing_element} olacak."
            )

        return f"""Asagidaki konu hakkinda bir egitici paragraf yaz:

KONU: {topic}
KAYNAK DERS: {subject}
SINIF SEVIYESI: {grade}. sinif

PARAGRAF STILI: {style_instruction}

CESITLILIK TALIMATI (ONEMLI!):
{diversity_hint}
Paragrafin diger paragraflardan FARKLI bir yaklasim, bakis acisi ve ornek secimi olmali.
Klise ve kalip ifadelerden kacin. Her paragraf OZGUN olmali.

UZUNLUK: {min_words}-{max_words} kelime{f', {min_sentences}-{max_sentences} cumle' if min_sentences and max_sentences else ''} (bu araliklarda KAL!)
{numbered_instruction}
{_dual_source_para}
OZEL KURALLAR (Bu template icin):
{rules_text}

GENEL KURALLAR:
1. {grade}. sinif ogrencisinin anlayabilecegi kelimeler kullan
2. Bilimsel olarak dogru bilgiler ver
3. Turkce dilbilgisi kurallarina dikkat et
4. Paragraf bagimsiz ve anlasilir olmali
5. Paragrafta SORU CUMLESI YASAK — "Hic dusundunuz mu?", "Neden boyledir?", "Peki ya...?" gibi soru cumleleri HICBIR YERDE kullanma. Paragraf tamamen bilgilendirici/anlatisal cumlelerden olusmali. Soru isareti (?) iceren cumle OLMAMALI!
6. Karakter kullaniyorsan Kerem, Elif, Ali, Ayse, Mehmet, Fatma gibi sik tekrarlanan isimleri KULLANMA — cesitli isimler sec
7. Paragraftan SONRA "Bu metin bize ... anlatiyor" gibi ACIKLAYICI/OZET cumleler EKLEME — paragraf tek blok olmali{_target_missing_block_text}"""

    # ========================================================================
    # HTML PROMPT BUILDING
    # ========================================================================

    @staticmethod
    def _extract_concept_from_definition(text: str) -> str | None:
        """Extract short concept name from Turkish definition sentences.

        Handles patterns like:
        - "...geometrik şekle çember denir" → "çember"
        - "...iki açıya bütünler açılar denir" → "bütünler açılar"
        - "...doğru parçasına köşegen denir" → "köşegen"
        - "...parçasına ışın adı verilir" → "ışın"

        Algorithm: find "denir"/"denilir"/"adı verilir" keyword, take word(s)
        immediately before it. If the word 2 positions back does NOT end in a
        Turkish dative suffix (-e/-a), include it as part of the concept name.
        """
        words = text.split()

        # Find keyword position: "denir", "denilir", or "adı ... verilir"
        key_idx = None
        for i, w in enumerate(words):
            w_clean = w.rstrip(",.;:!?").lower()
            if w_clean in ("denir", "denilir"):
                key_idx = i
                break
            if (
                w_clean == "adı"
                and i + 1 < len(words)
                and words[i + 1].rstrip(",.").lower() == "verilir"
            ):
                key_idx = i
                break

        if key_idx is None or key_idx < 1:
            return None

        # Build concept backwards from keyword: include words that are NOT
        # dative-suffixed (Turkish dative nouns end in -e/-a)
        parts: list[str] = [words[key_idx - 1]]

        for offset in range(2, min(key_idx + 1, 4)):  # check up to 3 words back
            prev = words[key_idx - offset].rstrip(",.;:!?")
            if not prev or prev[-1].lower() in ("e", "a"):
                break  # dative word — stop extending
            parts.insert(0, prev)

        concept = " ".join(parts)
        if 1 <= len(concept.split()) <= 3:
            return concept
        return None

    def _apply_sentence_case(self, text: str) -> str:
        """Apply sentence case: first letter uppercase, rest lowercase."""
        if len(text) > 1:
            return text[0].upper() + text[1:].lower()
        return text.upper() if text else text

    def _extract_leaf_topic(self, full_topic: str) -> str:
        """
        Extract short concept name from full topic path for use in question stems.

        For hierarchical topics like:
            "GEOMETRİK ŞEKİLLER / Açı / Bütünler Açılar / Ölçüleri toplamı 180° olan iki açıya bütünler açılar denir"
        Returns: "Bütünler açılar" (not the full definition sentence)

        Strategy:
        1. If leaf is short (≤ 5 words) → use as-is
        2. If leaf contains "X denir" / "X adı verilir" → extract concept name
        3. Otherwise → fall back to parent level (parts[-2])
        """
        if " / " not in full_topic:
            return self._apply_sentence_case(full_topic) if full_topic else full_topic

        parts = full_topic.split(" / ")
        leaf = parts[-1].strip()

        # Short leaf (≤4 words) — use directly
        if len(leaf.split()) <= 4:
            return self._apply_sentence_case(leaf)

        # Long leaf — try extracting concept from definition pattern
        concept = self._extract_concept_from_definition(leaf)
        if concept:
            return self._apply_sentence_case(concept)

        # Fall back to parent level (alt konu adı)
        if len(parts) >= 3:
            parent = parts[-2].strip()
            return self._apply_sentence_case(parent)

        return self._apply_sentence_case(leaf)

    def _build_rules_block(self, stem: str) -> str:
        """Build concise rules block shared by all prompt builders."""
        return f"""## KURALLAR
DOGRU CEVAP: Paragraftaki kelimelerin AYNILARINI kullan — es anlamli/parafraz YASAK! Dogru cevap paragraftaki ifadelerle AYNI kelimeleri kullanmali. "yardim"→"destek", "onemli"→"degerli" gibi es anlam degisiklikleri YAPMA!
CELDIRICILER: (1) En az 1 tane COK YAKIN. (2) Direkt elenebilir sik YASAK. (3) Ayni alan.
STRATEJI: ONCE sec → SONRA acikla → EN SON yaz. Dogru cevap = "DOGRU_CEVAP".
KOMBINASYON: En az 1 celdiricide 2 strateji kombine et.
ANLAMSAL AGIRLIK: Tum secenekler ayni soyutluk seviyesinde.
SORU KOKU (KESIN YASAK — DEGISTIRME!): Asagidaki soru kokunu question_stem alanina BIREBIR KOPYALA. Tek bir harf bile degistirme, ekleme, cikarma YASAK. HTML etiketleri (<b>, <u>) dahil HER SEYI koru. Kendi soru kokunu YAZMA — sadece KOPYALA:
{stem}
ANAHTAR SOZCUK: <u> icindeki kelimeyi key_word alanina yaz. Yoksa "hangisidir".
ALTI CIZGI KURALI (KRITIK!): <u> etiketi YALNIZCA olumsuz/disleyici kelimeler icin: olamaz, degildir, yer almaz, getirilemez, yoktur, beklenemez, cikarilmaz, soylenemez, bulunmaz. POZITIF kelimelerde (dogrusu, en uygun, hangisidir, verilmistir) <u> KULLANMA — validation FAIL olur!
CESITLILIK: Seceneklerin baslangic kelimelerini FARKLI yap. Hicbir iki secenek %80'den fazla benzer OLMAMALI (kopya-yapistir YASAK).
UZUNLUK DENGESI (KRITIK!): Dogru cevap diger seceneklerden UZUN veya KISA OLMAMALI. Tum secenekler ±1 kelime farkla ayni uzunlukta olmali. Dogru cevabi DETAYLANDIRMA, celdiricileri de ayni detayda yaz. KESIN YASAK: Dogru cevap EN UZUN secenek OLAMAZ!
YASAK SECENEKLER: "Hepsi", "Hiçbiri", "Yukarıdakilerin hepsi/hiçbiri" gibi seçenekler URETME. Her seçenek özgün olmalı.
MUTLAK İFADE YASAĞI: Soru kökünde "her zaman", "asla", "kesinlikle", "mutlaka", "daima", "hiçbir zaman" gibi mutlak ifadeler KULLANMA.
DIL YAPISI ESITLIGI (KRITIK!): 4 secenek AYNI dilbilgisel yapida olmali. Hepsi isim tamlamasi VEYA hepsi cumle VEYA hepsi sifat+isim. Bir secenek cumle digerleri tek kelime → FAIL.
CELDIRICI KALITE KURALLARI:
- Her celdirici FARKLI hata turunu temsil etmeli. Ayni soru icinde baskin hata tekrarlanmamali.
- Hicbir celdirici metin disi bilgi icermemeli — sadece metindeki baglama dayanmali.
- Uzunluk farki ±1 kelimeyi gecmemeli (tum secenekler arasi).
- Her celdirici merkez kavram ailesinden en az bir anahtar kelime icermeli.
- Seceneklerin retorik agirligi esit olmali: dogru cevap yalin dille yazildiysa celdiricileri akademik terimlerle susleme.
- Kaliteli celdirici = metin okunmadan elenemeyen sik. Hata, dis dunyadaki genel dogrularla celismemeli, SADECE metindeki baglamla celismeli.
- Sayisal verilerle yapilan yorum tamamen kopuk olmamali, zayif da olsa iliski korunmali.
PARAGRAF SONRASI YASAK: Paragraftan sonra "Bu metin bize ... anlatiyor", "Bu metinde ... gorulmektedir", "Bu paragrafta ... anlatilmaktadir" gibi ACIKLAYICI/OZET cumleler EKLEME. Paragraf TEK BLOK olarak kalmali, altina yorum veya aciklama YAZMA!
GENEL: Rastgele dogru sik. "question" = SADECE soru cumlesi. Soru koku TEK SATIRDA olmali (\n YASAK)."""

    def _build_html_prompt(
        self,
        template: "QuestionTemplate",
        paragraph: str,
        topic: str,
        grade: int,
        validation_feedback: str | None = None,
        stem_override: str | None = None,
        target_missing_element: str | None = None,
    ) -> str:
        """Build prompt for HTML question generation."""
        # Determine question type for hints
        template_id = template.meta.id.lower()

        # Get stem using balanced selection
        stem = stem_override or template.get_random_stem(
            template_id=template_id,
        )
        logger.debug(f"[STEM] Selected stem for {template_id}")

        # Handle inverse format: replace {topic} placeholder with LEAF topic
        stem = self._resolve_stem_with_topic(stem, topic)
        is_inverse = not template.format.paragraph.required
        opt_style = template.format.options.style

        # Build correct answer section
        correct_section = self._format_correct_answer_section(template)

        # Build distractor strategies section
        distractor_section = self._format_distractor_section(template)

        # Build option constraints section
        option_constraints = self._format_option_constraints(template)

        # Check if this is a beceri temelli template (BeceriConfig, not plain dict)
        from ..templates.schema import BeceriConfig
        is_beceri = isinstance(getattr(template, 'beceri', None), BeceriConfig)

        # Determine paragraph count for routing
        para_count = getattr(template.format.paragraph, "count", 1) or 1

        # Build the main prompt — routing logic
        _visual_req = getattr(template, "visual_requirement", None)
        _hide_para = getattr(template, "hide_paragraph_after_visual", False)

        if opt_style == "image_description":
            prompt = self._build_image_options_prompt(
                template, paragraph, stem, topic, grade, correct_section, distractor_section, option_constraints
            )
        elif _visual_req == "answer_critical" and _hide_para:
            # Visual-only questions (e.g., 7.2 gorsel_inceleme):
            # paragraph is a scene description, question must test visual observation
            prompt = self._build_visual_only_prompt(
                template, paragraph, stem, topic, grade, correct_section, distractor_section, option_constraints
            )
        elif is_beceri:
            prompt = self._build_beceri_prompt(
                template, paragraph, stem, topic, grade, correct_section, distractor_section, option_constraints
            )
        elif opt_style == "roman_numeral_combination" and para_count > 1:
            prompt = self._build_multi_paragraph_numbered_prompt(
                template, paragraph, stem, topic, grade, correct_section, distractor_section, option_constraints
            )
        elif opt_style == "roman_numeral_combination":
            prompt = self._build_numbered_html_prompt(
                template, paragraph, stem, topic, grade, correct_section, distractor_section, option_constraints
            )
        elif is_inverse and (template.format.topic_in_stem or template.format.titles_in_stem):
            prompt = self._build_inverse_html_prompt(
                template, stem, topic, grade, correct_section, distractor_section, option_constraints
            )
        elif is_inverse:
            prompt = self._build_generic_inverse_prompt(
                template, stem, topic, grade, correct_section, distractor_section, option_constraints
            )
        elif para_count > 1:
            prompt = self._build_multi_paragraph_standard_prompt(
                template, paragraph, stem, topic, grade, correct_section, distractor_section, option_constraints
            )
        else:
            prompt = self._build_standard_html_prompt(
                template, paragraph, stem, topic, grade, correct_section, distractor_section, option_constraints
            )

        # Append validation feedback if this is a retry
        if validation_feedback:
            prompt += self._format_validation_feedback_section(validation_feedback)
            logger.debug(
                f"[RETRY FEEDBACK APPENDED]\n{'='*80}\n"
                f"Feedback ({len(validation_feedback)} chars):\n{validation_feedback}\n"
                f"{'='*80}"
            )

        logger.debug(
            f"[QUESTION PROMPT BUILT]\n{'='*80}\n"
            f"Route: {'multi_para_numbered' if opt_style == 'roman_numeral_combination' and para_count > 1 else 'numbered' if opt_style == 'roman_numeral_combination' else 'generic_inverse' if is_inverse and not (template.format.topic_in_stem or template.format.titles_in_stem) else 'inverse' if is_inverse else f'multi_para({para_count})' if para_count > 1 else 'standard'}\n"
            f"Stem: {stem}\n"
            f"Total prompt length: {len(prompt)} chars\n"
            f"{'-'*80}\n"
            f"FULL PROMPT:\n{prompt}\n"
            f"{'='*80}"
        )

        # Inject per-question target element hint for hikaye_unsurlari_yoktur
        if target_missing_element and "hikaye_unsurlari_yoktur" in template_id:
            prompt += (
                f"\n\n## ★★★ HEDEF EKSIK UNSUR (ZORUNLU) ★★★\n"
                f"Bu soru icin paragrafta **{target_missing_element}** unsuru EKSIK olacak.\n"
                f"- Dogru cevap = **{target_missing_element}** olmak ZORUNDA.\n"
                f"- Diger 3 secenek (Olay + kalan iki unsur) paragrafta NET biçimde bulunmali.\n"
                f"- Bu kural KESINDIR — baska hiçbir unsuru dogru cevap olarak seçme.\n"
            )

        return prompt

    def _build_visual_only_prompt(
        self,
        template: "QuestionTemplate",
        paragraph: str,
        stem: str,
        topic: str,
        grade: int,
        correct_section: str,
        distractor_section: str,
        option_constraints: str,
    ) -> str:
        """Build prompt for visual-only questions (e.g., 7.2 gorsel_inceleme).

        The paragraph is a SCENE DESCRIPTION used internally — it will NOT be shown
        to the student. The student sees ONLY the generated visual + question + options.
        Question must test VISUAL OBSERVATION, not text comprehension.
        """
        visual_spec = getattr(template, "visual_spec", {}) or {}
        visual_type = getattr(template, "visual_type", "scene")

        return f"""{template.meta.ad} sorusu olustur:

## KONU
{topic}

## GORSEL SAHNE TASVIRI (dahili — ogrenciye gosterilmeyecek)
Asagidaki tasvire uygun bir gorsel uretilecek. Bu tasviri TEMEL ALARAK soru olustur.
{paragraph}

## KRITIK: GORSEL-ODAKLI SORU KURALLARI
Bu soru tipinde ogrenci SADECE bir GORSELE bakarak soruyu cozecek.
Paragraf/metin GOSTERILMEYECEK — ogrenci sadece gorseli gorecek.

ONEMLI KURALLAR:
1. Soru GORSEL GOZLEM testlemeli: sayma, detay fark etme, konum belirleme, karsilastirma
2. Dogru cevap YALNIZ gorsele bakarak dogrulanabilmeli
3. Yanlis secenekler gorselle celismeli veya gorselden CIKARILMAYAN bilgi icermeli
4. "Metne gore", "paragrafta", "yaziya gore" gibi ifadeler KESINLIKLE YASAK
5. Secenekler gorselden gozlemlenebilir somut bilgilere dayanmali:
   - Kisi sayisi, cinsiyet, giysi, aksesuar (gozluk, sapka)
   - Nesne sayisi, renk, boyut, konum
   - Eylem (ne yapiyor), mevsim/hava ipuclari
   - Mekan detaylari (ic/dis, park/okul/ev)
6. Soyut yorum, duygu analizi, niyet okuma YASAK — sadece GORUNEN bilgiler

## SORU KOKU (BIREBIR KOPYALA — tek harf bile degistirme!)
{stem}

## SINIF SEVIYESI
{grade}. sinif

{self._build_rules_block(stem)}

{correct_section}

{distractor_section}

{option_constraints}"""

    def _build_standard_html_prompt(
        self,
        template: "QuestionTemplate",
        paragraph: str,
        stem: str,
        topic: str,
        grade: int,
        correct_section: str,
        distractor_section: str,
        option_constraints: str,
    ) -> str:
        """Build prompt for standard (paragraph-based) format."""
        rules = self._build_rules_block(stem)

        # Special instruction for numbered-sentence ordering questions
        numbered_sentences = getattr(
            template.format.paragraph, "numbered_sentences", False
        )
        # Detect if this is a B3 yapı yönü template
        _is_b3 = "paragraf_siralama" in (template.meta.id or "")

        _template_id = template.meta.id or ""
        _is_siralama = _template_id == "paragraf_siralama_siralama"
        _is_akis_bozan_numarali = _template_id == "paragraf_siralama_akis_bozan_numarali"

        siralama_warning = ""
        if numbered_sentences and _is_siralama:
            siralama_warning = """
## SIRALAMA SORUSU OZEL KURALLARI (KRITIK!)
- Paragraftaki Roma rakami ile numarali cumleler zaten KARISIK sirada verilmis — onlari TEKRARLAMA!
- Soru kokunde SADECE tek bir soru cumlesi yaz
- YASAK: Soru kokunde cumleleri dogru sirada veya herhangi sirada TEKRAR YAZMAK!
- YASAK: Paragraftaki metni bold/kalin yapip tekrar yazmak — DUPLICATE YASAK!
- Secenekler SADECE Roma rakami dizisi olmali: "III - I - V - II - IV" formati
- YASAK: Seceneklerde Arap rakami (1, 2, 3) kullanmak
- YASAK: Seceneklerde cumle metni yazmak
"""
        elif _is_akis_bozan_numarali:
            siralama_warning = """
## NUMARALI AKIS BOZAN / IKIYE BOLME SORUSU OZEL KURALLARI (KRITIK!)
- "question" alanina SADECE tek bir soru cumlesi yaz — paragraftaki metni TEKRARLAMA!
- Paragraftaki cumleler (I), (II), (III), (IV) biciminde ROMA RAKAMI ile numarali
- Secenekler SADECE Roma rakami olmali: A) I  B) II  C) III  D) IV
- YASAK: Seceneklerde cumle metnini yazmak — metinli sik YASAK!
- YASAK: Arap rakami (1, 2, 3) kullanmak
- Dogru cevap = ilgili cumlenin Roma numarasi
"""
        elif _is_b3:
            siralama_warning = """
## YAPI YONU SORUSU OZEL KURALLARI (KRITIK!)
- "question" alanina SADECE tek bir soru cumlesi yaz — SADECE SORU CUMLESI!
- KESIN YASAK: "question" alanina paragraf metnini YAZMA! Paragraf zaten ayri bir alanda veriliyor.
- KESIN YASAK: "question" alaninda paragraftaki cumleleri tekrarlama, numaralama veya ozetleme
- "question" alani SADECE tek bir soru cumlesi olmali
"""

        # Universal duplicate prevention for ALL templates
        _universal_warning = """
## SORU KOKU KURALI (KRITIK!)
- "question_stem" alanina SADECE soru cumlesini yaz — paragraftaki metni TEKRARLAMA!
- YASAK: Soru kokunde paragrafin tamami veya bir kismini kopyalamak
- YASAK: Soru kokunde hikaye/metin icerigi yazmak
- Soru koku SADECE "<b>...hangisi doğrudur?</b>" gibi TEK CUMLE olmali
"""

        # Dual-source enforcement for answer-critical (Bolum 7) templates
        _dual_source_warning = ""
        if getattr(template, "visual_requirement", None) == "answer_critical":
            _dual_source_warning = """
## CIFT-KAYNAK ZORUNLULUGU (KRITIK — BU SORU GORSEL-BAGIMLI!)
Bu soru answer-critical: ogrenci DOGRU cevabi ancak GORSEL + PARAGRAF birlikte inceleyerek bulmalidir.

PARAGRAF YAZIM KURALLARI:
- Paragraf YALNIZCA baglam/ipucu vermelidir — dogru cevabi DOGRUDAN SOYLEMEMELIDIR.
- Paragrafta "Isaret bize ... anlatir", "Sembol ... anlamina gelir" gibi acik cevaplama YASAK.
- Paragraf, gorseli okumaya DAVET eden genel bilgi sunmali (orn: "Kitabimizdaki renkli isaretler farkli gorevlere isaret eder").
- TEST: Paragrafi tek basina okuyan ogrenci 2+ secenek arasinda bocalamaiidir — tek bir cevap kesin olmamali.

SORU KOKU KURALLARI:
- Soru koku GORSELE acikca atifta bulunmali: "Gorseldeki sembol...", "Sekle gore...", "Tablodaki veriye gore...".
- Soru kokunde paragrafin tamamini ya da bir kismini yeniden soyleme.

DOGRU CEVAP KURALLARI:
- Dogru cevap, paragraftaki ipucu + gorseldeki bicimsel bilgi birlesiminden cikar.
- Dogru cevap paragrafta TEK BASINA GECMEMELI.

CELDIRICI KURALLARI:
- 1 celdirici: paragrafa yakin ama gorsele AYKIRI.
- 1 celdirici: gorsele yakin ama paragrafa AYKIRI.
- Sadece ikisi birlikte incelendiginde TEK DOGRU cevap kalmali.
"""

        return f"""{template.meta.ad} sorusu olustur:

## KONU
{topic}

## PARAGRAF
{paragraph}
{siralama_warning}
{_universal_warning}
{_dual_source_warning}
## SINIF SEVIYESI
{grade}. sinif

{rules}

{correct_section}

{distractor_section}

{option_constraints}"""

    def _build_image_options_prompt(
        self,
        template: "QuestionTemplate",
        paragraph: str,
        stem: str,
        topic: str,
        grade: int,
        correct_section: str,
        distractor_section: str,
        option_constraints: str,
    ) -> str:
        """Build prompt for image-option (gorsel_siklar) format.

        LLM generates:
        1. shared_visual_format: The IDENTICAL visual format for all options
        2. option_X: ONLY the data/content that differs per option

        This separation ensures visual consistency when images are generated.
        """
        rules = self._build_rules_block(stem)

        image_style = getattr(template.format.options, "image_style", "photo") or "photo"

        # Style-specific instructions for shared_visual_format and options
        style_instructions = {
            "photo": (
                "## SHARED_VISUAL_FORMAT KURALLARI\n"
                "Tum seceneklerin ORTAK gorsel formati. Ornek:\n"
                "  'Beyaz arka plan uzerinde renkli illustrasyon, sol profil gorunum, tam vucut, sinav kitabi tarzi'\n\n"
                "## SECENEK KURALLARI (KRITIK)\n"
                "- 4 secenek AYNI GENEL KATEGORI icinde olmali\n"
                "  (paragraf kelebek anlatiyorsa → 4'u de kelebek/guve TURLERINDEN,\n"
                "   paragraf yaprak anlatiyorsa → 4'u de FARKLI yaprak turu,\n"
                "   paragraf gezegen anlatiyorsa → 4'u de gezegen)\n"
                "- FARKLI ALT TUR veya VARYANT kullan: belirgin gorsel farklar (sekil, desen, boyut, yapi)\n"
                "- ILK BAKISTA ayirt edilebilmeli ama PARAGRAF DIKKATLE OKUNMADAN dogru cevap belli OLMAMALI\n"
                "- Dogru cevap: paragraftaki TUM fiziksel ozellikleri yansitmali\n"
                "- Celdiriciler: ayni kategoriden ama 1-2 KRITIK gorunur ozellikte FARKLI\n"
                "- YASAK: Tamamen farkli kategorilerden sik koymak → cevabi bariz yapar!\n"
                "  (ornek: kelebek sorusunda bocek+yusufcuk+tirtil koymak YASAK)\n"
                "- YASAK: 4 gorseli SADECE renk tonuyla ayirmak → ayirt edilemez\n"
                "- Format bilgisi YAZMA — sadece nesnenin/canlinin FARKLI ozelliklerini anlat\n"
                "- Somut ve gorsellestirilmeye uygun detaylar"
            ),
            "chart": (
                "## SHARED_VISUAL_FORMAT KURALLARI\n"
                "Grafik basligini ve grafik tipini BELIRT.\n"
                "Ornek: 'baslik: Kus Turleri Adetleri, tip: dikey bar grafik'\n\n"
                "## SECENEK KURALLARI\n"
                "- Her secenek grafik verilerini icermeli (kategori ve sayisal degerler)\n"
                "- Tum seceneklerde AYNI kategoriler olmali, sadece degerler farkli\n"
                "- Format bilgisi YAZMA — sadece verileri yaz"
            ),
            "table": (
                "## SHARED_VISUAL_FORMAT KURALLARI\n"
                "Tablo sutun basliklarini BELIRT.\n"
                "Ornek: 'Yer | Zaman | Olay | Kisi sutunlari'\n\n"
                "## SECENEK KURALLARI\n"
                "- Her secenek tablo hucre degerlerini icermeli\n"
                "- Tum seceneklerde AYNI sutunlar olmali, sadece degerler farkli\n"
                "- Format bilgisi YAZMA — sadece degerleri yaz"
            ),
            "mockup": (
                "## SHARED_VISUAL_FORMAT KURALLARI\n"
                "Gorsel tipini BELIRT (telefon ekrani, akilli saat, gosterge paneli, vb).\n\n"
                "## SECENEK KURALLARI\n"
                "- Her secenek ekran/arayuz icerik verilerini icermeli\n"
                "- KISA ve OZ degerler yaz (en fazla 3-4 kelime per deger)\n"
                "- Tum seceneklerde AYNI alanlar olmali, sadece degerler farkli\n"
                "- Format bilgisi YAZMA — sadece icerik verilerini yaz"
            ),
        }

        style_rules = style_instructions.get(image_style, style_instructions["photo"])

        return f"""Gorsel secenekli soru olustur.

## KONU
{topic}

## PARAGRAF
{paragraph}

## SINIF SEVIYESI
{grade}. sinif

{style_rules}

## KRITIK: FORMAT/VERI AYRIMI
- shared_visual_format alanina: 4 secenegin ORTAK gorsel formatini yaz (hepsi BIREBIR AYNI gorunecek)
- option_X alanlarina: SADECE o secenege ozgu FARKLI veriyi/icerigi yaz
- Seceneklerde format bilgisi TEKRARLAMA — format shared_visual_format'ta ZATEN var
- Dogru cevap: Paragraftaki TUM verileri/ozellikleri YANSITAN secenek
- Celdiriciler: En az 1 kritik detayda FARKLI

{rules}

{correct_section}

{distractor_section}

{option_constraints}"""

    def _build_inverse_html_prompt(
        self,
        template: "QuestionTemplate",
        stem: str,
        topic: str,
        grade: int,
        correct_section: str,
        distractor_section: str,
        option_constraints: str,
    ) -> str:
        """Build prompt for inverse (topic-in-stem) format."""
        # Check if this is inverse title format
        is_title_format = template.format.titles_in_stem is not None

        if is_title_format:
            return self._build_inverse_title_html_prompt(
                template, topic, grade, correct_section, distractor_section, option_constraints
            )

        leaf_topic = self._extract_leaf_topic(topic)
        rules = self._build_rules_block(stem)

        return f"""TERS MANTIK (YER ALMAZ) SORUSU OLUSTUR:

## KONU
{leaf_topic}

## SINIF SEVIYESI
{grade}. sinif

{rules}

## TERS MANTIK
- {template.format.options.count} mini-paragraf secenegi olustur
- {template.format.options.count - 1} tanesi konuyla DOGRUDAN ilgili (YANLIS secenekler)
- 1 tanesi konuyla ALAKALI AMA FARKLI alandan (DOGRU cevap)
- Strateji: SADECE YAKIN_ANLAM, UST_KAVRAM, KAPSAM_KAYDIRMA
- Dogru cevap icin KOMBİNASYON: ["KAPSAM_KAYDIRMA", "YAKIN_ANLAM"]

{correct_section}

{distractor_section}

{option_constraints}"""

    def _build_inverse_title_html_prompt(
        self,
        template: "QuestionTemplate",
        stem: str,
        topic: str,
        grade: int,
        correct_section: str,
        distractor_section: str,
        option_constraints: str,
    ) -> str:
        """Build prompt for inverse title format with 3 titles in stem."""
        rules = self._build_rules_block(stem)

        return f"""TERS MANTIK (BASLIK GETIRILEMEZ) SORUSU OLUSTUR:

## ANA KONU ALANI
{topic}

## SINIF SEVIYESI
{grade}. sinif

{rules}

## BASLIK OLUSTURMA
- 3 farkli baslik olustur (her biri farkli alt konu, birbirini kapsamamali, gazete manseti tarzi)
- "titles_paragraph" alanina: "1. [Baslik 1]<br>2. [Baslik 2]<br>3. [Baslik 3]"
- "question" alanina baslik OLMADAN sadece soru kokunu yaz (HTML etiketleri dahil!)

## TERS MANTIK
- {template.format.options.count} mini-paragraf secenegi: {template.format.options.count - 1} basliklardan biriyle uyumlu (yanlis), 1 hicbir baslikla uyumsuz (dogru)
- Strateji: SADECE YAKIN_ANLAM, UST_KAVRAM, KAPSAM_KAYDIRMA
- Dogru cevap icin KOMBİNASYON: ["KAPSAM_KAYDIRMA", "YAKIN_ANLAM"]

{correct_section}

{distractor_section}

{option_constraints}"""

    # ========================================================================
    # NUMBERED (ROMAN NUMERAL) FORMAT
    # ========================================================================

    def _build_numbered_html_prompt(
        self,
        template: "QuestionTemplate",
        paragraph: str,
        stem: str,
        topic: str,
        grade: int,
        correct_section: str,
        distractor_section: str,
        option_constraints: str,
    ) -> str:
        """Build prompt for numbered I/II/III/IV format (roman_numeral_combination)."""
        # Handle {topic} placeholder in stem
        stem = self._resolve_stem_with_topic(stem, topic)
        rules = self._build_rules_block(stem)

        # Determine if options use does_not_belong logic
        correct_type = template.format.options.correct_type
        is_negative = correct_type == "does_not_belong"

        # Arabic numeral templates (sequence/combination options with 1,2,3,4)
        _tmpl_id = getattr(getattr(template, "meta", None), "id", "") or ""
        _is_olusturma_sinif2 = "paragraf_olusturma_sinif2" in _tmpl_id
        _is_arabic_numarali = "yardimci_fikir_numarali_sinif4" in _tmpl_id

        if _is_olusturma_sinif2:
            logic_hint = """## PARAGRAF OLUSTURMA — ARAP RAKAMI FORMATI (KRITIK!)
- Paragrafta 3 veya 4 cumle ARAP RAKAMIYLA numarali (1., 2., 3., 4.) ve KARISIK sirada verilmis.
- Dogru siralama bu rakamlarin dizisi olmalidir (orn: "2-3-4-1", "1-3-2-4").
- Roma rakami (I, II) KULLANMA — SADECE Arap rakami!
- Secenekler tire ile ayrilmis rakam dizisi biciminde olmali: "2-3-4-1" gibi.
- statement_I/II/III/IV alanlarini doldurman GEREKMIYOR — paragraftaki cumleler zaten numarali.
- "question" alanina SADECE soru kokunu yaz — {{statements}} PLACEHOLDER KULLANMA!"""
        elif _is_arabic_numarali:
            logic_hint = """## NUMARALI FORMAT — ARAP RAKAMI ZORUNLU (KRITIK!)
- 4 numarali ifade olustur (1, 2, 3, 4) — ROMA RAKAMI KESİNLİKLE YASAK!
- 2 tanesi paragrafta yardimci fikir olarak DESTEKLENEN, 2 tanesi DESTEKLENMEYEN (ana fikir, alakasiz, metinde yok) olmali.
- DOGRU CEVAP: desteklenen 2 ifadenin birlesimi (orn: "1 ve 3", "2 ve 4").
- Secenek format: ARAP RAKAMI ile "1 ve 2" gibi — "I ve II" YASAK!"""
        elif is_negative:
            logic_hint = """## NUMARALI FORMAT MANTIGI (TERS MANTIK!)
- 4 numarali ifade/soru olustur (I, II, III, IV)
- 2 tanesi paragrafta DESTEKLENEN, 2 tanesi DESTEKLENMEYEN
- DOGRU CEVAP: desteklenmeyen 2 ifadenin birlesimi (orn: "II ve IV")"""
        else:
            logic_hint = """## NUMARALI FORMAT MANTIGI (POZITIF MANTIK)
- 4 numarali ifade/soru olustur (I, II, III, IV)
- HEPSİ verilen KONU ve PARAGRAF ile ilgili olmali!
- 2 tanesi DESTEKLENEN, 2 tanesi DESTEKLENMEYEN
- DOGRU CEVAP: desteklenen 2 ifadenin birlesimi (orn: "I ve III")"""

        return f"""NUMARALI FORMAT SORUSU OLUSTUR:

## KONU
{topic}

## PARAGRAF
{paragraph}

## SINIF SEVİYESİ
{grade}. sinif

{rules}

{logic_hint}

{correct_section}

{distractor_section}

{option_constraints}

## NUMARALI FORMAT OZEL KURALLARI
- statement_I/II/III/IV alanlarini AYRI AYRI DOLDUR (tam cumle, siralama karisik)
- "question" alanina soru kokunu {{statements}} PLACEHOLDER ile yaz — degistirme!
- ASLA <ol> veya <li> KULLANMA — validation FAIL olur!
{"- Secenekler ikili birlesim: 'ARAP RAKAMI' ile '1 ve 2', '1 ve 3', '2 ve 4', '3 ve 4' gibi (Roma YASAK)" if _is_arabic_numarali else "- Secenekler ikili birlesim: 'I ve II', 'I ve III', 'II ve IV', 'III ve IV' gibi"}
- Her ifade SADECE verilen konu ve paragrafla ilgili olmali
- Desteklenen/desteklenmeyen ayrimi INCE olmali (bariz degil!)

ORNEK question: "<b>Bu metinde,</b>\n{{statements}}\n<b>maddelerinden hangileri...</b>"
"""

    # ========================================================================
    # BECERI TEMELLI (SKILL-BASED) FORMAT
    # ========================================================================

    def _build_beceri_prompt(
        self,
        template: "QuestionTemplate",
        paragraph: str,
        stem: str,
        topic: str,
        grade: int,
        correct_section: str,
        distractor_section: str,
        option_constraints: str,
    ) -> str:
        """Build prompt for beceri temelli (skill-based) question format."""
        rules = self._build_rules_block(stem)
        beceri = template.beceri
        opt_count = template.format.options.count

        # Get context-specific instructions
        context_type = beceri.context_type.lower() if beceri else "bilgilendirici"
        context_prompt = CONTEXT_TYPE_PROMPTS.get(context_type, "")

        # Build skill areas hint with taxonomy level
        skill_hint = ""
        if beceri and beceri.skill_areas:
            from legacy_app.kadir_hoca.agentic.prompts.beceri_prompts import SKILL_AREAS
            skill_parts = []
            for area in beceri.skill_areas:
                info = SKILL_AREAS.get(area)
                if isinstance(info, dict):
                    skill_parts.append(f"{area} ({info['tanim']}, {info['seviye']})")
                else:
                    skill_parts.append(area)
            skill_hint = "BECERI ALANLARI: " + ", ".join(skill_parts)
            if beceri.skill_level:
                skill_hint += f"\nBECERI SEVIYESI: {beceri.skill_level}"
            if beceri.process_component:
                skill_hint += f"\nSUREC BILESENI: {beceri.process_component}"

        return f"""BECERI TEMELLI SORU OLUSTUR:

## KONU
{topic}

## PARAGRAF / BAGLAM
{paragraph}

## SINIF SEVIYESI
{grade}. sinif

{context_prompt}

{skill_hint}

{rules}

## BECERI TEMELLI OZEL KURALLAR
- {opt_count} secenek (A-E) olustur
- ONEMLI: option_e, option_e_strategy ve option_e_reasoning alanlarini MUTLAKA doldur! Bos birakma!
- Ust duzey dusunme becerileri olcen bir soru yaz
- Secenekler arasinda ince farklar olsun
- answer_explanation alanina dogru cevabin NEDEN dogru oldugunu acikla
- skill_tag alanina olculen beceri alanini yaz (ornek: "cikarimlama", "degerlendirme")
- Soru sadece metni okuyarak cevaplanabilmeli, dis bilgi gerektirmemeli

## KRITIK - SORU KOKU KURALLARI
- Soru koku (question alani) SADECE soru cumlesini icermeli!
- Paragraf/baglam metni ZATEN yukarida verilmis. Soru kokune metin EKLEME!
- YANLIS: "Metin I: ... Metin II: ... Bu metinlere gore hangisi dogrudur?"
- DOGRU: "Bu metinlere gore asagidakilerden hangisi dogrudur?"
- Soru koku KISA olmali (1-2 cumle). Metin tekrarlanmamali!
- "Yukaridaki metin/paragraf/metinler" diye referans verebilirsin ama icerigi kopyalama!

## SIK YAPILAN HATALAR - BUNLARDAN KACIN
- BAGLAM HATASI: Baglam dekoratif olmamali, sorunun cozumu icin gerekli bilgi icermeli
- BAGLAM HATASI: Baglam dogrudan cevabi vermemeli, ipucu icermeli
- KOK HATASI: Cift olumsuz kullanma ("degil" + "-mez" gibi)
- KOK HATASI: Oznel soru sorma ("sizce", "sence" gibi ifadeler KULLANMA)
- SECENEK HATASI: Eleme yoluyla cevaplanabilir secenek olusturma (4 secenek bariz yanlis olmamali)
- SECENEK HATASI: Format farkliligi ile dogru cevabi belli etme (tum secenekler ayni uzunluk/formatta)
- SECENEK HATASI: Dogru cevap diger seceneklerden belirgin sekilde uzun veya kisa olmamali

{correct_section}

{distractor_section}

{option_constraints}"""

    # ========================================================================
    # MULTI-PARAGRAPH FORMAT (2-text comparison)
    # ========================================================================

    def _build_multi_paragraph_standard_prompt(
        self,
        template: "QuestionTemplate",
        paragraph: str,
        stem: str,
        topic: str,
        grade: int,
        correct_section: str,
        distractor_section: str,
        option_constraints: str,
    ) -> str:
        """Build prompt for multi-paragraph standard format (2-text comparison)."""
        rules = self._build_rules_block(stem)

        return f"""{template.meta.ad} sorusu olustur:

## KONU
{topic}

## METINLER (IKI METIN KARSILASTIRMASI)
{paragraph}

## SINIF SEVIYESI
{grade}. sinif

{rules}

## IKI METIN KARSILASTIRMA TALIMATLARI
- Yukaridaki iki metin arasindaki iliskiyi analiz et
- Soru bu iki metin arasindaki ORTAK veya FARKLI yonlerle ilgili olmali
- Secenekler her iki metni birden dikkate almali

{correct_section}

{distractor_section}

{option_constraints}"""

    def _build_multi_paragraph_numbered_prompt(
        self,
        template: "QuestionTemplate",
        paragraph: str,
        stem: str,
        topic: str,
        grade: int,
        correct_section: str,
        distractor_section: str,
        option_constraints: str,
    ) -> str:
        """Build prompt for multi-paragraph numbered format (2-text + I/II/III/IV)."""
        stem = self._resolve_stem_with_topic(stem, topic)
        rules = self._build_rules_block(stem)

        correct_type = template.format.options.correct_type
        is_negative = correct_type == "does_not_belong"

        if is_negative:
            logic_hint = """## NUMARALI FORMAT MANTIGI (TERS MANTIK!)
- 4 numarali ifade olustur (I, II, III, IV) — her iki metinle ilgili
- 2 tanesi her iki metinde DESTEKLENEN (ortak), 2 tanesi DESTEKLENMEYEN
- DOGRU CEVAP: desteklenmeyen 2 ifadenin birlesimi"""
        else:
            logic_hint = """## NUMARALI FORMAT MANTIGI (POZITIF MANTIK)
- 4 numarali ifade olustur (I, II, III, IV) — her iki metinle ilgili
- 2 tanesi her iki metinde DESTEKLENEN (ortak), 2 tanesi DESTEKLENMEYEN
- DOGRU CEVAP: desteklenen 2 ifadenin birlesimi (orn: "I ve III")"""

        return f"""NUMARALI FORMAT + IKI METIN SORUSU OLUSTUR:

## KONU
{topic}

## METINLER (IKI METIN KARSILASTIRMASI)
{paragraph}

## SINIF SEVİYESİ
{grade}. sinif

{rules}

{logic_hint}

{correct_section}

{distractor_section}

{option_constraints}

## NUMARALI FORMAT OZEL KURALLARI
- statement_I/II/III/IV alanlarini AYRI AYRI DOLDUR (tam cumle, her iki metinle ilgili)
- "question" alanina soru kokunu {{statements}} PLACEHOLDER ile yaz
- ASLA <ol> veya <li> KULLANMA
- Secenekler ikili birlesim: "I ve II", "I ve III", "II ve IV", "III ve IV" gibi
- Her ifade IKI METIN arasindaki iliskiyi degerlendirmeli

ORNEK question: "<b>Bu metinler ile ilgili;</b>\n{{statements}}\n<b>ifadelerinden hangileri ortaktir?</b>"
"""

    # ========================================================================
    # GENERIC INVERSE FORMAT (no paragraph, options carry content)
    # ========================================================================

    def _build_generic_inverse_prompt(
        self,
        template: "QuestionTemplate",
        stem: str,
        topic: str,
        grade: int,
        correct_section: str,
        distractor_section: str,
        option_constraints: str,
    ) -> str:
        """Build template-driven prompt for generic inverse formats.

        Used by Category D templates where paragraph=false and options carry
        the main content (mini-paragraphs, sentences, etc.).

        Reads generation_logic.steps from the template to build instructions,
        ensuring future templates need only YAML changes.
        """
        rules = self._build_rules_block(stem)

        # Extract generation steps from template
        steps_text = self._format_generation_steps(template)

        # Extract premises info if available
        premises_text = self._format_premises_section(template)

        # Template description for context
        template_desc = template.meta.aciklama or template.meta.ad

        return f"""GENERIC INVERSE SORUSU OLUSTUR:
Template: {template.meta.ad}
Aciklama: {template_desc}

## KONU
{topic}

## SINIF SEVIYESI
{grade}. sinif

{rules}
{premises_text}
## ONEMLI: PARAGRAF YOK!
- Bu soruda ana paragraf YOKTUR
- Seceneklerin KENDISI icerik tasir (mini-paragraf, cumle, kavram vb.)
- Her secenek bagimsiz bir metin/ifade olarak olusturulmali
{self._get_titles_paragraph_instruction(template)}

## URETIM ADIMLARI
{steps_text}

{correct_section}

{distractor_section}

{option_constraints}"""

    def _format_generation_steps(self, template: "QuestionTemplate") -> str:
        """Format generation_logic.steps into readable instructions."""
        if not template.generation_logic or "steps" not in template.generation_logic:
            return "Template'in uretim mantigi mevcut degil — genel kurallara uy."

        steps = template.generation_logic["steps"]
        lines = []
        for step in steps:
            step_num = step.get("step", "?")
            action = step.get("action", "")
            details = step.get("details", "")
            lines.append(f"Adim {step_num}: {action}")
            if details:
                for detail_line in details.strip().split("\n"):
                    lines.append(f"  {detail_line.strip()}")
        return "\n".join(lines)

    def _format_premises_section(self, template: "QuestionTemplate") -> str:
        """Format premises section for reverse/matching templates."""
        premises_cfg = getattr(template.format, "premises", None)
        if not premises_cfg or not premises_cfg.required:
            return ""

        structure = premises_cfg.structure
        if not structure:
            return ""

        lines = ["## ONCUL YAPISI (PREMISES)"]
        lines.append("Soru kokunden ONCE sunulan bilgi yapisi:")
        for item in structure:
            lines.append(f"  - {item}")
        lines.append("")
        lines.append(
            "Bu onculleri olustur ve 'titles_paragraph' alanina yaz "
            "(orn: 'Yer: X<br>Zaman: Y<br>Kisiler: Z<br>Olay: W')"
        )
        lines.append("Secenekler bu oncullerle KARSILASTIRILIR.")
        lines.append("")
        return "\n".join(lines)

    def _get_titles_paragraph_instruction(self, template: "QuestionTemplate") -> str:
        """Return titles_paragraph field instruction based on template type."""
        premises_cfg = getattr(template.format, "premises", None)
        if premises_cfg and premises_cfg.required:
            return (
                '- "titles_paragraph" alanina ONCULLERI yaz '
                '(orn: "Yer: X<br>Zaman: Y<br>Kisiler: Z<br>Olay: W")'
            )
        return '- "titles_paragraph" alani BOS kalmali (bos string "")'

    # ========================================================================
    # HELPER METHODS
    # ========================================================================

    def _resolve_stem_with_topic(self, stem: str, topic: str) -> str:
        """Replace {topic} placeholder in stem with leaf topic.

        Used by both standard and numbered prompt builders.
        """
        if "{topic}" in stem:
            leaf_topic = self._extract_leaf_topic(topic)
            return stem.replace("{topic}", leaf_topic)
        return stem

    def _format_strategy_list(self, strategies: list) -> list[str]:
        """Format a numbered list of strategies with name, description, instructions, and warnings.

        Returns list of formatted lines with full strategy details for LLM.
        Used by both standard and inverse strategy pool formatters.
        """
        lines: list[str] = []
        for i, strat in enumerate(strategies, 1):
            lines.append(f"{i}. {strat.ad} — {strat.aciklama}")
            if strat.nasil_olusturulur:
                nasil = strat.nasil_olusturulur.strip().replace("\n", " ")
                lines.append(f"   Nasıl: {nasil}")
            if strat.kacinilacaklar:
                kacinilacak = strat.kacinilacaklar.strip().replace("\n", " ")
                lines.append(f"   Kaçınılacaklar: {kacinilacak}")
        return lines

    def _format_correct_answer_section(self, template: "QuestionTemplate") -> str:
        """Format correct answer rules section for prompt."""
        correct = template.dogru_cevap
        rules_text = "\n".join(f"  - {rule}" for rule in correct.kurallar)

        examples_text = ""
        if correct.ornekler:
            examples = []
            for ex in correct.ornekler[:2]:
                if ex.paragraf and ex.dogru:
                    examples.append(f"  - Paragraf: '{ex.paragraf[:50]}...' -> Dogru: '{ex.dogru}'")
                elif ex.konu and ex.dogru_cevap:
                    examples.append(f"  - Konu: '{ex.konu}' -> Cevap: '{ex.dogru_cevap}'")
            if examples:
                examples_text = "\nOrnekler:\n" + "\n".join(examples)

        return f"""## DOGRU CEVAP KURALLARI
Tanim: {correct.tanim}
Kurallar:
{rules_text}{examples_text}"""

    def _format_distractor_section(self, template: "QuestionTemplate") -> str:
        """Format distractor strategies section for prompt.

        Supports both legacy template-specific strategies and the new shared pool.
        When use_shared_strategies=True, formats strategies as a pool
        for the LLM to select from based on paragraph content.

        For INVERSE templates, strategies are grouped by role (dogru_cevap vs yanlis_cevap).
        """
        strategies = template.celdirici_stratejileri

        # Check if using shared pool
        is_shared_pool = template.use_shared_strategies and len(strategies) >= 3

        if is_shared_pool:
            # Check if this is an INVERSE template
            is_inverse = not template.format.paragraph.required
            return self._format_shared_strategy_pool(strategies, is_inverse=is_inverse)
        else:
            return self._format_legacy_distractor_section(strategies)

    def _format_shared_strategy_pool(self, strategies: list, is_inverse: bool = False) -> str:
        """Format shared strategy pool for prompt.

        For STANDARD templates: Presents all strategies as a pool for the LLM to
        dynamically select from based on paragraph content.

        For INVERSE templates: Separates strategies by role (dogru_cevap vs yanlis_cevap)
        to guide the LLM on which strategies to use for which purpose.

        Supports combined strategies in both cases.
        """
        if is_inverse:
            return self._format_inverse_strategy_pool(strategies)
        else:
            return self._format_standard_strategy_pool(strategies)

    def _format_standard_strategy_pool(self, strategies: list) -> str:
        """Format strategy pool for standard (paragraph-based) templates."""
        lines = ["## ÇELDİRİCİ STRATEJİLERİ HAVUZU"]
        lines.append(
            f"Aşağıdaki {len(strategies)} stratejiden paragrafın yapısına göre seç:"
        )
        lines.append("")
        lines.extend(self._format_strategy_list(strategies))
        lines.append("")
        lines.append("İDEAL DAĞILIM: 2 tek strateji + 1 kombinasyon (3 çeldirici için)")

        return "\n".join(lines)

    def _format_inverse_strategy_pool(self, strategies: list) -> str:
        """Format strategy pool for INVERSE templates."""
        lines = ["## ÇELDİRİCİ STRATEJİLERİ HAVUZU (TERS MANTIK)"]
        lines.append("SADECE şu stratejileri kullan:")
        lines.append("")
        lines.extend(self._format_strategy_list(strategies))
        lines.append("")
        lines.append("DOĞRU CEVAP: KOMBİNASYON ([\"KAPSAM_KAYDIRMA\", \"KAVRAM_YANILGISI\"] vb.)")
        lines.append("YANLIŞ CEVAPLAR: Tek strateji (KAVRAM_YANILGISI, ASIRI_SOYUTLAMA veya KAPSAM_KAYDIRMA)")

        return "\n".join(lines)

    def _format_legacy_distractor_section(self, strategies: list) -> str:
        """Format legacy template-specific distractor strategies."""
        lines = ["## CELDIRICI STRATEJILERI (3 yanlis sik icin)"]

        for strat in strategies:
            lines.append(f"\n### {strat.ad.upper()}")
            lines.append(f"Aciklama: {strat.aciklama}")
            if strat.nasil_olusturulur:
                lines.append(f"Nasil: {strat.nasil_olusturulur}")

            # Collect examples: prefer ornekler (plural), fallback to ornek (legacy singular)
            examples_to_show: list = []
            if strat.ornekler:
                examples_to_show = strat.ornekler[:1]  # 1 example per strategy
            elif strat.ornek:
                if isinstance(strat.ornek, str):
                    lines.append(f"Ornek: {strat.ornek}")
                else:
                    examples_to_show = [strat.ornek]

            for ex in examples_to_show:
                if ex.paragraf_konusu and ex.celdirici:
                    # Standard format example
                    lines.append(
                        f"Ornek: Konu='{ex.paragraf_konusu}' -> '{ex.celdirici}' "
                        f"(Neden yanlis: {ex.neden_yanlis})"
                    )
                elif ex.konu and ex.paragraf:
                    # Inverse format example
                    reason = f" (Neden dogru: {ex.neden_dogru})" if ex.neden_dogru else ""
                    lines.append(f"Ornek: Konu='{ex.konu}' -> '{ex.paragraf[:60]}...'{reason}")
                elif ex.paragraf:
                    # Paragraph-only example
                    reason_text = ex.neden_dogru or ex.neden_yanlis or ""
                    reason = f" ({reason_text})" if reason_text else ""
                    lines.append(f"Ornek: '{ex.paragraf[:60]}...'{reason}")

        # Add difficulty reminder after strategies
        lines.append("\n## ÇELDİRİCİ ZORLUK SEVİYESİ (KRİTİK!)")
        lines.append("- En az 1 çeldirici doğru cevaba ÇOK YAKIN olmalı (yakın anlam)")
        lines.append("- 'Çok geniş' çeldirici bile konuyla AYNI ALANDA kalmalı")
        lines.append("- Öğrenci şıkları okurken en az 2 şıkta tereddüt etmeli")
        lines.append("- 'Bariz yanlış' şık YAZMA! Her şık mantıklı görünmeli")

        return "\n".join(lines)

    def _format_option_constraints(self, template: "QuestionTemplate") -> str:
        """Format option constraints section for prompt."""
        opt = template.format.options

        # Determine answer style hint
        style_hints = {
            "topic_phrase": "kisa isim tamlamasi (2-6 kelime), orn: 'Sisin olusumu'",
            "headline_title": "yaratici gazete manseti (2-6 kelime), orn: 'Guvercinlerin Pusulasi'",
            "complete_sentence": "tam cumle (8-25 kelime), orn: 'Kahvalti saglikli yasam icin gereklidir.'",
            "mini_paragraph": "mini-paragraf (25-45 kelime, 2-4 cumle)",
            "single_keyword": (
                "tek kelime (1 sozcuk) - tum secenekler ayni "
                "soyutluk/somutluk seviyesinde olmali, "
                "orn: hepsi somut isim veya hepsi soyut kavram"
            ),
            "keyword_set": "sozcuk seti (2-4 sozcuk, MUTLAKA ' - ' ile ayrilmis, VIRGUL KULLANMA), orn: 'bellek - veri - islem'",
            "short_phrase": (
                "kisa ifade (2-8 kelime, yon/ozellik ifadesi), "
                "orn: 'Fiziksel ozelliklerine', 'Yasam alanlarina'"
            ),
            "question_sentence": (
                "soru cumlesi (4-15 kelime, '?' ile biter), "
                "orn: 'Spor açken mi yoksa tokken mi yapılmalıdır?'"
            ),
            "roman_numeral_combination": "Roma rakami birlesimi (orn: 'I ve II', 'II ve IV')",
            "ordered_sequence": (
                "tam siralama — tum bireyler/varliklar tek satirda, ayni ayirici ile "
                "(orn: 'Ali - Ece - Baran - Defne - Kerem' veya virgullu es format); "
                "her sikta ayni kisiler, yalnizca sira farkli"
            ),
            "concept": "kavram adi (1-3 kelime), orn: 'Tanimlama', 'Kaygi', 'Zaman'",
            "structured_list": "yapilandirilmis liste — her unsuru <br> ile AYRI SATIRDA yaz. Format: Yer: X<br>Zaman: Y<br>Olay: Z<br>Kisi: T (VIRGUL ILE AYIRMA, <br> KULLAN!)",
            "element_label": (
                "SADECE TEK KELIME hikaye unsur adi. "
                "Her secenek SADECE 4 unsur adindan biri olabilir: Zaman, Mekan, Kişi, Olay. "
                "YASAK: aciklama, deger, icerik, parantez (ornek: 'Zaman: Sabah' YASAK — sadece 'Zaman'). "
                "YASAK: 'Sorun', 'Çatışma', 'Tema', 'Anlatıcı', 'Olay örgüsü' (hikaye unsuru degil). "
                "3 secenek = 4 unsurdan 3 tanesi; DOGRU cevap = metinde BULUNMAYAN unsur adi."
            ),
            "element_set_labeled_multiline": (
                "unsur seti — HER UNSURU <br> ile AYRI SATIRDA yaz. "
                "Format: ZAMAN: deger<br>MEKAN: deger<br>KİŞİ: deger. "
                "Her unsur icin metinden alinmis SOMUT deger yaz (ornek: 'ZAMAN: Cumartesi sabahi<br>MEKAN: Bahce<br>KİŞİ: Ali'). "
                "YASAK: virgul veya tire ile ayirma."
            ),
            "variable": "degisken format (2-5 kelime), orn: 'Gorme - Isitme', 'Endise - Sevinc'",
            "image_description": "gorsel tasvir (15-50 kelime), gorsellestirilmeye uygun, dogrudan nesneyi/sahneyi anlat",
        }

        style_hint = style_hints.get(opt.style, style_hints.get(opt.type, "kisa ifade"))

        labels_str = ", ".join(opt.labels)
        e_reminder = ""
        if opt.count >= 5:
            e_reminder = f"\n- ONEMLI: option_e alanini MUTLAKA doldur! {opt.count} secenek ({labels_str}) uretilmeli!"

        return f"""## SECENEK KISITLAMALARI
- Kelime sayisi: {opt.word_count_min}-{opt.word_count_max}
- Stil: {opt.style or opt.type} ({style_hint})
- {opt.count} secenek ({labels_str}) birbirine yakin uzunlukta olmali (±1-2 kelime)
- DIL YAPISI: {opt.count} secenek AYNI dilbilgisel yapida olmali (hepsi isim tamlamasi VEYA hepsi cumle VEYA hepsi sifat+isim)
- FAIL ORNEK: A) "Güneşle ısınma" B) "Rutubet" C) "Toprak kayması" D) "Yağmur suyunu biriktirerek tasarruf etmek" → D farklı yapı!
- PASS ORNEK: A) "Isı yalıtımı" B) "Su tasarrufu" C) "Enerji verimliliği" D) "Geri dönüşüm" → hepsi isim tamlaması{e_reminder}"""

    def _format_validation_feedback_section(self, validation_feedback: str) -> str:
        """Format validation feedback for retry prompts."""
        return f"""

## ONCEKI DENEME GERI BILDIRIMI (KRITIK - BU HATALARI TEKRARLAMA!)
Onceki uretiminiz dogrulama kontrolunden gecemedi. Asagidaki sorunlari DUZELT:

{validation_feedback}

ONEMLI:
- Yukaridaki sorunlari KESINLIKLE tekrarlama
- Onerileri dikkate al
- Ozellikle celdirici stratejileri uyarilarına dikkat et
"""

    # ========================================================================
    # CONTEXT-BASED QUESTION GENERATION
    # ========================================================================

    async def generate_context(
        self,
        template: "QuestionTemplate",
        topic: str,
        subject: str,
        grade: int,
        client: "GeminiClient",
        cache_name: str | None = None,
        model: str = "gemini-3-flash-preview",
    ) -> ParagraphOutput:
        """Generate shared context text (scenario + table/dialog) for context-based questions.

        Returns ParagraphOutput to reuse the existing cache infrastructure.
        """
        prompt = self._build_context_generation_prompt(template, topic, subject, grade)

        logger.info(f"[CONTEXT_GEN] Generating context for: {template.meta.id}")
        logger.debug(
            f"[CONTEXT PROMPT]\n{'='*80}\n"
            f"Template: {template.meta.id}\n"
            f"Topic: {topic}\n"
            f"Model: {model}, Cache: {cache_name or 'none'}\n"
            f"{'-'*80}\n{prompt}\n{'='*80}"
        )

        if cache_name:
            result = await client.generate(
                model=model,
                prompt=prompt,
                output_schema=ParagraphOutput,
                cache_name=cache_name,
            )
        else:
            result = await client.generate(
                model=model,
                prompt=prompt,
                output_schema=ParagraphOutput,
                system_instruction=PARAGRAPH_SYSTEM_PROMPT,
            )

        # Post-process: strip any "Soru N:" contamination from context text
        cleaned = re.sub(
            r'\s*Soru\s+\d+\s*[:：].*?(?=Soru\s+\d+\s*[:：]|\Z)',
            '',
            result.paragraph,
            flags=re.DOTALL | re.IGNORECASE,
        ).strip()
        if cleaned != result.paragraph:
            logger.warning(
                f"[CONTEXT_GEN] Stripped 'Soru N:' contamination from context text "
                f"({len(result.paragraph)} → {len(cleaned)} chars)"
            )
            result.paragraph = cleaned

        # Post-process: convert forbidden HTML tags to safe equivalents
        # <h1-h6>Title</h1-h6> → <b>Title</b><br>  (preserve title semantics)
        # <p>Text</p> → Text<br>  (preserve paragraph breaks)
        # Other forbidden tags → stripped (except chart div/span when uses_chart)
        text = result.paragraph

        # Detect chart format from structure instructions
        _gen = template.context.generation if template.context else None
        _structures = _gen.structure if _gen else []
        _visual_fmt = _gen.visual_format if _gen else None
        _uses_custom_html = _visual_fmt in ("bar_chart", "grouped_bar_chart", "newspaper", "feature_table", "data_table")
        _uses_chart = _uses_custom_html or any(
            kw in s.lower()
            for s in (_structures or [])
            for kw in ("çubuk grafik", "bar chart", 'class="chart"', "pasta grafik", "pie chart", 'class="pie-chart"')
        )

        # Build forbidden tag pattern — exclude chart-related div/span if chart mode
        if _uses_chart:
            forbidden_detect = r'<(?:h[1-6]|p|strong|em|blockquote|ol|li|ul)[\s>]'
            remaining_forbidden = r'</?(?:strong|em|blockquote|ol|li|ul)(?:\s[^>]*)?>'
        else:
            forbidden_detect = r'<(?:h[1-6]|p|div|span|strong|em|blockquote|ol|li|ul)[\s>]'
            remaining_forbidden = r'</?(?:div|span|strong|em|blockquote|ol|li|ul)(?:\s[^>]*)?>'

        has_forbidden = bool(re.search(forbidden_detect, text, re.IGNORECASE))
        if has_forbidden:
            # Convert heading tags to bold with line break
            text = re.sub(r'<h[1-6][^>]*>(.*?)</h[1-6]>', r'<b>\1</b><br>', text, flags=re.IGNORECASE)
            # Convert p tags to line breaks
            text = re.sub(r'<p[^>]*>', '', text, flags=re.IGNORECASE)
            text = re.sub(r'</p>', '<br>', text, flags=re.IGNORECASE)
            # Strip remaining forbidden tags (chart div/span preserved when _uses_chart)
            text = re.sub(remaining_forbidden, '', text, flags=re.IGNORECASE)
            # Collapse multiple consecutive <br>
            text = re.sub(r'(?:<br\s*/?>[\s]*){3,}', '<br><br>', text)
            # Remove trailing <br>
            text = re.sub(r'(?:<br\s*/?>[\s]*)+$', '', text).strip()
            logger.warning(
                f"[CONTEXT_GEN] Converted forbidden HTML tags in context text "
                f"({len(result.paragraph)} → {len(text)} chars)"
            )
            result.paragraph = text

        # Post-process: apply visual format transformation if configured
        _visual_fmt = _gen.visual_format if _gen else None
        if _visual_fmt:
            from legacy_app.kadir_hoca.agentic.tools.visual_formats import apply_visual_format
            original_len = len(result.paragraph)
            result.paragraph = apply_visual_format(result.paragraph, _visual_fmt)
            if len(result.paragraph) != original_len:
                logger.info(
                    f"[CONTEXT_GEN] Applied visual format '{_visual_fmt}' "
                    f"({original_len} → {len(result.paragraph)} chars)"
                )

        logger.debug(
            f"[CONTEXT OUTPUT]\n{'='*80}\n"
            f"Context ({len(result.paragraph.split())} words):\n{result.paragraph}\n"
            f"Key concepts: {result.key_concepts}\n"
            f"{'='*80}"
        )

        return result

    def _build_context_generation_prompt(
        self,
        template: "QuestionTemplate",
        topic: str,
        subject: str,
        grade: int,
    ) -> str:
        """Build prompt for context text generation.

        Includes ALL sub-question previews so LLM fills context with
        information needed for every question.
        """
        from ..tools.name_pool import get_diverse_names as get_names

        ctx = template.context
        gen = ctx.generation

        # Build structure instructions
        structure_text = ""
        if gen.structure:
            structure_text = "YAPI TALIMATLARI:\n" + "\n".join(
                f"  - {s}" for s in gen.structure
            )

        # Build rules
        rules_text = ""
        if gen.kurallar:
            rules_text = "OZEL KURALLAR:\n" + "\n".join(
                f"  - {r}" for r in gen.kurallar
            )

        # Build sub-question preview section
        question_previews = []
        for slot in ctx.questions:
            stems_preview = slot.soru_kokleri[0] if slot.soru_kokleri else "(soru koku)"
            question_previews.append(
                f"  Soru {slot.slot}: [{slot.type}] {stems_preview}"
            )
        questions_section = "\n".join(question_previews) if question_previews else ""

        # Character name diversity
        from ..tools.name_pool import get_name_prompt_section
        name_section = get_name_prompt_section(count=4)

        # Detect chart format from structure instructions
        uses_pie = any(
            kw in s.lower()
            for s in (gen.structure or [])
            for kw in ("pasta grafik", "pie chart", 'class="pie-chart"')
        )
        uses_bar = any(
            keyword in s.lower()
            for s in (gen.structure or [])
            for keyword in ("çubuk grafik", "bar chart", 'class="chart"')
        ) and not uses_pie
        uses_chart = uses_bar or uses_pie
        # Text-only mode: template wants no table/chart in context — image-based types
        _img_type = getattr(gen, "image_type", None)
        text_only_mode = _img_type in ("illustration", "infografik", "soyagaci", "pictograph")

        # Data presentation type labels
        veri_tipi = "GRAFIK" if uses_chart else "TABLO"
        veri_tipi_kucuk = "grafik" if uses_chart else "tablo"
        veri_ref = "grafikteki" if uses_chart else "tablodaki"

        # Build HTML tag rules based on pie chart vs bar chart vs table
        if uses_pie:
            html_tag_rules = f"""HTML TAG KURALLARI (KRITIK!):
- IZIN VERILEN TAGLER: <b>, <u>, <br>, <div class="pie-chart">, <div class="pie">, <div class="pie-legend">, <div class="pie-legend-item">, <span class="pie-legend-color">
- YASAK TAGLER: <table>, <tr>, <th>, <td>, <h1>-<h6>, <p>, <strong>, <em>, <ol>, <li>, <ul>, <blockquote>
- Metin bolumleri arasinda <br> kullan

PASTA GRAFIK FORMAT KURALLARI (KRITIK!):
- 6 renk paleti (SADECE bunlari kullan): #4a90d9, #e5534b, #57ab5a, #d4a72c, #986ee2, #cc6b2c
- Grafik basligini grafigin UZERINDE duz metin olarak yaz
- 4-6 dilim veri olmali, toplam %100 yapmali
- conic-gradient derecelerini hesapla: her dilim = (yuzde/100) * 360 derece
- Ilk dilim 0deg'den baslar, her dilim oncekinin bittigi yerden baslar
- PASTA GRAFIK ORNEK:
  Ogrencilerin En Sevdigi Mevsim
  <div class="pie-chart">
  <div class="pie" style="background: conic-gradient(#4a90d9 0deg 126deg, #e5534b 126deg 234deg, #57ab5a 234deg 306deg, #d4a72c 306deg 360deg)"></div>
  <div class="pie-legend">
  <div class="pie-legend-item"><span class="pie-legend-color" style="background:#4a90d9"></span>Yaz %35</div>
  <div class="pie-legend-item"><span class="pie-legend-color" style="background:#e5534b"></span>Ilkbahar %30</div>
  <div class="pie-legend-item"><span class="pie-legend-color" style="background:#57ab5a"></span>Sonbahar %20</div>
  <div class="pie-legend-item"><span class="pie-legend-color" style="background:#d4a72c"></span>Kis %15</div>
  </div>
  </div>"""
        elif uses_bar:
            html_tag_rules = """HTML TAG KURALLARI (KRITIK!):
- IZIN VERILEN TAGLER: <b>, <u>, <br>, <div class="chart">, <div class="chart-row">, <span class="chart-label">, <span class="chart-bar">, <span class="chart-val">
- YASAK TAGLER: <table>, <tr>, <th>, <td>, <h1>, <h2>, <h3>, <h4>, <h5>, <h6>, <p>, <strong>, <em>, <ol>, <li>, <ul>, <blockquote>
- Metin bolumleri arasinda <br> kullan, KESINLIKLE <p> veya <h3> KULLANMA!
- Baslik/etiket icin duz metin yaz (ornegin "Anket Sonuclari" seklinde), HTML baslik tagi KULLANMA!

GRAFIK FORMAT KURALLARI (KRITIK!):
- Grafik basligini grafigin UZERINDE duz metin olarak yaz
- HTML <div class="chart"> etiketi ile grafik konteyneri olustur
- Her veri: <div class="chart-row"><span class="chart-label">Etiket</span><span class="chart-bar" style="width:XX%"></span><span class="chart-val">Deger</span></div>
- 4-6 veri satiri, en buyuk deger width:100%, digerleri oranli
- TABLO KULLANMA! Veriyi SADECE grafik olarak sun.
- GRAFIK ORNEK:
  Anket Sonuclari (kisi sayisi)
  <div class="chart">
  <div class="chart-row"><span class="chart-label">Futbol</span><span class="chart-bar" style="width:100%"></span><span class="chart-val">18</span></div>
  <div class="chart-row"><span class="chart-label">Basketbol</span><span class="chart-bar" style="width:72%"></span><span class="chart-val">13</span></div>
  <div class="chart-row"><span class="chart-label">Voleybol</span><span class="chart-bar" style="width:56%"></span><span class="chart-val">10</span></div>
  <div class="chart-row"><span class="chart-label">Yuzme</span><span class="chart-bar" style="width:44%"></span><span class="chart-val">8</span></div>
  </div>"""
        else:
            html_tag_rules = """HTML TAG KURALLARI (KRITIK!):
- IZIN VERILEN TAGLER: <b>, <u>, <br>, <table>, <tr>, <th>, <td>
- YASAK TAGLER: <h1>, <h2>, <h3>, <h4>, <h5>, <h6>, <p>, <div>, <span>, <strong>, <em>, <ol>, <li>, <ul>, <blockquote>
- Metin bolumleri arasinda <br> kullan, KESINLIKLE <p> veya <h3> KULLANMA!
- Baslik/etiket icin duz metin yaz (ornegin "1. Metin:" seklinde), HTML baslik tagi KULLANMA!

"""
            if text_only_mode:
                html_tag_rules = """HTML TAG KURALLARI (KRITIK — METIN TABANLI BAGLAM!):
- IZIN VERILEN TAGLER: <b>, <u>, <br>
- YASAK TAGLER: <table>, <tr>, <th>, <td>, <ol>, <li>, <ul>, <div>, <span>, <p>, <h1>-<h6>
- Tablo, grafik, yapisal veri VE HICBIR HTML TABLOSU KULLANMA!
- Sadece akici metin/hikaye yaz. Bu sablon gorsel-destekli DUZ METIN baglamidir.

METIN TABANLI BAGLAM OZEL KURALLARI (KRITIK!):
- Cevap bir ILLUSTRASYON gorseliyle desteklenecek, tablo gerekmez.
- Baglam SADECE duz paragraf/hikaye metni olmali.
- Veri, sayi listesi, tablo, grafik, liste YASAK — sadece akici Turkce anlatim."""
            else:
                html_tag_rules += """

TABLO VE YAPISAL OGE KURALLARI (KRITIK!):
- Tablo MUTLAKA gecerli HTML olsun: <table><tr><th>...</th></tr><tr><td>...</td></tr></table>
- Her <tr> icinde AYNI SAYIDA <th> veya <td> olsun (sutun sayisi tutarli olmali!)
- TUM satirlarda ayni sayida hucre olmali! Baslik satirinda 4 sutun varsa, BUTUN veri satirlarinda da 4 hucre olmali
- Her hucreyi BOS BIRAKMA — veri yoksa "-" yaz
- Hucre icinde SADECE duz metin veya sayi olsun (ic ice tablo, HTML entity KULLANMA)
- Ok isareti icin → (unicode karakter) kullan, &rarr; KULLANMA
- Tirnak isareti icin " (normal tirnak) kullan, &quot; KULLANMA
- Diyalog metinlerinde tirnak isaretlerini duz yaz: "..." seklinde
- Liste icin maddeler arasinda <br> kullan
- TABLO ORNEK YAPI (4 sutun, 3 satirlik):
  <table>
  <tr><th>Kriter</th><th>Secenek A</th><th>Secenek B</th><th>Secenek C</th></tr>
  <tr><td>Fiyat</td><td>50 TL</td><td>80 TL</td><td>65 TL</td></tr>
  <tr><td>Kalite</td><td>Orta</td><td>Yuksek</td><td>Dusuk</td></tr>
  </table>"""

        return f"""Asagidaki konu hakkinda bir BAGLAM METNI (senaryo + veri) olustur:

KONU: {topic}
KAYNAK DERS: {subject}
SINIF SEVIYESI: {grade}. sinif
BAGLAM TIPI: {ctx.type}

UZUNLUK: {gen.word_count_min}-{gen.word_count_max} kelime

HIKAYELESTIRME VE CESITLILIK (KRITIK!):
- Konuyu {grade}. sinif ogrencisinin GUNLUK HAYATINDA yasayabilecegi GERCEKCI bir hikayeye donustur.
- Her uretimde FARKLI ve YARATICI bir senaryo kurgula.
- KARAKTER ISIMLERI: Bu senaryoda KULLANILACAK isimler: {', '.join(get_names(4))}
  Bu isimleri AYNEN kullan, BASKA isim SECME!
- YASAK KALIPLAR (bunlara DUSME!):
  × "Ogrenci ders/proje icin arastirma yapti ve {veri_tipi_kucuk} hazirladi"
  × "Ali/Zeynep kitabinda okudu ve not aldi"
  × Ansiklopedik/ders kitabi ozeti tarzi yazi
  × Sadece isimleri degistirip ayni yapida metin uretme
- BUNUN YERINE:
  ✓ Canli, somut olaylar kurgula: aile gezisi, pazar alisverisi, bahce isi, piknik, spor, deney, gozlem, tatil, kamp...
  ✓ Farkli mekanlar kullan: ev, okul bahcesi, park, koy, orman, deniz kenari, ciftlik, muze, hayvanat bahcesi...
  ✓ Karakterlerin DUYGU ve DENEYIMLERINI yansit (heyecan, merak, saskinlik, sevinc, endise...)
  ✓ Olay orgusu olsun: baslangic → gelisme → sonuc
  ✓ Bilimsel bilgiyi hikayenin ICINE DOKUN — "ogrendiler" yerine "yasadilar/gozlemlediler/kesfettiler"
  ✓ Diyalog, mektup, gunluk, haber, deney raporu gibi FARKLI anlatim bicimleri dene
- Paragraf/senaryo OLAY ve DURUMU anlat. {veri_ref.capitalize()} veriyi paragrafta TEKRARLAMA — {veri_tipi_kucuk} AYRI gostersin.
- Paragraf {veri_tipi_kucuk}ya atifta bulunabilir ("asagidaki {veri_tipi_kucuk}yu inceleyin" gibi) ama {veri_ref} sayilari/degerleri KOPYALAMA.
- YASAK: Paragrafta {veri_tipi_kucuk}nun her satirini metin olarak aciklama — bu TEKRAR olur, validation FAIL!
- Baglam kurallarina (yapi, kelime sayisi) UYARAK hikayelestir.

{structure_text}

{rules_text}

BU BAGLAM UZERINDEN SORULACAK SORULAR ({ctx.question_count} adet):
{questions_section}

{name_section}

ONEMLI:
- Baglam metni yukaridaki TUM sorulari cevaplayacak bilgileri icermeli.
- Her soru icin gerekli veriyi/bilgiyi baglama yerlestir.
- Baglam metni BAGIMSIZ ve ANLASILIR olmali.
- {grade}. sinif ogrencisinin anlayabilecegi kelimeler kullan.
- Turkce dilbilgisi kurallarina dikkat et.
- Hikaye {grade}. sinif seviyesine uygun, ilgi cekici ve OZGUN olmali.
- Senaryo/paragrafta SORU CUMLESI YASAK — "Hic dusundunuz mu?", "Neden boyledir?", "Peki ya...?" gibi soru cumleleri HICBIR YERDE kullanma. Soru isareti (?) iceren cumle OLMAMALI!

KESINLIKLE YAPMA (KRITIK!):
- Baglam metnine SORU KOKLERI, "Soru 1:", "Soru 2:" gibi ifadeler EKLEME!
- Baglam metnine soru cumlesi, sik (A/B/C/D), veya cevap EKLEME!
- Sadece SENARYO ve VERI/{veri_tipi} yaz. Sorular AYRI ADIMLARDA uretilecek.
- "paragraph" alanina YALNIZCA senaryoyu ve {veri_tipi_kucuk}yu/veriyi yaz, baska bir sey EKLEME!
- Bilinen terimleri (alet, arac, kavram adlari) aciklama cumlesiyle DEGISTIRME.
  "Teleskop" = "Teleskop", "mercekli uzagigörür arac" DEGIL.
- <b> etiketi SADECE yapisal basliklar icin kullan: tablo basligi, "1. Metin:", "2. Metin:" gibi bolum etiketleri.
- Senaryo/hikaye anlatim metni icinde <b> ile kelime veya cumle VURGULAMA — soru cevabini belli eder.
- Her cumleden sonra <br><br> KOYMA! Bir paragraftaki cumleler arasinda <br> KULLANMA — cumleler ard arda aksin.
  <br><br> SADECE farkli icerik bolumleri arasinda kullan (senaryo ile tablo arasi, baslik ile metin arasi gibi).

{html_tag_rules}

"""

    async def generate_question_from_context(
        self,
        template: "QuestionTemplate",
        slot: "ContextQuestionSlot",
        topic: str,
        context_text: str,
        client: "GeminiClient",
        grade: int,
        subject: str = "turkce",
        cache_name: str | None = None,
        question_model: str = "gemini-3-flash-preview",
        previous_questions: list[dict] | None = None,
        validation_feedback: str | None = None,
    ) -> GeneratorOutput:
        """Generate a single sub-question from shared context.

        Args:
            template: The context template
            slot: Sub-question slot definition
            topic: Topic string
            context_text: Shared context text (already generated)
            client: GeminiClient
            grade: Target grade level
            subject: Subject code
            cache_name: Optional cache for PDF grounding
            question_model: Model to use
            previous_questions: List of previous questions for overlap prevention
            validation_feedback: Feedback from previous validation failure
        """
        from ..templates.schema import ContextQuestionSlot  # noqa: F811

        prompt = self._build_context_question_prompt(
            template, slot, topic, context_text, grade,
            previous_questions, validation_feedback,
        )

        logger.info(f"[CONTEXT_Q] Generating sub-question slot {slot.slot}: {slot.type}")
        logger.debug(
            f"[CONTEXT Q PROMPT]\n{'='*80}\n{prompt}\n{'='*80}"
        )

        if cache_name:
            output = await client.generate(
                model=question_model,
                prompt=prompt,
                output_schema=HTMLOutput,
                cache_name=cache_name,
            )
        else:
            output = await client.generate(
                model=question_model,
                prompt=prompt,
                output_schema=HTMLOutput,
                system_instruction=get_html_generation_system_prompt(grade),
            )

        # Determine option count/labels — slot.options_override > template.format.options > default
        _opt_count = 4
        _opt_labels = ["A", "B", "C", "D"]
        try:
            _fmt_opts = getattr(getattr(template, "format", None), "options", None)
            if _fmt_opts is not None:
                if getattr(_fmt_opts, "count", None):
                    _opt_count = _fmt_opts.count
                if getattr(_fmt_opts, "labels", None):
                    _opt_labels = list(_fmt_opts.labels)
        except Exception:
            pass
        _slot_override = getattr(slot, "options_override", None) or {}
        if isinstance(_slot_override, dict):
            if _slot_override.get("count"):
                _opt_count = _slot_override["count"]
            if _slot_override.get("labels"):
                _opt_labels = list(_slot_override["labels"])

        _all_option_values = [
            output.option_a,
            output.option_b,
            output.option_c,
            output.option_d,
            getattr(output, "option_e", None),
        ]
        _all_option_strategies = [
            output.option_a_strategy,
            output.option_b_strategy,
            output.option_c_strategy,
            output.option_d_strategy,
            getattr(output, "option_e_strategy", None),
        ]
        _all_option_reasonings = [
            output.option_a_reasoning,
            output.option_b_reasoning,
            output.option_c_reasoning,
            output.option_d_reasoning,
            getattr(output, "option_e_reasoning", None),
        ]

        options = {
            label: _all_option_values[i]
            for i, label in enumerate(_opt_labels[:_opt_count])
            if _all_option_values[i] is not None
        }
        option_reasoning = {
            label: {
                "strategy": _all_option_strategies[i],
                "reasoning": _all_option_reasonings[i],
            }
            for i, label in enumerate(_opt_labels[:_opt_count])
            if _all_option_strategies[i] is not None or _all_option_reasonings[i] is not None
        }

        # For numbered format, embed statements
        final_question = output.question
        if slot.options_style == "roman_numeral_combination" and output.statement_I:
            statements_text = (
                f"I. {output.statement_I}<br>"
                f"II. {output.statement_II}<br>"
                f"III. {output.statement_III}<br>"
                f"IV. {output.statement_IV}"
            )
            if "{statements}" in final_question:
                # Ensure <br> before and after statements block
                final_question = final_question.replace(
                    "{statements}", f"<br>{statements_text}<br>"
                )
            final_question = final_question.replace("\n", "<br>")
            # Clean up duplicate <br> tags from double insertion
            while "<br><br>" in final_question:
                final_question = final_question.replace("<br><br>", "<br>")

        # Strip stray bracket remnants from LLM output
        _BRACKET_RE = re.compile(r'\[([^\]]*)\]')
        final_question = _BRACKET_RE.sub(r'\1', final_question)
        options = {k: _BRACKET_RE.sub(r'\1', v) for k, v in options.items()}

        return GeneratorOutput(
            paragraph=context_text,
            key_concepts=[topic],
            difficulty_level="orta",
            question=final_question,
            key_word=output.key_word or "hangisidir",
            options=options,
            correct_answer=output.correct_answer,
            option_reasoning=option_reasoning,
            template_id=template.meta.id,
            format_id="llm_generated_html",
        )

    def _build_context_question_prompt(
        self,
        template: "QuestionTemplate",
        slot: "ContextQuestionSlot",
        topic: str,
        context_text: str,
        grade: int,
        previous_questions: list[dict] | None = None,
        validation_feedback: str | None = None,
    ) -> str:
        """Build prompt for a single sub-question from context."""
        import random as _rnd

        # Determine option count/labels — slot.options_override > template.format.options > default
        opt_count = 4
        opt_labels = ["A", "B", "C", "D"]
        try:
            fmt_opts = getattr(getattr(template, "format", None), "options", None)
            if fmt_opts is not None:
                if getattr(fmt_opts, "count", None):
                    opt_count = fmt_opts.count
                if getattr(fmt_opts, "labels", None):
                    opt_labels = list(fmt_opts.labels)
        except Exception:
            pass
        slot_override = getattr(slot, "options_override", None) or {}
        if isinstance(slot_override, dict):
            if slot_override.get("count"):
                opt_count = slot_override["count"]
            if slot_override.get("labels"):
                opt_labels = list(slot_override["labels"])
        # Slot-level word bounds override (falls back to slot.word_count_min/max defined above)
        slot_word_min = slot_override.get("word_count_min") if isinstance(slot_override, dict) else None
        slot_word_max = slot_override.get("word_count_max") if isinstance(slot_override, dict) else None
        effective_word_min = slot_word_min if slot_word_min is not None else slot.word_count_min
        effective_word_max = slot_word_max if slot_word_max is not None else slot.word_count_max
        labels_str = ", ".join(opt_labels)

        # Select stem
        if slot.soru_kokleri:
            stem = _rnd.choice(slot.soru_kokleri)
        else:
            stem = template.get_random_stem(template_id=template.meta.id)

        stem = self._resolve_stem_with_topic(stem, topic)
        rules = self._build_rules_block(stem)

        # For context templates, override the "AYNEN kullan" rule with placeholder instructions
        # Stems may have [...] or …Özne… placeholders that the LLM must fill from the context
        has_placeholders = "[" in stem or "…" in stem
        if has_placeholders:
            rules = rules.replace(
                "SORU KOKU: AYNEN kullan, <b>/<u> KORU:",
                "SORU KOKU: Asagidaki sablonu TEMEL AL. [...] ve …Özne… gibi yer tutuculari "
                "BAGLAM METNINDEKI bilgilerle DOLDUR. <b>/<u> etiketlerini KORU. "
                "Koseli parantez [...] ve uc nokta … isaretleri KALMAMALI:"
            )

        # Correct answer and distractor sections from template
        correct_section = self._format_correct_answer_section(template)
        distractor_section = self._format_distractor_section(template)

        # Slot-level enrichment: prepend slot-specific dogru_cevap_kurallari
        slot_correct_rules = getattr(slot, "dogru_cevap_kurallari", None) or []
        if slot_correct_rules:
            slot_correct_text = "\n".join(f"- {r}" for r in slot_correct_rules)
            correct_section = (
                f"## BU SORU ICIN DOGRU CEVAP KURALLARI (SLOT-OZEL — KRITIK!)\n"
                f"{slot_correct_text}\n\n"
                + correct_section
            )

        # Slot-level enrichment: prefer slot-specific distractor strategies
        slot_strategies = getattr(slot, "celdirici_stratejileri", None) or []
        if slot_strategies:
            slot_lines = ["## BU SORU ICIN CELDIRICI STRATEJILERI (SLOT-OZEL — ONCELIKLI!)"]
            for s in slot_strategies:
                ad = s.get("ad", "") if isinstance(s, dict) else str(s)
                aciklama = s.get("aciklama", "") if isinstance(s, dict) else ""
                nasil = s.get("nasil_olusturulur", "") if isinstance(s, dict) else ""
                slot_lines.append(f"- **{ad}** — {aciklama}")
                if nasil:
                    slot_lines.append(f"    NASIL: {nasil.strip()}")
            distractor_section = "\n".join(slot_lines) + "\n\n" + distractor_section

        # Option constraints from slot
        style_hints = {
            "complete_sentence": "tam cumle (8-25 kelime)",
            "short_phrase": "kisa ifade (2-8 kelime)",
            "topic_phrase": "kisa isim tamlamasi (2-6 kelime)",
            "keyword_set": "sozcuk seti (2-4 sozcuk, MUTLAKA ' - ' ile ayrilmis, VIRGUL KULLANMA), orn: 'bellek - veri - islem'",
            "question_sentence": "soru cumlesi (4-15 kelime, '?' ile biter), orn: 'Spor açken mi yapılmalıdır?'",
            "headline_title": "yaratici gazete manseti (2-6 kelime), orn: 'Guvercinlerin Pusulasi'",
            "roman_numeral_combination": "Roma rakami birlesimi (orn: 'I ve II')",
            "single_keyword": "tek kelime (1 sozcuk)",
        }
        style_hint = style_hints.get(slot.options_style, "kisa ifade")

        # Build format rule line if slot has custom format rule
        format_rule_line = ""
        if getattr(slot, "options_format_rule", None):
            format_rule_line = f"\n- FORMAT KURALI: {slot.options_format_rule}"

        option_constraints = f"""## SECENEK KISITLAMALARI
- TAM OLARAK {opt_count} SECENEK uret: {labels_str}. Ekstra secenek EKLEMEYIN, eksik BIRAKMAYIN.
- Kelime sayisi: {effective_word_min}-{effective_word_max}
- Stil: {slot.options_style} ({style_hint})
- {opt_count} secenek birbirine yakin uzunlukta olmali (±1-2 kelime)
- DIL YAPISI: {opt_count} secenek AYNI dilbilgisel yapida olmali (hepsi isim tamlamasi VEYA hepsi cumle VEYA hepsi sifat+isim)
- FAIL ORNEK: A) "Güneşle ısınma" B) "Rutubet" C) "Toprak kayması" D) "Yağmur suyunu biriktirerek tasarruf etmek" → D farklı yapı!
- PASS ORNEK: A) "Isı yalıtımı" B) "Su tasarrufu" C) "Enerji verimliliği" D) "Geri dönüşüm" → hepsi isim tamlaması
- TERIM KORUMA (KRITIK!): Bilinen kavram, alet ve terimleri (Isli Cam, Teleskop, Pusula, Termometre, Mikroskop vb.)
  kendi adiyla kullan. Tanimlama cumlesiyle DEGISTIRME!
  × YANLIS: "dumanla karartilmis saydam madde" (Isli Cam yerine)
  × YANLIS: "mercekli gelismis uzagigörür arac" (Teleskop yerine)
  ✓ DOGRU: "Isli Cam", "Teleskop", "Pusula" — AYNEN yaz.{format_rule_line}"""

        # Slot-specific rules (slot_rules from template YAML)
        _slot_rules = getattr(slot, 'slot_rules', None) or []
        if _slot_rules:
            rules_text = "\n".join(f"- {r}" for r in _slot_rules)
            option_constraints += f"\n\nSLOT OZEL KURALLARI (BU SORU ICIN GECERLI):\n{rules_text}"

        # Context dependency section (critical for reducing retry rate)
        context_dep_section = """## BAGLAM BAGIMLILIGI (KRITIK! — FAIL = retry)
- Soru SADECE yukaridaki baglam metnindeki VERI/TABLO/SENARYO kullanilarak cevaplanabilir olmali.
- Genel kultur bilgisiyle cozulebilecek soru YASAK — validation FAIL olur!
- Baglamdaki SPESIFIK rakamlar, isimler, tablodaki degerler soruya dahil et.
- TEST: Baglam metni olmadan bu soru cevaplanabilir mi? Eger evet → YANLIS soru, degistir.
- ORNEK FAIL: "Depremde ne yapilmali?" (genel bilgi, baglam gerekmez)
- ORNEK PASS: "Tabloya gore en cok hasar goren bolge hangisidir?" (tablodaki veri gerekli)

## BAGLAM SORUSU ≠ KLASIK SORU (FARK ONEMLI!)
- Soru koku baglamdaki SPESIFIK veriyi/bilgiyi hedeflemeli, genel bilgi sorusu gibi OLMAMALI.
- YANLIS SORU KOKU: "Asagidakilerden hangisi dogrudur?" (klasik soru — baglama referans yok)
- DOGRU SORU KOKU: "Tablodaki verilere gore...", "Senaryodaki bilgilere gore...", "Grafige bakarak..." (baglama ozgu)
- Soru koku MUTLAKA baglam kaynagina referans vermeli (tablo, grafik, senaryo, anket vb.)

## CELDIRICI KALITE KONTROLU (KRITIK!)
- CELDIRICI TESTI: Her celdirici icin sor: "Baglam metni olmadan bu secenek elenebilir mi?"
  Eger evet → ZAYIF celdirici! Baglamdaki SPESIFIK bir veriyi yanlis yorumlayan celdirici yaz.
- Her celdirici baglamdaki belirli bir bilgiyi/veriyi YANLIS YORUMLAMALI veya CARPITMALI.
- Genel dogru/yanlis bilgiye dayanan celdirici YASAK (metin-disi bilgi yasagi).
- Celdiriciler birbirinden FARKLI hata turlerini temsil etmeli."""

        # Previous questions section (overlap prevention)
        prev_section = ""
        if previous_questions:
            prev_lines = ["## ONCEKI SORULAR (CAKISMA ONLEME — FARKLI SORU URET!)"]
            for i, pq in enumerate(previous_questions, 1):
                prev_lines.append(f"  Soru {i}: {pq.get('question', '')}")
                prev_lines.append(f"    Dogru: {pq.get('correct_answer', '')} — {pq.get('correct_text', '')}")
            prev_lines.append("BU SORULARLA AYNI KONUYU/CEVABI SORME! Farkli bir aci kullan.")
            prev_lines.append("IPUCU ZINCIRI YASAK: Bu sorunun cevabi/secenekleri onceki sorulara ipucu VERMEMELI.")
            prev_lines.append("Onceki sorunun dogru cevap metni bu sorunun seceneklerinde OLMAMALI.")
            prev_lines.append("BILISSEL ASAMALILIK: Onceki soru veri okumaysa, bu soru yorum/degerlendirme olsun (basit→karmasik).")
            prev_section = "\n".join(prev_lines)

        # Header template signal — STRICT: used only as semantic hint; NEVER include in question.
        _header = getattr(template, "header_template", None)
        header_section = ""
        if _header:
            _is_independent = "bagimsiz" in (_header or "").lower() or "BAGIMSIZ" in (_header or "")
            indep_hint = ""
            if _is_independent:
                indep_hint = (
                    "- Sorular birbirinden BAGIMSIZ cevaplanmalidir: Bu soru diger soru ile "
                    "ipucu zinciri OLUSTURMAMALI; cevap/secenekler diger soruya hint vermemeli.\n"
                )
            header_section = (
                "## GRUP METADATA (SADECE ANLAMSAL IPUCU — ASLA QUESTION ALANINA KOPYALAMA!)\n"
                "- KESIN YASAK: question alanina '1-2. sorulari', '1-3. sorulari' gibi "
                "GRUP BASLIGI veya YONLENDIRME ifadesi yazma. Bu baslik RENDER tarafindan ayri "
                "bir yerde gosterilecek. question alanina SADECE o slotun soru kokunu yaz.\n"
                f"{indep_hint}"
            )

        prompt = f"""BAGLAM TEMELLI SORU OLUSTUR (Soru {slot.slot}/{template.context.question_count}):

## SORU TIPI
{slot.type}

## KONU
{topic}

## BAGLAM METNI
{context_text}

## SINIF SEVIYESI
{grade}. sinif

## KRITIK KURAL — QUESTION ALANI
- `question` alanina SADECE ve YALNIZCA asagida belirtilen SORU KOKU (stem) cumlesini yaz
- Paragrafi, baglam metnini, tabloyu, hikayeyi `question` alanina KOPYALAMA — VALIDATION FAIL OLUR!
- `question` SADECE tek bir soru cumlesi olmali (ornek: "Bu tabloya gore asagidakilerden hangisi soylenemez?")
- YASAK: Context_text icerigi, paragraf cumleleri, tablo verileri question alaninda TEKRAR EDILMEMELI

{header_section}{rules}

{correct_section}

{distractor_section}

{option_constraints}

{context_dep_section}

{prev_section}"""

        if validation_feedback:
            prompt += self._format_validation_feedback_section(validation_feedback)

        return prompt
