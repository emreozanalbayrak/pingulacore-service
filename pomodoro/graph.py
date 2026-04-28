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
import os
import re
import subprocess
import sys
import time
from contextlib import redirect_stderr, redirect_stdout
from operator import add
from pathlib import Path
from typing import Annotated, Iterable, Optional, TypedDict

from langgraph.graph import END, StateGraph

from pomodoro.chains.chain_generate_visual_question import generate_visual_question
from pomodoro.chains.chain_validate_batch import validate_batch
from pomodoro.chains.chain_solve_question import solve_question
from pomodoro.chains.chain_generate_image import generate_images
from pomodoro.chains.chain_generate_geometry_image import generate_geometry_image
from pomodoro.chains.chain_generate_solid3d_image import generate_solid3d_image
from pomodoro.chains.chain_validate_visual import validate_visual
from pomodoro.chains.chain_solve_visual_question import solve_visual_question
from pomodoro.models import (
    BatchValidation,
    GeneratedImages,
    GeneratedVisualQuestion,
    QuestionSolution,
    VisualQuestionSolution,
    VisualValidation,
)
from pomodoro.pipeline_log import pipeline_log
from pomodoro.variant_rotation import get_variant_names, select_next_variant
from pomodoro.number_pool import get_excluded_objects, register_objects, claim_object_suggestion, get_excluded_number_sets, register_numbers, clear_yaml_history
from pomodoro.yaml_loader import ParsedTemplate, load_and_parse_template
from src.build_question_html import build_question_html
from src.render_question_html import render_question_html


MAX_QUESTION_ATTEMPTS = 3
MAX_VALIDATION_ATTEMPTS = 3
MAX_SOLVER_ATTEMPTS = 3
MAX_IMAGE_ATTEMPTS = 3
MAX_VISUAL_SOLVE_ATTEMPTS = 5
KEEP_VERBOSE_OUTPUTS = os.getenv("PINGULA_KEEP_VERBOSE_OUTPUTS", "").lower() in {
    "1", "true", "yes", "on"
}

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
    excluded_number_sets: Optional[list[list[int]]]
    pre_generated_question: Optional[dict]
    excluded_objects: Optional[list[str]]
    suggested_object: Optional[str]

    # --- parse edilmis sablon ---
    template: Optional[dict]
    has_visual_options: bool
    requires_visual: bool
    force_no_visual_options: bool

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

    # Sayi gecmisinden excluded setler yukle
    excluded_number_sets = state.get("excluded_number_sets")
    if excluded_number_sets is None:
        try:
            excluded_number_sets = get_excluded_number_sets(state["yaml_path"])
            if excluded_number_sets:
                pipeline_log("pipeline", f"Kaçınılacak sayı setleri: {excluded_number_sets}")
                log_entries.append(f"[load_yaml] Excluded number sets: {excluded_number_sets}")
        except Exception as exc:
            excluded_number_sets = []
            log_entries.append(f"[load_yaml] Sayi gecmisi okunamadi (atlanıyor): {exc}")

    # Nesne gecmisinden excluded listesi + yeni nesne claim
    excluded_objects = state.get("excluded_objects")
    suggested_object = state.get("suggested_object")
    if excluded_objects is None:
        try:
            excluded_objects = get_excluded_objects(state["yaml_path"])
            if excluded_objects:
                log_entries.append(f"[load_yaml] Excluded objects: {excluded_objects}")
        except Exception as exc:
            excluded_objects = []
            log_entries.append(f"[load_yaml] Nesne gecmisi okunamadi (atlanıyor): {exc}")
    if suggested_object is None:
        try:
            suggested_object = claim_object_suggestion(state["yaml_path"])
            pipeline_log("pipeline", f"Nesne önerisi: {suggested_object}")
            log_entries.append(f"[load_yaml] Suggested object: {suggested_object}")
        except Exception as exc:
            log_entries.append(f"[load_yaml] Nesne claim hatasi (atlanıyor): {exc}")

    if state.get("force_no_visual_options"):
        template.has_visual_options = False
        log_entries.append("[load_yaml] force_no_visual_options aktif: has_visual_options=False zorlandi")

    log_entries.append(f"[load_yaml] YAML yuklendi: {state['yaml_path']} "
                       f"(has_visual_options={template.has_visual_options}, "
                       f"requires_visual={template.requires_visual})")

    return {
        "template": template.model_dump(),
        "variant_name": variant_name,
        "excluded_number_sets": excluded_number_sets,
        "excluded_objects": excluded_objects,
        "suggested_object": suggested_object,
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

    # Onceden uretilmis soru varsa LLM cagrisi atla
    if state.get("pre_generated_question"):
        question_data = dict(state["pre_generated_question"])
        pipeline_log("pipeline", "Soru üretimi atlandı — önceden üretilmiş soru kullanılıyor.")
    else:
        excluded_number_sets = state.get("excluded_number_sets") or []
        excluded_objects = state.get("excluded_objects") or []
        suggested_object = state.get("suggested_object")
        question = generate_visual_question(
            template, difficulty, feedback, variant_name,
            excluded_number_sets=excluded_number_sets,
            excluded_objects=excluded_objects,
            suggested_object=suggested_object,
        )
        question_data = question.model_dump()
    if variant_name:
        question_data["selected_variant"] = variant_name
    requires_visual = state.get("requires_visual", False) or _question_explicitly_requires_visual(question_data)
    question_path = _write_question_snapshot(
        question_data,
        state.get("output_dir", "output/visual_questions"),
        stage="question_generated",
    )

    actual = len(question_data.get("questions") or [])
    return {
        "generated_question": question_data,
        "question_attempts": attempts,
        "requires_visual": requires_visual,
        "log": [
            f"[generate_question] Soru hazır (deneme {attempts}/{MAX_QUESTION_ATTEMPTS}) — {actual} soru",
            (
                "[generate_question] Soru metni gorsele acik atif yaptigi icin ana gorsel zorunlu kabul edildi"
                if requires_visual and not template.requires_visual
                else f"[generate_question] Ana gorsel gereksinimi: {requires_visual}"
            ),
            f"[generate_question] Taslak JSON kaydedildi: {question_path}",
        ],
    }



def _check_answer_numbers_in_context(question_data: dict) -> str | None:
    """Correct answer'daki ana sayinin senaryo/gorsel baglaminda gecip gecmedigini kontrol eder.

    Dogrudan sayisal bir cevap varsa (ornegin '24', '3 x 8 = 24') bu sayi senaryo
    metninde ya da scene/visual elementlerinde yer almiyorsa revizyon gereklidir.
    Yazi iceren sik cevaplari (ornegin 'evet', 'hayir', islem cumlesi) kontrol edilmez.
    """
    import re as _re

    for q in question_data.get("questions") or []:
        correct_key = q.get("correct_answer", "")
        correct_val = str((q.get("options") or {}).get(correct_key, ""))

        # Sadece icinde rakam olan siklari kontrol et
        nums_in_answer = _re.findall(r"\b(\d{2,})\b", correct_val)
        if not nums_in_answer:
            continue

        # Baglam: senaryo + scene_elements + visual_elements + hidden_computation
        context_blob = " ".join([
            str(question_data.get("scenario_text") or ""),
            str(question_data.get("scene_elements") or ""),
            str(question_data.get("visual_elements") or ""),
            str(question_data.get("hidden_computation") or ""),
            " ".join(str(qi.get("question_stem") or "") for qi in question_data.get("questions") or []),
        ])

        for num in nums_in_answer:
            if num not in context_blob:
                return (
                    f"Doğru cevaptaki sayı '{num}' senaryo metninde, görsel tanımında "
                    f"veya gizli hesaplamalarda geçmiyor. Senaryo, görsel ve cevap "
                    f"sayısal olarak tutarsız."
                )
    return None


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

    # numeric_consistency_check fail ise override et
    if not validation.numeric_consistency_check and validation.overall_status == "gecerli":
        validation.overall_status = "revizyon_gerekli"
        if not validation.feedback:
            validation.feedback = "Senaryo sayıları ile görsel/doğru cevap arasında sayısal tutarsızlık."

    # Kod seviyesi sayı tutarlılık kontrolü: correct_answer değerindeki sayılar
    # senaryo metninde veya scene/visual elementlerinde geçmeli
    if validation.overall_status == "gecerli":
        code_feedback = _check_answer_numbers_in_context(state["generated_question"])
        if code_feedback:
            validation.overall_status = "revizyon_gerekli"
            validation.feedback = code_feedback
            pipeline_log("validate", f"⚠️ Kod-seviyesi sayı kontrolü başarısız: {code_feedback[:100]}")

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
    # Retry'da exact sayıları feedback'e ekle
    if attempts > 1:
        import re as _re
        hc = str(question.hidden_computation or {})
        hc_nums = list(dict.fromkeys(
            m for m in _re.findall(r"\b\d+\b", hc) if 1 < int(m) < 10000
        ))
        if hc_nums:
            feedback_parts.append(
                f"KRİTİK: Görseldeki nesne sayıları MUTLAKA şu değerlerle birebir eşleşmeli: "
                f"{', '.join(hc_nums[:8])}. "
                f"Önceki görselde sayım yanlıştı — her grubu tek tek say ve bu sayıları koru."
            )
    feedback = "\n\n".join(feedback_parts) if feedback_parts else None

    engine = getattr(template, "visual_engine", "generative")
    if engine == "geometric_deterministic":
        pipeline_log(
            "pipeline",
            f"Gorsel motoru: geometric_deterministic (hybrid referans + image model) — image_type={template.image_type}"
        )
        images = generate_geometry_image(template, question, output_dir, feedback)
    elif engine == "solid_3d_deterministic":
        pipeline_log(
            "pipeline",
            f"Gorsel motoru: solid_3d_deterministic (deterministik 3D main visual, sik gorselleri kapali) — image_type={template.image_type}"
        )
        images = generate_solid3d_image(template, question, output_dir, feedback)
    else:
        images = generate_images(template, question, output_dir, feedback)
    return {
        "generated_images": images.model_dump(),
        "image_attempts": attempts,
        "log": [
            f"[generate_images] Gorsel uretildi (deneme {attempts}/{MAX_IMAGE_ATTEMPTS}, engine={engine}): "
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

    # Ek yildizlama: cevap sayisi baglamda yoksa
    if not is_problematic:
        numeric_issue = _check_answer_numbers_in_context(state["generated_question"])
        if numeric_issue:
            is_problematic = True
            pipeline_log("finalize", f"⚠️ Ek yıldızlama: {numeric_issue}")

    output_dir = _prepare_final_output_dir(requested_output_dir, is_problematic=is_problematic)

    # Kullanilan sayilari gecmise kaydet (set bazli)
    # Oncelik: used_numbers (LLM doldurmussa) → hidden_computation → senaryo/cevap regex
    used_numbers = state["generated_question"].get("used_numbers") or []
    if not used_numbers:
        import re as _re
        from collections import Counter
        # 1. hidden_computation'dan cek (sayilarin birincil kaynagi)
        hc = state["generated_question"].get("hidden_computation") or {}
        hc_text = str(hc)
        hc_nums = [int(m) for m in _re.findall(r"\b\d+\b", hc_text) if 1 < int(m) < 10000]
        if hc_nums:
            used_numbers = [n for n, _ in Counter(hc_nums).most_common(8)]
        else:
            # 2. Fallback: senaryo + soru koku + dogru cevap degeri
            text_parts = [state["generated_question"].get("scenario_text", "")]
            for q in state["generated_question"].get("questions", []):
                text_parts.append(q.get("question_stem", ""))
                correct_key = q.get("correct_answer", "")
                correct_val = (q.get("options") or {}).get(correct_key, "")
                if correct_val:
                    text_parts.append(str(correct_val))
            combined = " ".join(str(p) for p in text_parts)
            nums = [int(m) for m in _re.findall(r"\b\d+\b", combined) if 1 < int(m) < 10000]
            used_numbers = [n for n, _ in Counter(nums).most_common(6)]
    if used_numbers:
        try:
            register_numbers(state["yaml_path"], used_numbers)
            pipeline_log("pipeline", f"Sayı geçmişine eklendi: {sorted(set(used_numbers))}")
        except Exception as exc:
            pipeline_log("pipeline", f"Sayı geçmişi kaydedilemedi (atlanıyor): {exc}")

    # Kullanilan nesneleri gecmise kaydet
    used_objects = state["generated_question"].get("used_objects") or []
    if not used_objects and state.get("suggested_object"):
        used_objects = [state["suggested_object"]]
    if used_objects:
        try:
            _tmpl = ParsedTemplate(**state["template"])
            register_objects(state["yaml_path"], used_objects)
            pipeline_log("pipeline", f"Nesne geçmişine eklendi: {used_objects}")
        except Exception as exc:
            pipeline_log("pipeline", f"Nesne geçmişi kaydedilemedi (atlanıyor): {exc}")

    # Soru verisini finalize et
    question_path = _write_question_snapshot(
        state["generated_question"],
        output_dir,
        stage="finalized",
    )

    # HTML ciktisini kaydet
    html_content = state["generated_question"].get("html_content", "")
    images = GeneratedImages(**state["generated_images"]) if state.get("generated_images") else None

    # Yildizlama sırasında klasör yeniden adlandırıldıysa image path'i güncelle
    if images and images.main_image_path:
        old_img = Path(images.main_image_path)
        if not old_img.exists():
            new_img = output_dir / old_img.name
            if new_img.exists():
                imgs_dict = images.model_dump()
                imgs_dict["main_image_path"] = str(new_img)
                if imgs_dict.get("option_images"):
                    imgs_dict["option_images"] = {
                        k: str(output_dir / Path(v).name)
                        for k, v in imgs_dict["option_images"].items()
                    }
                images = GeneratedImages(**imgs_dict)
    questions = state["generated_question"].get("questions") or []

    if questions:
        html_content = build_question_html(
            question_data=state["generated_question"],
            output_dir=output_dir,
            main_image_path=images.main_image_path if images else None,
            option_images=images.option_images if images else None,
            inline_images=True,
        )
    if html_content:
        html_path = output_dir / "question.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html_content)

        is_geometry = False
        if state.get("template"):
            try:
                is_geometry = (
                    ParsedTemplate(**state["template"]).visual_engine
                    == "geometric_deterministic"
                )
            except Exception:
                is_geometry = False

        preview_html_path = html_path
        if questions and (not is_geometry or KEEP_VERBOSE_OUTPUTS):
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
    """Gorsel dogrulama sonrasi: uygun → cozume, revizyon → gorseli yeniden uret."""
    if state.get("visual_validation_status") == "uygun":
        return "solve_visual_question"
    if state.get("image_attempts", 0) >= MAX_IMAGE_ATTEMPTS:
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

    # Node'lar (8 toplam)
    graph.add_node("load_yaml", node_load_yaml)
    graph.add_node("generate_question", node_generate_question)
    graph.add_node("validate_question", node_validate_question)
    graph.add_node("solve_question", node_solve_question)
    graph.add_node("generate_images", node_generate_images)
    graph.add_node("validate_visual", node_validate_visual)
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

    # Gorsel dogrulama sonrasi: cozume gec veya gorseli yeniden uret
    graph.add_conditional_edges(
        "validate_visual",
        route_after_visual_validation,
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
    force_no_visual_options: bool = False,
    pre_generated_question: dict | None = None,
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
        "has_visual_options": False,
        "requires_visual": True,
        "force_no_visual_options": force_no_visual_options,
        "pre_generated_question": pre_generated_question,
        "log": [],
    }

    final_state = app.invoke(initial_state)

    for entry in final_state.get("log", []):
        print(entry)

    return final_state


def generate_question_standalone(
    yaml_path: str | Path,
    difficulty: str = "orta",
    output_dir: str | Path = "output/visual_questions",
    clear_history: bool = False,
) -> dict:
    """Sadece soru uretimi (LLM-1) + sayi/nesne logu. Pipeline'in geri kalani calistirilmaz.

    Paralel uretimde seri Faz-1 icin kullanilir: her run bir oncekinin
    sayi logunu gorebilsin diye sirayla cagirilir; ardindan `run()` ile
    `pre_generated_question` enjekte edilerek paralel Faz-2 baslatilir.

    Returns:
        question_data dict — `run(pre_generated_question=...)` icin hazir.
    """
    from pomodoro.yaml_loader import load_and_parse_template

    yaml_path = str(yaml_path)
    if clear_history:
        clear_yaml_history(yaml_path)
    template = load_and_parse_template(yaml_path)

    # Varyant sec
    available = get_variant_names(template)
    variant_name = select_next_variant(yaml_path, available) if available else None
    if variant_name:
        pipeline_log("standalone", f"Varyant: {variant_name}")

    # Excluded number sets
    try:
        excluded_number_sets = get_excluded_number_sets(yaml_path)
    except Exception:
        excluded_number_sets = []

    # Object claim
    try:
        suggested_object = claim_object_suggestion(yaml_path)
        excluded_objects = get_excluded_objects(yaml_path)
    except Exception:
        suggested_object = None
        excluded_objects = []

    # Soru uret
    question = generate_visual_question(
        template, difficulty, None, variant_name,
        excluded_number_sets=excluded_number_sets,
        excluded_objects=excluded_objects,
        suggested_object=suggested_object,
    )
    question_data = question.model_dump()
    question_data["selected_variant"] = variant_name

    # Sayilari logla — oncelik: used_numbers → hidden_computation → regex fallback
    used_numbers = question_data.get("used_numbers") or []
    if not used_numbers:
        import re as _re
        from collections import Counter
        hc = question_data.get("hidden_computation") or {}
        hc_nums = [int(m) for m in _re.findall(r"\b\d+\b", str(hc)) if 1 < int(m) < 10000]
        if hc_nums:
            used_numbers = [n for n, _ in Counter(hc_nums).most_common(8)]
    if not used_numbers:
        import re as _re
        from collections import Counter
        text = " ".join([
            question_data.get("scenario_text", ""),
            *[q.get("question_stem", "") for q in question_data.get("questions", [])],
        ])
        nums = [int(m) for m in _re.findall(r"\b\d+\b", text) if 1 < int(m) < 10000]
        used_numbers = [n for n, _ in Counter(nums).most_common(8)]
    if used_numbers:
        register_numbers(yaml_path, used_numbers)
        pipeline_log("standalone", f"Sayı logu: {sorted(set(used_numbers))}")

    # Nesneleri logla
    used_objects = question_data.get("used_objects") or []
    if not used_objects and suggested_object:
        used_objects = [suggested_object]
    if used_objects:
        register_objects(yaml_path, used_objects)

    # Cikti dizinine snapshot yaz
    from pathlib import Path as _Path
    out = _Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    import json as _json
    snap = dict(question_data)
    snap["pipeline_stage"] = "question_generated"
    (out / "question.json").write_text(_json.dumps(snap, ensure_ascii=False, indent=2))

    return question_data


def _launch_stage2_process(
    yaml_path: Path,
    output_dir: Path,
    difficulty: str,
) -> tuple[subprocess.Popen, object, Path, Path]:
    """Hazir question.json ile Faz-2'yi ayri process olarak baslatir.

    Thread icinde stdout/stderr redirect etmek global oldugu icin loglari
    karistirir. Subprocess + dosya handle'i ise her is icin izole log tutar.
    """
    log_path = output_dir / "run.log"
    code = f"""
import json
from pathlib import Path
from pomodoro.graph import run

yaml_path = Path({str(yaml_path)!r})
output_dir = Path({str(output_dir)!r})
question_data = json.loads((output_dir / "question.json").read_text(encoding="utf-8"))
state = run(
    yaml_path=yaml_path,
    difficulty={difficulty!r},
    output_dir=output_dir,
    variant_name=question_data.get("selected_variant"),
    pre_generated_question=question_data,
)
print(state.get("final_output_path") or output_dir)
"""
    log_file = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=log_file,
        stderr=subprocess.STDOUT,
    )
    return process, log_file, yaml_path, output_dir


def run_batch_two_phase_streaming(
    yaml_paths: Iterable[str | Path],
    output_root: str | Path,
    difficulty: str = "orta",
    max_parallel_stage2: int = 3,
    skip_completed: bool = True,
    reuse_existing_question: bool = True,
    clear_history: bool = False,
    output_suffix: str = "",
) -> list[dict]:
    """Birden fazla YAML'i seri soru + akan paralel final fazi ile uretir.

    Faz-1 (`question.json`) bilerek seri calisir; boylece sayi/nesne gecmisi
    siradaki soru secimine yansir. Her YAML'in `question.json` dosyasi hazir
    olur olmaz Faz-2 ayri subprocess olarak baslatilir; tum soru dosyalarinin
    bitmesi beklenmez.
    """
    output_root = Path(output_root)
    output_root.mkdir(parents=True, exist_ok=True)
    yaml_list = [Path(path) for path in yaml_paths]
    active: list[tuple[subprocess.Popen, object, Path, Path]] = []
    results: list[dict] = []

    def finish_process(item: tuple[subprocess.Popen, object, Path, Path]) -> dict:
        process, log_file, yaml_path, output_dir = item
        return_code = process.wait()
        log_file.close()
        status = "ok" if return_code == 0 and (output_dir / "question.html").exists() else "phase2_error"
        result: dict = {
            "yaml": str(yaml_path),
            "output_dir": str(output_dir),
            "status": status,
            "return_code": return_code,
        }
        if status != "ok":
            result["error"] = f"phase2 return_code={return_code}"
        return result

    def reap_one(block: bool) -> Optional[dict]:
        while active:
            for index, item in enumerate(active):
                process = item[0]
                if process.poll() is not None:
                    active.pop(index)
                    return finish_process(item)
            if not block:
                return None
            time.sleep(1)
        return None

    for index, yaml_path in enumerate(yaml_list, 1):
        output_dir = output_root / f"{yaml_path.stem}{output_suffix}"
        output_dir.mkdir(parents=True, exist_ok=True)

        if skip_completed and (output_dir / "question.html").exists():
            results.append({
                "yaml": str(yaml_path),
                "output_dir": str(output_dir),
                "status": "already_ok",
            })
            continue

        question_path = output_dir / "question.json"
        if not (reuse_existing_question and question_path.exists()):
            phase1_log = output_dir / "run_phase1_question.log"
            try:
                with phase1_log.open("w", encoding="utf-8") as log_file:
                    with redirect_stdout(log_file), redirect_stderr(log_file):
                        generate_question_standalone(
                            yaml_path=yaml_path,
                            difficulty=difficulty,
                            output_dir=output_dir,
                            clear_history=clear_history,
                        )
            except Exception as exc:
                results.append({
                    "yaml": str(yaml_path),
                    "output_dir": str(output_dir),
                    "status": "phase1_error",
                    "error": f"{type(exc).__name__}: {exc}",
                })
                continue

        active.append(_launch_stage2_process(yaml_path, output_dir, difficulty))
        print(f"[batch-two-phase] stage2 basladi {index}/{len(yaml_list)}: {yaml_path.name}")

        while len(active) >= max(1, max_parallel_stage2):
            finished = reap_one(block=True)
            if finished:
                results.append(finished)
                print(f"[batch-two-phase] {finished['status']}: {Path(finished['yaml']).name}")

        finished = reap_one(block=False)
        while finished:
            results.append(finished)
            print(f"[batch-two-phase] {finished['status']}: {Path(finished['yaml']).name}")
            finished = reap_one(block=False)

    while active:
        finished = reap_one(block=True)
        if finished:
            results.append(finished)
            print(f"[batch-two-phase] {finished['status']}: {Path(finished['yaml']).name}")

    summary_path = output_root / "batch_summary.json"
    summary_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return results
