"""
Chain 6: Gorsel Uzerinden Bagimsiz Cozum (LLM-6)
Model: gemini-2.5-flash, temp=0.1 (vision capable)

Uretilen gorsele bakarak soruyu bagimsiz olarak cozer.
KRITIK: Dogru cevap LLM'e KESINLIKLE verilmez.
LLM sadece gorselleri + senaryo + soru + siklari gorur.
"""
from __future__ import annotations

from pathlib import Path
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

1. Görseli/görselleri dikkatlice incele. **Nesne sayılarını YALNIZCA görselden say** — senaryo metnindeki sayılara dayanarak hesap yapma.
2. Senaryo ve soruyu oku; bağlamı anlamak için kullan ama sayısal değerleri GÖRSELDEN doğrula.
3. Görseldeki bilgileri kullanarak soruyu adım adım çöz.
4. Her şıkkı değerlendir.
5. Doğru cevabı seç.
6. Eğer görselde saydığın miktar senaryo metnindeki miktardan FARKLI ise bunu visual_issues'a açıkça yaz ve issues_affect_solution=true yap.
7. Görselde herhangi bir sorun fark edersen (yanlış etiket, eksik öğe, belirsiz alan, bağlama uymayan temsil) visual_issues'a yaz.
8. Küçük tipografi kusuru veya estetik sorun çözümü etkilemiyorsa issues_affect_solution=false bırak.

KRİTİK: Senaryo "8 incir" dese bile görselde 9 incir görüyorsan, görsel sayısını (9) kullan ve tutarsızlığı raporla.
"""


GEOMETRY_COMPARE_PROMPT = """Sen geometri görsellerinde referans-final tutarlılığı kontrol eden bir denetçisin.

İki görsel verilecek:
1. Referans/base görsel: Kodla üretilmiş matematiksel iskelet.
2. Final görsel: Image modelinin estetikleştirdiği çıktı.

Görevin soruyu çözmek DEĞİL; final görseldeki matematiksel içeriğin base görselle tutup tutmadığını kontrol etmektir.

KONTROL ET:
- Ana geometri base ile aynı alan/çevre/sayım/simetri/açı/uzunluk sonucunu veriyor mu?
- Grid/nokta varsa hücre düzeni, şeklin kapladığı hücreler ve etiketler finalde base ile uyumlu mu?
- Grid olmayan geometride polygonlar, segmentler, açı kolları, simetriye etkili şekil özellikleri, kenar uzunluğu etiketleri ve numaralar base ile uyumlu mu?
- Etiket/sayı varsa finalde base ile çelişiyor mu?

GÖZ ARDI ET:
- Ana geometri dışındaki frame, margin, kart zemini, tema rengi, kağıt dokusu, border, arka plan estetiği.
- Çizgi yumuşatma, renk değişimi, modern eğitim materyali stili.
- Ana geometri dışındaki tematik öğeler, geometriyi kapatmıyor ve yeni çözüm bilgisi eklemiyorsa.

Eğer finaldeki geometri/sayım/ölçü ilişkisi base ile genel olarak tutuyorsa issues_affect_solution=false yap.
Yalnızca final ana geometriyi, hücre/şekil sayısını, etiketleri, açı/simetri/uzunluk ilişkisini base'e göre açıkça değiştirdiyse issues_affect_solution=true yap.

chosen_answer alanına "BASE_ILE_TUTARLI" veya "BASE_ILE_TUTARSIZ" yaz.
reasoning alanında kısa karşılaştırma yap.
visual_issues alanına yalnızca base-final matematiksel tutarsızlıklarını yaz; çevre/frame/stil farklarını sorun sayma.
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
    if getattr(template, "visual_engine", "generative") == "solid_3d_deterministic":
        image_descriptions = [
            "- Ana görsel (A/B/C seçenek panellerini tek görsel içinde içerir)"
        ]
    else:
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
    # Gorsel sorunlari cozumu etkiliyorsa, cevap dogru olsa bile soru hatali sayilir
    # ve gorsel yeniden uretilir — ogrenciyi yaniltacak gorseller kabul edilmez.
    matches = answer_matches and not llm_output.issues_affect_solution
    return VisualQuestionSolution(**llm_output.model_dump(), matches_expected=matches)


def _compare_geometry_visual_with_base(
    q,
    main_image_path: str,
    idx: int,
    total: int,
) -> VisualQuestionSolution | None:
    """Geometri hybrid finalini base referansla karsilastirir.

    Bu mod soruyu cozmeye calismaz; final gorseldeki ic geometri/sayim base ile
    tutuyor mu diye bakar. Cevre/frame/tema farklari serbesttir.
    """
    base_path = Path(main_image_path).with_name("main_visual_base.png")
    if not base_path.exists():
        return None

    content = [{"type": "text", "text": GEOMETRY_COMPARE_PROMPT}]
    for path in (base_path, Path(main_image_path)):
        content.append({
            "type": "image_url",
            "image_url": {"url": encode_image_data_uri(str(path))},
        })

    structured_model = _model.with_structured_output(
        VisualQuestionSolutionLLM,
        method="json_schema",
    )

    message = HumanMessage(content=content)
    pipeline_log("LLM-6", f"Soru {idx}/{total} geometri base-final kontrolü — model çağrılıyor…")
    llm_output = structured_model.invoke([message])

    matches = not llm_output.issues_affect_solution
    chosen = q.correct_answer if matches else (llm_output.chosen_answer or "?")
    return VisualQuestionSolution(
        **llm_output.model_dump(exclude={"chosen_answer"}),
        chosen_answer=chosen,
        matches_expected=matches,
    )


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
        solution = None
        if getattr(template, "visual_engine", "generative") == "geometric_deterministic":
            solution = _compare_geometry_visual_with_base(q, main_image_path, i, total)
        if solution is None:
            solution = _solve_single_visual_question(
                template, question, q, main_image_path, option_image_paths, i, total,
            )
        results.append(solution)

    pipeline_log("LLM-6", f"Görsel üzerinden çözüm tamamlandı ({total} soru).")
    return results
