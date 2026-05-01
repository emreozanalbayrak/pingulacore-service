"""
Soru uretim pipeline'i - LangGraph State Machine
7 baslikli YAML sablon formati: meta, context, header_template, format, dogru_cevap, distractors, use_shared_strategies

Pipeline akisi (8 node, 2 yol):

  Gorselli yol (gorsel.ana_gorsel.gerekli=true, varsayilan):
    1) YAML yukle & parse et
    2) Mega soru uret: sahne + soru + siklar + cozum (LLM-1)
    3) Batch dogrula (LLM-2)      -- gecersizse -> 2'ye don (max 3)
    4) Bagimsiz cozum (LLM-3)     -- yanlissa  -> 2'ye don (max 3)
    5) Gorsel uret (LLM-4a + 4b)  -- ana + kosullu sik gorselleri
    6) Gorsel dogrula (LLM-5)     -- gecersizse -> 5'e don (max 3)
    7) Gorsel cozum (LLM-6)       -- yanlissa  -> 5'e don (max 3)
    8) Final cikti

  Gorselsiz yol (gorsel.ana_gorsel.gerekli=false):
    1) YAML yukle & parse et
    2) Mega soru uret (LLM-1)
    3) Batch dogrula (LLM-2)      -- gecersizse -> 2'ye don (max 3)
    4) Bagimsiz cozum (LLM-3)     -- yanlissa  -> 2'ye don (max 3)
    5) Final cikti                 -- gorsel adimlari atlanir
"""
from __future__ import annotations

import json
import re
from operator import add
from pathlib import Path
from typing import Annotated, Optional, TypedDict

from langgraph.graph import END, StateGraph

from legacy_app.geometri.pomodoro.chains.chain_generate_visual_question import generate_visual_question
from legacy_app.geometri.pomodoro.chains.chain_validate_batch import validate_batch
from legacy_app.geometri.pomodoro.chains.chain_solve_question import solve_question
from legacy_app.geometri.pomodoro.chains.chain_generate_image import generate_images
from legacy_app.geometri.pomodoro.chains.chain_validate_visual import validate_visual
from legacy_app.geometri.pomodoro.chains.chain_verify_currency import verify_currency
from legacy_app.geometri.pomodoro.chains.chain_solve_visual_question import solve_visual_question
from legacy_app.geometri.pomodoro.models import (
    BatchValidation,
    CurrencyVerification,
    GeneratedImages,
    GeneratedVisualQuestion,
    QuestionSolution,
    VisualQuestionSolution,
    VisualValidation,
)
from legacy_app.geometri.pomodoro.pipeline_log import pipeline_log
from legacy_app.geometri.pomodoro.variant_rotation import get_variant_names, select_next_variant
from legacy_app.geometri.pomodoro.yaml_loader import ParsedTemplate, load_and_parse_template
from legacy_app.shared.src.build_question_html import build_question_html
from legacy_app.shared.src.render_question_html import render_question_html


MAX_QUESTION_ATTEMPTS = 3
MAX_VALIDATION_ATTEMPTS = 3
MAX_SOLVER_ATTEMPTS = 3
MAX_IMAGE_ATTEMPTS = 3
MAX_VISUAL_SOLVE_ATTEMPTS = 3
MAX_CURRENCY_VERIFY_ATTEMPTS = 2

VISUAL_REFERENCE_PATTERNS = [
    # Çekimli görsel/şekil/şema/tablo/grafik/harita — açık konum/ilgi atıfları
    r"\bgörsel(?:de|deki|den|e)\b",        # görselde, görseldeki, görselden, görsele
    r"\bşekl?(?:e|de|deki|den)\b",         # şekle, şekilde, şekildeki, şekilden
    r"\bşema(?:da|daki|dan|ya)\b",
    r"\btablo(?:da|daki|dan|ya)\b",
    r"\bgrafik(?:te|teki|ten|e)\b",
    r"\bharita(?:da|daki|dan|ya)\b",
    # Yön+nesne bileşimleri
    r"\b(yan|sol|sağ|üst|alt)daki (görsel|şekil|şema|tablo|grafik|etiket)\b",
    r"\b(yukarıdaki|aşağıdaki) (görsel|şekil|şema|tablo|grafik|etiket)\b",
    # Yerleşik bileşik ifadeler
    r"\b(akış şeması|üretim zinciri|şemaya göre)\b",
]
VISUAL_REFERENCE_RE = re.compile("|".join(VISUAL_REFERENCE_PATTERNS), re.IGNORECASE)

# Görsel atıfmış gibi görünen ama aslında deyim olan kalıplar.
# Bunlar VISUAL_REFERENCE_RE ile eşleşirse false-positive olarak atılır.
_VISUAL_IDIOM_RE = re.compile(
    r"\b(aynı|bu|söz konusu|o)\s+şekil(de|deki|den|e)?\b",
    re.IGNORECASE,
)


def _question_explicitly_requires_visual(question_data: dict) -> bool:
    """Üretilen metin öğrenciyi açıkça bir görsele yönlendiriyorsa True döner.

    Yalnızca öğrenciye yönelik metinler kontrol edilir (scenario_text, question_stem,
    solution_explanation). scene_description, LLM'in iç meta verisidir ve sıkça
    "görsel bulunmamaktadır" gibi ifadeler içerdiğinden kontrol dışı tutulur.
    """
    text_parts: list[str] = []

    # Öğrenciye yönelik metin alanları — scene_description dahil değil
    value = question_data.get("scenario_text")
    if isinstance(value, str):
        text_parts.append(value)

    for question in question_data.get("questions") or []:
        if not isinstance(question, dict):
            continue
        for key in ("question_stem", "solution_explanation"):
            value = question.get(key)
            if isinstance(value, str):
                text_parts.append(value)

    combined = "\n".join(text_parts)

    # Deyimsel kullanımları temizledikten sonra görsel atıf ara
    cleaned = _VISUAL_IDIOM_RE.sub("", combined)
    return bool(VISUAL_REFERENCE_RE.search(cleaned))


def _write_question_snapshot(
    question_data: dict,
    output_dir: str | Path,
    stage: str,
) -> str:
    """Persist the latest question payload with pipeline stage metadata."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    payload = dict(question_data)
    payload["pipeline_stage"] = stage

    question_path = output_dir / "question.json"
    with open(question_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    return str(question_path)


def _build_detailed_answer_text(question_data: dict) -> Optional[str]:
    """Build a readable answer string for detailed renders.

    Coklu soru destegi: her sorunun cevabini ayri satirda gosterir.
    """
    questions = question_data.get("questions") or []
    if not questions:
        return None

    if len(questions) == 1:
        q = questions[0]
        correct = q.get("correct_answer")
        options = q.get("options") or {}
        if not correct:
            return None
        answer_value = options.get(correct, "")
        return f"{correct}) {answer_value}" if answer_value else str(correct)

    # Coklu soru: her birinin cevabini goster
    lines = []
    for q in questions:
        num = q.get("question_number", "?")
        correct = q.get("correct_answer", "?")
        options = q.get("options") or {}
        answer_value = options.get(correct, "")
        if answer_value:
            lines.append(f"S{num}: {correct}) {answer_value}")
        else:
            lines.append(f"S{num}: {correct}")
    return "  |  ".join(lines)


def _get_starred_output_dir(output_dir: str | Path) -> Path:
    """Sorunlu ama uretilmis ciktinin klasor adini * ile isaretler."""
    output_path = Path(output_dir)
    if output_path.name.startswith("*"):
        return output_path
    return output_path.with_name(f"*{output_path.name}")


def _prepare_final_output_dir(output_dir: str | Path, *, is_problematic: bool) -> Path:
    """Gerekirse mevcut cikti klasorunu * ile isaretleyerek tasir."""
    requested = Path(output_dir)
    if not is_problematic:
        requested.mkdir(parents=True, exist_ok=True)
        return requested

    starred = _get_starred_output_dir(requested)
    if requested.exists() and requested != starred:
        if starred.exists():
            counter = 2
            base_name = starred.name
            while True:
                candidate = starred.with_name(f"{base_name}_{counter}")
                if not candidate.exists():
                    starred = candidate
                    break
                counter += 1
        requested.rename(starred)
    starred.mkdir(parents=True, exist_ok=True)
    return starred


# ── State ─────────────────────────────────────────────────────────────────

class VisualQuestionPipelineState(TypedDict, total=False):
    # --- girdiler ---
    yaml_path: str
    difficulty: str
    output_dir: str
    variant_name: Optional[str]

    # --- parse edilmis sablon ---
    template: Optional[dict]
    has_visual_options: bool
    requires_visual: bool

    # --- Chain 1: Mega soru uretimi ---
    generated_question: Optional[dict]

    # --- Chain 2: Dogrulama ---
    validation_status: Optional[str]
    validation_feedback: Optional[str]
    question_attempts: int
    validation_failures: int

    # --- Chain 3: Bagimsiz cozum ---
    solver_correct: Optional[bool]
    solver_explanation: Optional[str]
    solver_results: Optional[list[dict]]
    solver_failures: int

    # --- Chain 4: Gorsel uretimi ---
    generated_images: Optional[dict]
    image_attempts: int

    # --- Chain 5: Gorsel dogrulama ---
    visual_validation_status: Optional[str]
    visual_validation_feedback: Optional[str]

    # --- Chain 6: Gorsel cozum ---
    visual_solver_correct: Optional[bool]
    visual_solver_explanation: Optional[str]
    visual_solver_issues: Optional[list[str]]
    visual_solver_results: Optional[list[dict]]
    visual_solve_attempts: int

    # --- Chain (opsiyonel): Turk Lirasi sadakat dogrulama ---
    currency_verify_status: Optional[str]  # "ok" | "mismatch" | "skipped"
    currency_verify_feedback: Optional[str]
    currency_verify_attempts: int

    # --- benzerlik / ek feedback ---
    extra_feedback: Optional[str]

    # --- final ---
    final_output_path: Optional[str]
    log: Annotated[list[str], add]


# ── Node fonksiyonlari ────────────────────────────────────────────────────

def node_load_yaml(state: VisualQuestionPipelineState) -> dict:
    """YAML yukle ve parse et."""
    pipeline_log("pipeline", "Adım 1/8: YAML yükleniyor ve şablon parse ediliyor…")
    template = load_and_parse_template(state["yaml_path"])

    # Varyant otomatik secimi: variant_name verilmemisse siradakini sec
    variant_name = state.get("variant_name")
    log_entries = []
    if variant_name is None:
        available = get_variant_names(template)
        if available:
            variant_name = select_next_variant(state["yaml_path"], available)
            pipeline_log("pipeline", f"Varyant otomatik seçildi: {variant_name}")
            log_entries.append(f"[load_yaml] Varyant otomatik secildi: {variant_name} "
                               f"(mevcut: {', '.join(available)})")

    log_entries.append(f"[load_yaml] YAML yuklendi: {state['yaml_path']} "
                       f"(has_visual_options={template.has_visual_options}, "
                       f"requires_visual={template.requires_visual})")

    return {
        "template": template.model_dump(),
        "variant_name": variant_name,
        "has_visual_options": template.has_visual_options,
        "requires_visual": template.requires_visual,
        "log": log_entries,
    }


def node_generate_question(state: VisualQuestionPipelineState) -> dict:
    """Mega soru uretimi: sahne + soru + siklar + cozum (LLM-1)."""
    pipeline_log("pipeline", "Adım 2/8: Mega soru üretimi (LLM-1) — sahne, soru, şıklar, HTML…")
    template = ParsedTemplate(**state["template"])
    difficulty = state.get("difficulty", "orta")
    attempts = state.get("question_attempts", 0) + 1

    # Retry durumunda onceki feedback'i topla
    feedback_parts = []
    if state.get("extra_feedback"):
        feedback_parts.append(state["extra_feedback"])
    if state.get("validation_feedback"):
        feedback_parts.append(f"Doğrulama: {state['validation_feedback']}")
    if state.get("solver_explanation"):
        feedback_parts.append(f"Çözüm kontrolü: {state['solver_explanation']}")
    feedback = "\n\n".join(feedback_parts) if feedback_parts else None

    variant_name = state.get("variant_name")
    question = generate_visual_question(template, difficulty, feedback, variant_name)
    question_data = question.model_dump()
    if variant_name:
        question_data["selected_variant"] = variant_name
    # YAML acikca gorselsiz ise (ana_gorsel.gerekli=false veya image_type gorselsiz/gorsel_yok)
    # LLM'in urettigi metindeki gorsel referanslarini override olarak KULLANMA.
    # Sadece gorsel belirsiz olan sablonlarda override uygula.
    yaml_requires_visual = state.get("requires_visual", False)
    if yaml_requires_visual:
        requires_visual = True
    elif template.requires_visual is False:
        # YAML acikca gorselsiz — override yapma
        requires_visual = False
        if _question_explicitly_requires_visual(question_data):
            pipeline_log(
                "pipeline",
                "⚠️ Gorselsiz sablonda LLM gorsel referansi uretmis — override YAPILMADI.",
            )
    else:
        requires_visual = _question_explicitly_requires_visual(question_data)
    question_path = _write_question_snapshot(
        question_data,
        state.get("output_dir", "output/visual_questions"),
        stage="question_generated",
    )

    actual = len(question.questions)
    return {
        "generated_question": question_data,
        "question_attempts": attempts,
        "requires_visual": requires_visual,
        "log": [
            f"[generate_question] Mega soru uretildi (deneme {attempts}/{MAX_QUESTION_ATTEMPTS}) — {actual} soru",
            (
                "[generate_question] Soru metni gorsele acik atif yaptigi icin ana gorsel zorunlu kabul edildi"
                if requires_visual and not template.requires_visual
                else f"[generate_question] Ana gorsel gereksinimi: {requires_visual}"
            ),
            f"[generate_question] Taslak JSON kaydedildi: {question_path}",
        ],
    }


def node_validate_question(state: VisualQuestionPipelineState) -> dict:
    """Batch dogrulama (LLM-2). Oncelikle question_count kontrolu yapar."""
    pipeline_log("pipeline", "Adım 3/8: Toplu doğrulama (LLM-2)…")
    template = ParsedTemplate(**state["template"])

    # Kesin soru sayisi kontrolu (kod seviyesi — LLM'e sorulmaz)
    expected = template.question_count
    actual = len(state["generated_question"].get("questions", []))
    if actual != expected:
        validation_failures = state.get("validation_failures", 0) + 1
        feedback = (
            f"SORU SAYISI HATASI: {expected} soru bekleniyor ancak {actual} soru üretildi. "
            f"Tam olarak {expected} adet soru, questions listesinde ayrı QuestionItem olarak üretilmeli."
        )
        pipeline_log("pipeline", f"⚠️ {feedback}")
        return {
            "validation_status": "revizyon_gerekli",
            "validation_feedback": feedback,
            "validation_failures": validation_failures,
            "log": [f"[validate_question] ⚠️ Soru sayisi hatasi: beklenen={expected}, uretilen={actual}"],
        }

    question_text = json.dumps(state["generated_question"], ensure_ascii=False, indent=2)
    validation = validate_batch(template, question_text)

    validation_failures = state.get("validation_failures", 0)
    if validation.overall_status != "gecerli":
        validation_failures += 1

    return {
        "validation_status": validation.overall_status,
        "validation_feedback": validation.feedback or "",
        "validation_failures": validation_failures,
        "log": [
            f"[validate_question] Sonuc: {validation.overall_status}"
            + (f" - {validation.feedback[:120]}" if validation.feedback else "")
        ],
    }


def node_solve_question(state: VisualQuestionPipelineState) -> dict:
    """Bagimsiz soru cozumu (LLM-3). Tum sorulari cozer."""
    pipeline_log("pipeline", "Adım 4/8: Bağımsız metin çözümü (LLM-3)…")
    template = ParsedTemplate(**state["template"])
    question = GeneratedVisualQuestion(**state["generated_question"])

    solutions = solve_question(template, question)  # list[QuestionSolution]

    all_correct = all(s.matches_expected for s in solutions)
    solver_failures = state.get("solver_failures", 0)
    if not all_correct:
        solver_failures += 1

    # Yanlis sorularin aciklamalarini topla (retry feedback icin)
    wrong_explanations = [
        f"Soru {i+1}: {s.reasoning}"
        for i, s in enumerate(solutions) if not s.matches_expected
    ]
    explanation = "\n".join(wrong_explanations) if wrong_explanations else solutions[0].reasoning

    log_parts = [
        f"[solve_question] {len(solutions)} soru cozuldu — tumu dogru: {all_correct}"
    ]
    for i, s in enumerate(solutions):
        log_parts.append(
            f"  Soru {i+1}: cevap={s.chosen_answer} uyusma={s.matches_expected} guven={s.confidence}"
        )

    return {
        "solver_correct": all_correct,
        "solver_explanation": explanation,
        "solver_results": [s.model_dump() for s in solutions],
        "solver_failures": solver_failures,
        "log": log_parts,
    }


def node_generate_images(state: VisualQuestionPipelineState) -> dict:
    """Gorsel uretimi: ana + kosullu sik gorselleri (LLM-4a + 4b)."""
    pipeline_log("pipeline", "Adım 5/8: Görsel üretimi (LLM-4)…")
    template = ParsedTemplate(**state["template"])
    question = GeneratedVisualQuestion(**state["generated_question"])
    output_dir = state.get("output_dir", "output/visual_questions")
    attempts = state.get("image_attempts", 0) + 1

    # Retry durumunda onceki feedback
    feedback_parts = []
    if state.get("visual_validation_feedback"):
        feedback_parts.append(f"Görsel doğrulama: {state['visual_validation_feedback']}")
    if state.get("visual_solver_explanation"):
        feedback_parts.append(f"Görsel çözüm: {state['visual_solver_explanation']}")
    if state.get("visual_solver_issues"):
        feedback_parts.append(
            "Görsel çözücü sorunları: "
            + "; ".join(state["visual_solver_issues"])
        )
    if state.get("currency_verify_feedback"):
        feedback_parts.append(f"Türk Lirası sadakat: {state['currency_verify_feedback']}")
    feedback = "\n\n".join(feedback_parts) if feedback_parts else None

    images = generate_images(template, question, output_dir, feedback)
    return {
        "generated_images": images.model_dump(),
        "image_attempts": attempts,
        "log": [
            f"[generate_images] Gorsel uretildi (deneme {attempts}/{MAX_IMAGE_ATTEMPTS}): "
            f"{images.main_image_path}"
            + (f" + {len(images.option_images)} sik gorseli" if images.option_images else "")
        ],
    }


def node_validate_visual(state: VisualQuestionPipelineState) -> dict:
    """Gorsel dogrulama (LLM-5)."""
    pipeline_log("pipeline", "Adım 6/8: Görsel doğrulama (LLM-5)…")
    template = ParsedTemplate(**state["template"])
    question = GeneratedVisualQuestion(**state["generated_question"])
    images = GeneratedImages(**state["generated_images"])

    validation = validate_visual(
        template, question, images.main_image_path, images.option_images,
    )
    return {
        "visual_validation_status": validation.overall_status,
        "visual_validation_feedback": validation.feedback or "",
        "log": [
            f"[validate_visual] Sonuc: {validation.overall_status}"
            + (f" - basarisiz: {validation.failed_targets}" if validation.failed_targets else "")
        ],
    }


def node_verify_currency(state: VisualQuestionPipelineState) -> dict:
    """Turk Lirasi sadakat dogrulamasi (opsiyonel).

    Sadece template.real_currency=True oldugunda calisir. Uretilen ana
    gorseldeki banknot ve madeni paralari manifest'teki referanslarla
    karsilastirir. Basarisiz olursa MAX_CURRENCY_VERIFY_ATTEMPTS'e kadar
    gorsel uretimini tetikler; limit asilirsa uyariyla devam eder.
    """
    template = ParsedTemplate(**state["template"])

    if not template.real_currency:
        return {
            "currency_verify_status": "skipped",
            "currency_verify_feedback": None,
            "log": ["[verify_currency] Bayrak kapali, atlaniyor."],
        }

    images = GeneratedImages(**state["generated_images"])
    attempts = state.get("currency_verify_attempts", 0) + 1

    # Denominasyonlara LLM-1 karar verir (question.chosen_denominations)
    question = GeneratedVisualQuestion(**state["generated_question"])
    denom_ids = question.chosen_denominations or []
    if not denom_ids:
        return {
            "currency_verify_status": "skipped",
            "currency_verify_feedback": None,
            "log": ["[verify_currency] LLM chosen_denominations bos, atlaniyor."],
        }

    pipeline_log(
        "pipeline",
        f"Turk Lirasi sadakat kontrolu (deneme {attempts}/{MAX_CURRENCY_VERIFY_ATTEMPTS})…",
    )
    verification = verify_currency(
        main_image_path=images.main_image_path,
        required_denominations=denom_ids,
    )

    status = "ok" if verification.all_match else "mismatch"
    feedback_lines: list[str] = []
    if not verification.all_match:
        if verification.issues:
            feedback_lines.append("Türk Lirası tasarım sorunları: " + "; ".join(verification.issues))
        if verification.missing_denominations:
            feedback_lines.append(
                "Gorselde eksik/tanınamaz para birimleri: "
                + ", ".join(verification.missing_denominations)
            )
        feedback_lines.append(
            "Ekli referans görselleri birebir kopyala: portre, renk kodu, rakam ve desen eşleşmeli."
        )
    feedback = "\n".join(feedback_lines) if feedback_lines else None

    log_parts = [
        f"[verify_currency] Sonuc: {status} "
        f"(sorun={len(verification.issues)}, eksik={len(verification.missing_denominations)})"
    ]
    if feedback:
        log_parts.append(f"[verify_currency] Geri bildirim: {feedback[:160]}")

    return {
        "currency_verify_status": status,
        "currency_verify_feedback": feedback,
        "currency_verify_attempts": attempts,
        "log": log_parts,
    }


def node_solve_visual_question(state: VisualQuestionPipelineState) -> dict:
    """Gorsel uzerinden bagimsiz cozum (LLM-6). Tum sorulari cozer."""
    pipeline_log("pipeline", "Adım 7/8: Görsel üzerinden çözüm (LLM-6)…")
    template = ParsedTemplate(**state["template"])
    question = GeneratedVisualQuestion(**state["generated_question"])
    images = GeneratedImages(**state["generated_images"])
    attempts = state.get("visual_solve_attempts", 0) + 1

    solutions = solve_visual_question(
        template, question, images.main_image_path, images.option_images,
    )  # list[VisualQuestionSolution]

    all_correct = all(s.matches_expected for s in solutions)

    # Tum gorsel sorunlarini topla
    all_issues = []
    for s in solutions:
        all_issues.extend(s.visual_issues)

    # Yanlis sorularin aciklamalarini topla
    wrong_explanations = [
        f"Soru {i+1}: {s.reasoning}"
        for i, s in enumerate(solutions) if not s.matches_expected
    ]
    explanation = "\n".join(wrong_explanations) if wrong_explanations else solutions[0].reasoning

    log_parts = [
        f"[solve_visual] {len(solutions)} soru cozuldu — tumu dogru: {all_correct}"
    ]
    for i, s in enumerate(solutions):
        log_parts.append(
            f"  Soru {i+1}: cevap={s.chosen_answer} uyusma={s.matches_expected}"
            + (f" sorunlar={s.visual_issues}" if s.visual_issues else "")
        )

    return {
        "visual_solver_correct": all_correct,
        "visual_solver_explanation": explanation,
        "visual_solver_issues": all_issues,
        "visual_solver_results": [s.model_dump() for s in solutions],
        "visual_solve_attempts": attempts,
        "log": log_parts,
    }


def node_finalize(state: VisualQuestionPipelineState) -> dict:
    """Final cikti olustur."""
    requested_output_dir = Path(state.get("output_dir", "output/visual_questions"))
    if state.get("requires_visual", True):
        is_problematic = not state.get("visual_solver_correct", False)
    else:
        is_problematic = not state.get("solver_correct", False)
    output_dir = _prepare_final_output_dir(requested_output_dir, is_problematic=is_problematic)

    # HTML ciktisini once uret: chain_generate_visual_question post-shuffle
    # html_content'i bosalttigi icin build_question_html kanonik HTML kaynagidir.
    # Bu HTML state'e geri yazilir ki JSON snapshot'inda da post-shuffle sira yer alsin.
    images = GeneratedImages(**state["generated_images"]) if state.get("generated_images") else None
    questions = state["generated_question"].get("questions") or []
    html_content = state["generated_question"].get("html_content", "")

    if questions:
        html_content = build_question_html(
            question_data=state["generated_question"],
            output_dir=output_dir,
            main_image_path=images.main_image_path if images else None,
            option_images=images.option_images if images else None,
            inline_images=True,
        )
        state["generated_question"]["html_content"] = html_content

    # Soru verisini finalize et (post-shuffle, post-build_question_html)
    question_path = _write_question_snapshot(
        state["generated_question"],
        output_dir,
        stage="finalized",
    )
    if html_content:
        html_path = output_dir / "question.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        preview_html_path = html_path
        if questions:
            preview_html_path = output_dir / "question.preview.html"
            preview_html = build_question_html(
                question_data=state["generated_question"],
                output_dir=output_dir,
                main_image_path=images.main_image_path if images else None,
                option_images=images.option_images if images else None,
                inline_images=False,
            )
            with open(preview_html_path, "w", encoding="utf-8") as f:
                f.write(preview_html)

        render_logs = [f"[render] HTML kaydedildi: {html_path}"]
        if preview_html_path != html_path:
            render_logs.append(f"[render] Preview HTML kaydedildi: {preview_html_path}")

        question_png, detailed_png = render_question_html(
            preview_html_path,
            output_dir,
            answer_text=_build_detailed_answer_text(state["generated_question"]),
        )
        render_logs.append(f"[render] PNG kaydedildi: {question_png}")
        render_logs.append(f"[render] PNG kaydedildi: {detailed_png}")
    else:
        render_logs = []

    return {
        "final_output_path": str(output_dir),
        "log": [
            (
                f"[finalize] Sorunlu cikti * ile isaretlendi: {output_dir}"
                if is_problematic else
                f"[finalize] Cikti kaydedildi: {output_dir}"
            ),
            f"[finalize] Final JSON kaydedildi: {question_path}",
            *render_logs,
        ],
    }


# ── Kosullu yonlendirme ──────────────────────────────────────────────────

def route_after_validation(state: VisualQuestionPipelineState) -> str:
    """Dogrulama sonrasi: gecerli → cozume, gecersiz → soruyu yeniden uret."""
    if state.get("validation_status") == "gecerli":
        return "solve_question"
    if state.get("validation_failures", 0) >= MAX_VALIDATION_ATTEMPTS:
        return "solve_question"
    return "generate_question"


def route_after_solving(state: VisualQuestionPipelineState) -> str:
    """Cozum sonrasi: dogru → gorsele (veya gorselsizse finalize), yanlis → soruyu bastan uret."""
    if not state.get("requires_visual", True):
        if state.get("solver_correct"):
            return "finalize"
        if state.get("solver_failures", 0) >= MAX_SOLVER_ATTEMPTS:
            return "finalize"
        return "generate_question"
    if state.get("solver_correct"):
        return "generate_images"
    if state.get("solver_failures", 0) >= MAX_SOLVER_ATTEMPTS:
        return "generate_images"
    return "generate_question"


def route_after_visual_validation(state: VisualQuestionPipelineState) -> str:
    """Gorsel dogrulama sonrasi: uygun → TL sadakat kontrolu, revizyon → yeniden uret."""
    if state.get("visual_validation_status") == "uygun":
        return "verify_currency"
    if state.get("image_attempts", 0) >= MAX_IMAGE_ATTEMPTS:
        return "verify_currency"
    return "generate_images"


def route_after_currency_verify(state: VisualQuestionPipelineState) -> str:
    """TL sadakat kontrolu sonrasi yonlendirme.

    - skipped veya ok → cozume gec
    - mismatch AND retry kaldi → gorseli yeniden uret
    - mismatch AND retry bitti → uyariyla cozume gec (infinite retry yasagina uyumlu)
    """
    status = state.get("currency_verify_status")
    if status in ("ok", "skipped"):
        return "solve_visual_question"
    # mismatch
    if state.get("currency_verify_attempts", 0) >= MAX_CURRENCY_VERIFY_ATTEMPTS:
        return "solve_visual_question"
    return "generate_images"


def route_after_visual_solving(state: VisualQuestionPipelineState) -> str:
    """Gorsel cozum sonrasi: dogru → bitir, yanlis → gorseli yeniden uret."""
    if state.get("visual_solver_correct"):
        return "finalize"
    if state.get("visual_solve_attempts", 0) >= MAX_VISUAL_SOLVE_ATTEMPTS:
        return "finalize"
    return "generate_images"


# ── Graf olusturma ───────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    """LangGraph StateGraph'ini olusturur ve derler."""
    graph = StateGraph(VisualQuestionPipelineState)

    # Node'lar (9 toplam — 8 temel + opsiyonel TL sadakat)
    graph.add_node("load_yaml", node_load_yaml)
    graph.add_node("generate_question", node_generate_question)
    graph.add_node("validate_question", node_validate_question)
    graph.add_node("solve_question", node_solve_question)
    graph.add_node("generate_images", node_generate_images)
    graph.add_node("validate_visual", node_validate_visual)
    graph.add_node("verify_currency", node_verify_currency)
    graph.add_node("solve_visual_question", node_solve_visual_question)
    graph.add_node("finalize", node_finalize)

    # Kenarlar
    graph.set_entry_point("load_yaml")
    graph.add_edge("load_yaml", "generate_question")
    graph.add_edge("generate_question", "validate_question")

    # Dogrulama sonrasi: tekrar uret veya cozume gec
    graph.add_conditional_edges(
        "validate_question",
        route_after_validation,
        {
            "solve_question": "solve_question",
            "generate_question": "generate_question",
        },
    )

    # Cozum sonrasi: gorsele gec, soruyu yeniden uret veya gorselsizse finalize
    graph.add_conditional_edges(
        "solve_question",
        route_after_solving,
        {
            "generate_images": "generate_images",
            "generate_question": "generate_question",
            "finalize": "finalize",
        },
    )

    graph.add_edge("generate_images", "validate_visual")

    # Gorsel dogrulama sonrasi: TL sadakat kontrolu (varsa) veya gorseli yeniden uret
    graph.add_conditional_edges(
        "validate_visual",
        route_after_visual_validation,
        {
            "verify_currency": "verify_currency",
            "generate_images": "generate_images",
        },
    )

    # TL sadakat kontrolu sonrasi: cozume gec veya gorseli yeniden uret
    graph.add_conditional_edges(
        "verify_currency",
        route_after_currency_verify,
        {
            "solve_visual_question": "solve_visual_question",
            "generate_images": "generate_images",
        },
    )

    # Gorsel cozum sonrasi: bitir veya gorseli yeniden uret
    graph.add_conditional_edges(
        "solve_visual_question",
        route_after_visual_solving,
        {
            "finalize": "finalize",
            "generate_images": "generate_images",
            "generate_question": "generate_question",
        },
    )

    graph.add_edge("finalize", END)

    return graph.compile()


app = build_graph()


# ── Calistirma yardimcisi ────────────────────────────────────────────────

def run(
    yaml_path: str | Path,
    difficulty: str = "orta",
    output_dir: str | Path = "output/visual_questions",
    extra_feedback: str | None = None,
    variant_name: str | None = None,
) -> VisualQuestionPipelineState:
    """Pipeline'i calistirir ve son state'i dondurur.

    Args:
        yaml_path: ortak/ klasorundeki YAML sablon yolu
        difficulty: Zorluk seviyesi (kolay/orta/zor)
        output_dir: Cikti dizini
        extra_feedback: Soru uretimine ek yonerge (ornegin benzerlik uyarisi)
        variant_name: Kullanilacak varyant adi (None ise LLM rastgele secer)

    Returns:
        VisualQuestionPipelineState: Pipeline'in son durumu
    """
    initial_state: VisualQuestionPipelineState = {
        "yaml_path": str(yaml_path),
        "difficulty": difficulty,
        "output_dir": str(output_dir),
        "extra_feedback": extra_feedback,
        "variant_name": variant_name,
        "question_attempts": 0,
        "validation_failures": 0,
        "solver_failures": 0,
        "image_attempts": 0,
        "visual_solve_attempts": 0,
        "currency_verify_attempts": 0,
        "has_visual_options": False,
        "requires_visual": True,
        "log": [],
    }

    final_state = app.invoke(initial_state)

    for entry in final_state.get("log", []):
        print(entry)

    return final_state


def show_graph() -> None:
    """Grafin Mermaid diyagramini tarayicida acar."""
    import subprocess
    import tempfile

    mermaid_syntax = app.get_graph().draw_mermaid()
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<script src="https://cdn.jsdelivr.net/npm/mermaid/dist/mermaid.min.js"></script>
<style>body{{display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;background:#fafafa}}</style>
</head><body>
<pre class="mermaid">{mermaid_syntax}</pre>
<script>mermaid.initialize({{startOnLoad:true,theme:'default'}});</script>
</body></html>"""

    tmp = tempfile.NamedTemporaryFile(
        suffix=".html", prefix="visual_graph_", delete=False, mode="w", encoding="utf-8",
    )
    tmp.write(html)
    tmp.close()
    subprocess.Popen(["open", tmp.name])


if __name__ == "__main__":
    show_graph()
