"""
Chain 6: Gorsel Uzerinden Bagimsiz Cozum (LLM-6)
Model: gemini-2.5-flash, temp=0.1 (vision capable)

Uretilen gorsele bakarak soruyu bagimsiz olarak cozer.
KRITIK: Dogru cevap LLM'e KESINLIKLE verilmez.
LLM sadece gorselleri + senaryo + soru + siklari gorur.
"""
from __future__ import annotations

from typing import Optional

from langchain.messages import HumanMessage

from pomodoro.models import (
    GeneratedVisualQuestion,
    VisualQuestionSolution,
    VisualQuestionSolutionLLM,
)
from pomodoro.pipeline_log import pipeline_log
from pomodoro.yaml_loader import ParsedTemplate, extract_for_visual_solver_chain
from utils.image_data import encode_image_data_uri
from utils.llm import ModelRole, get_model


_model = get_model(ModelRole.VISUAL_QUESTION_SOLVER)


SOLVE_PROMPT = """Sen {sinif_seviyesi}. sınıf matematik sorusu çözen bir uzman öğretmensin.

Aşağıdaki görsele/görsellere bakarak soruyu adım adım çöz.

{solver_context}

## SENARYO

{scenario_text}

## SORU

{question_stem}

{options_text}

## GÖRSELLER

{image_list_description}

## GÖREV

1. Görseli/görselleri dikkatlice incele.
2. Senaryo ve soruyu oku.
3. Görseldeki bilgileri kullanarak soruyu adım adım çöz.
4. Her şıkkı değerlendir.
5. Doğru cevabı seç.
6. Görselde herhangi bir sorun fark edersen (yanlış etiket, eksik öğe, belirsiz alan, bağlama uymayan temsil, metindeki sayılarla çelişen miktarlar vb.) visual_issues'a yaz.
7. Görseldeki sorunlar çözümü gerçekten etkiliyorsa issues_affect_solution=true yap. Küçük tipografi kusuru, hafif hizalama sorunu veya çözümü etkilemeyen estetik kusur varsa false yap.
8. Görselde görülen nesne sayıları, grup büyüklükleri veya eksik miktarlar seçeneklerde beklenen mantıkla çelişiyorsa bunu açıkça sorun olarak yaz. Görsel bariz biçimde başka bir cevabı destekliyorsa issues_affect_solution=true yap.

NOT: Sadece gördüğün bilgilerle çöz. Tahmin yapma.
Temsilî görsel kullanılabilir; ancak senaryodaki ana nesne ile genel bağlam korunmalı ve temsil öğrenciyi yanlış nesneye ya da yanlış sayıya götürmemelidir.
"""


def _build_options_text_for_item(q) -> str:
    """Tek bir QuestionItem'in sikklarini formatlar. Dogru cevap isareti OLMAZ."""
    lines = []
    for label, content in sorted(q.options.items()):
        lines.append(f"{label}) {content}")
    return "\n".join(lines)


def _solve_single_visual_question(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    q,
    main_image_path: str,
    option_image_paths: Optional[dict[str, str]],
    idx: int,
    total: int,
) -> VisualQuestionSolution:
    """Tek bir QuestionItem icin gorsel bazli bagimsiz cozum yapar."""
    # Gorsel listesi aciklamasi
    image_descriptions = ["- Ana görsel (yukarıdaki ilk görsel)"]
    if option_image_paths:
        for label in sorted(option_image_paths.keys()):
            image_descriptions.append(f"- Şık {label} görseli")

    # Prompt olustur
    prompt_text = SOLVE_PROMPT.format(
        sinif_seviyesi=template.sinif_seviyesi,
        solver_context=extract_for_visual_solver_chain(template),
        scenario_text=question.scenario_text,
        question_stem=q.question_stem,
        options_text=_build_options_text_for_item(q),
        image_list_description="\n".join(image_descriptions),
    )

    # Multimodal mesaj olustur
    content = [{"type": "text", "text": prompt_text}]

    # Ana gorsel
    main_uri = encode_image_data_uri(main_image_path)
    content.append({
        "type": "image_url",
        "image_url": {"url": main_uri},
    })

    # Sik gorselleri (varsa)
    if option_image_paths:
        for label in sorted(option_image_paths.keys()):
            opt_uri = encode_image_data_uri(option_image_paths[label])
            content.append({
                "type": "image_url",
                "image_url": {"url": opt_uri},
            })

    structured_model = _model.with_structured_output(
        VisualQuestionSolutionLLM,
        method="json_schema",
    )

    message = HumanMessage(content=content)
    pipeline_log("LLM-6", f"Soru {idx}/{total} görsel çözüm — model çağrılıyor…")
    llm_output = structured_model.invoke([message])

    answer_matches = llm_output.chosen_answer.strip().upper() == q.correct_answer.strip().upper()
    # Cevap dogru ise gorsel kabul edilir — kucuk estetik kusurlar retry dongusune sokmaz.
    # Cevap yanlis ve gorsel sorunu varsa gorsel yeniden uretilir.
    matches = answer_matches
    return VisualQuestionSolution(**llm_output.model_dump(), matches_expected=matches)


def solve_visual_question(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    main_image_path: str,
    option_image_paths: Optional[dict[str, str]] = None,
) -> list[VisualQuestionSolution]:
    """Gorsele bakarak tum sorulari bagimsiz olarak cozer.

    KRITIK: Dogru cevap, self_solution ve solution_explanation
    LLM'e KESINLIKLE verilmez.

    question_count == 1 ise tek elemanli list doner.
    question_count > 1 ise her soru icin ayri gorsel cozum doner.

    Args:
        template: 7 baslikli ParsedTemplate
        question: Mega chain ciktisi
        main_image_path: Ana gorsel dosya yolu
        option_image_paths: Sik gorselleri {"A": path, ...} (opsiyonel)

    Returns:
        list[VisualQuestionSolution]: Her soru icin gorsel bazli bagimsiz cozum
    """
    if not question.questions:
        pipeline_log("LLM-6", "Görsel çözüm atlandı (soru yok).")
        return [VisualQuestionSolution(
            chosen_answer="?",
            reasoning="Soru bulunamadi",
            visual_issues=[],
            matches_expected=False,
        )]

    total = len(question.questions)
    pipeline_log("LLM-6", f"Görsel üzerinden çözüm — {total} soru çözülecek…")

    results = []
    for i, q in enumerate(question.questions, 1):
        solution = _solve_single_visual_question(
            template, question, q, main_image_path, option_image_paths, i, total,
        )
        results.append(solution)

    pipeline_log("LLM-6", f"Görsel üzerinden çözüm tamamlandı ({total} soru).")
    return results
