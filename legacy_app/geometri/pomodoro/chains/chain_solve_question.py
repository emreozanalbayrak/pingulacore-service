"""
Chain 3: Bagimsiz Soru Cozumu (LLM-3)
Model: gemini-3.1-pro-preview, temp=0.1

Uretilen soruyu bagimsiz bir LLM cozer.
KRITIK: Dogru cevap LLM'e KESINLIKLE verilmez.
LLM sadece senaryo + gorsel aciklama + soru + siklari gorur.
Node fonksiyonu cevaplari karsilastirir.
"""
from __future__ import annotations

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate

from legacy_app.geometri.pomodoro.models import GeneratedVisualQuestion, QuestionSolution, QuestionSolutionLLM
from legacy_app.geometri.pomodoro.pipeline_log import pipeline_log
from legacy_app.geometri.pomodoro.yaml_loader import ParsedTemplate, extract_for_solver_chain
from legacy_app.shared.utils.llm import ModelRole, get_model


_parser = PydanticOutputParser(pydantic_object=QuestionSolutionLLM)
_model = get_model(ModelRole.QUESTION_SOLVER)


PROMPT_TEMPLATE = """Sen {sinif_seviyesi}. sınıf matematik sorusu çözen bir uzman öğretmensin.

Aşağıdaki soruyu dikkatlice oku ve adım adım çöz.

{solver_context}

## SENARYO

{scenario_text}

## GÖRSEL AÇIKLAMA

Sahne: {scene_description}
Görsel düzen: {visual_layout}
Görsel öğeler: {visual_elements}

## SORU

{question_stem}

{options_text}

## GÖREV

1. Senaryo ve görsel açıklamayı dikkatlice oku.
2. Soruyu adım adım çöz.
3. Her şıkkı değerlendir.
4. Doğru olduğunu düşündüğün cevabı seç.
5. Güven seviyeni belirle (yuksek/orta/dusuk).

NOT: Sadece verilen bilgilerle çöz. Tahmin yapma.

{format_instructions}
"""


def _build_options_text_for_item(q) -> str:
    """Tek bir QuestionItem'in sikklarini formatlar. Dogru cevap isareti OLMAZ."""
    lines = []
    for label, content in sorted(q.options.items()):
        lines.append(f"{label}) {content}")
    return "\n".join(lines)


def _solve_single_question(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    q,
    idx: int,
    total: int,
) -> QuestionSolution:
    """Tek bir QuestionItem icin bagimsiz cozum yapar."""
    prompt = PromptTemplate(
        template=PROMPT_TEMPLATE,
        input_variables=[],
        partial_variables={
            "sinif_seviyesi": str(template.sinif_seviyesi),
            "solver_context": extract_for_solver_chain(template),
            "scenario_text": question.scenario_text,
            "scene_description": question.scene_description,
            "visual_layout": str(question.visual_layout),
            "visual_elements": str(question.visual_elements),
            "question_stem": q.question_stem,
            "options_text": _build_options_text_for_item(q),
            "format_instructions": _parser.get_format_instructions(),
        },
    )
    chain = prompt | _model | _parser
    pipeline_log("LLM-3", f"Soru {idx}/{total} çözülüyor…")
    llm_output = chain.invoke({})
    matches = llm_output.chosen_answer.strip().upper() == q.correct_answer.strip().upper()
    return QuestionSolution(**llm_output.model_dump(), matches_expected=matches)


def solve_question(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
) -> list[QuestionSolution]:
    """Uretilen tum sorulari bagimsiz olarak cozer.

    KRITIK: Dogru cevap, self_solution ve solution_explanation
    LLM'e KESINLIKLE verilmez.

    question_count == 1 ise tek elemanli list doner.
    question_count > 1 ise her soru icin ayri cozum doner.

    Args:
        template: 7 baslikli ParsedTemplate
        question: Mega chain ciktisi (GeneratedVisualQuestion)

    Returns:
        list[QuestionSolution]: Her soru icin bagimsiz cozum sonucu
    """
    if not question.questions:
        pipeline_log("LLM-3", "Bağımsız çözüm atlandı (soru yok).")
        return [QuestionSolution(
            chosen_answer="?",
            reasoning="Soru bulunamadi",
            confidence="dusuk",
            matches_expected=False,
        )]

    total = len(question.questions)
    pipeline_log("LLM-3", f"Bağımsız metin çözümü — {total} soru çözülecek…")

    results = []
    for i, q in enumerate(question.questions, 1):
        solution = _solve_single_question(template, question, q, i, total)
        results.append(solution)

    pipeline_log("LLM-3", f"Bağımsız metin çözümü tamamlandı ({total} soru).")
    return results
