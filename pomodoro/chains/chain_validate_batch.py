"""
Chain 2: Batch Dogrulama (LLM-2)
Model: gemini-3-flash-preview, temp=0.1

YAML basliklari: meta, context.generation.kurallar, format.options, dogru_cevap, distractors, tymm
Uretilen soruyu YAML'daki kurallara gore dogrular.

Yeni kontroller:
- self_solution tutarliligi (uretici LLM'in kendi cozumu dogru mu?)
- TYMM uyum kurallari (varsa)
"""
from __future__ import annotations

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate

from pomodoro.models import BatchValidation
from pomodoro.pipeline_log import pipeline_log
from pomodoro.yaml_loader import ParsedTemplate, extract_for_validation_chain
from utils.llm import ModelRole, get_model


_parser = PydanticOutputParser(pydantic_object=BatchValidation)
_model = get_model(ModelRole.BATCH_VALIDATOR)


PROMPT_TEMPLATE = """Sen {sinif_seviyesi}. sınıf için üretilen soruları doğrulayan uzman bir eğitim denetçisisin.
Soru tipi: {context_type}

Üretilen soruyu aşağıdaki kriterlere göre doğrula.

## ÜRETİLEN SORU

{generated_question}

## DOĞRULAMA KRİTERLERİ

{validation_constraints}

## ÖNEMLİ: SEÇENEK ETİKETLERİ

Şıkların sırası (A, B, C...) rastgele karıştırılmıştır. Doğrulama yaparken etiketlere (A, B, C) değil, **şıkların içeriğine (değerlerine)** bakarak değerlendir. `correct_answer` alanı hangi etiketi gösteriyorsa, o etiketin karşısındaki değerin matematiksel/mantıksal olarak doğru olup olmadığını kontrol et.

## GÖREV

Yukarıdaki üretilen soruyu, doğrulama kriterlerindeki her maddeyi tek tek kontrol ederek değerlendir.

Kontrol edilecek alanlar:
{kontrol_alanlari}

{format_instructions}
"""


def _build_check_areas(template: ParsedTemplate) -> str:
    """YAML icerigine gore dinamik kontrol alanlari listesi olusturur."""
    areas = []
    idx = 1
    generation = template.context.get("generation", {})

    # Kural uyumu
    kurallar = generation.get("kurallar", [])
    if kurallar:
        areas.append(
            f"{idx}. **Kural uyumu** (curriculum_compliance): Soru, üretim kurallarının tamamına uygun mu?"
        )
        idx += 1

    areas.append(
        f"{idx}. **Kritik miktar ve değişim tutarlılığı**: Artış, azalış, eksilme, ekleme, çıkarma, "
        f"transfer, eşitleme veya dönüşüm içeren miktarlar eksiksiz gösterilmiş mi? Bu ilişkiler "
        f"soru ve doğru cevapla bire bir uyuşuyor mu? Görselden yapılacak doğrudan sayım veya grup okuma, "
        f"başka bir seçeneği değil yalnızca doğru seçeneği destekliyor mu?"
    )
    idx += 1

    areas.append(
        f"{idx}. **Üst metin-görsel iş bölümü**: Senaryo metni çözüme faydalı en az bir sayısal ya da "
        f"ilişkisel ipucu veriyor mu? Buna rağmen tüm çözümü verip görseli gereksiz hale getirmiyor mu? "
        f"Metin ve görselin birlikte kullanılmasını zorunlu kılan dengeli bir yapı var mı?"
    )
    idx += 1

    areas.append(
        f"{idx}. **Görsel referansı tutarlılığı**: Soru metni, çözüm veya senaryo "
        f"'görselde', 'şekilde', 'tabloda', 'şemada', 'yandaki', 'yukarıdaki' gibi açık bir "
        f"görsel referansı içeriyorsa soru mutlaka ana görselle birlikte sunulabilecek yapıda mı? "
        f"Görsel olmadan askıda kalan bir ifade veya eksik bırakılmış bir veri var mı?"
    )
    idx += 1

    areas.append(
        f"{idx}. **Sayısal tutarlılık** (numeric_consistency_check): "
        f"Senaryo metnindeki sayısal değerler (nesne adetleri, grup büyüklükleri, miktarlar) "
        f"ile visual_elements / scene_elements'teki sayılar BİREBİR uyuşuyor mu? "
        f"Örneğin senaryo '5 kasa' diyorsa görselde de 5 kasa olmalı, 4 veya 6 olamaz. "
        f"Aynı şekilde doğru cevap, senaryo ve görseldeki sayılarla matematiksel olarak tutarlı mı? "
        f"Herhangi bir tutarsızlık varsa bu alan false olmalı."
    )
    idx += 1

    # Dogru cevap tutarliligi
    if template.dogru_cevap:
        areas.append(
            f"{idx}. **Doğru cevap tutarlılığı** (answer_consistency_check): "
            f"Doğru seçenek gerçekten doğru mu? Doğru cevap kurallarıyla uyumlu mu?"
        )
        idx += 1

    # Celdirici kalitesi
    if template.distractors:
        areas.append(
            f"{idx}. **Çeldirici kalitesi** (distractor_quality_check): "
            f"Yanlış seçenekler çeldirici stratejilerine uygun mu? Makul ama yanlış mı?"
        )
        idx += 1

    # Format kontrolu
    if template.format_spec:
        areas.append(
            f"{idx}. **Format uygunluğu** (format_check): Şık sayısı, yapı ve sunum doğru mu?"
        )
        idx += 1

    # Dil kontrolu
    areas.append(
        f"{idx}. **Dil uygunluğu** (language_check): Türkçe dil kurallarına uygun mu? "
        f"Yabancı dilde ifade var mı? Senaryo içinde probleme katkısız, yalnızca süs veya duygu "
        f"aktarımı yapan kapanış cümleleri var mı? Varsa language_check false olmalı."
    )
    idx += 1

    # Uretim yapisi kontrolu
    structure = generation.get("structure", [])
    if structure:
        areas.append(
            f"{idx}. **Üretim yapısı uyumu**: Soru, ÜRETİM YAPISI bölümündeki "
            f"tüm adımları karşılıyor mu? Her yapısal gereksinim sağlanmış mı?"
        )
        idx += 1

    # Beceri uyumu
    questions = template.context.get("questions", [])
    any_beceri = any(q.get("beceri") for q in questions)
    if any_beceri:
        areas.append(
            f"{idx}. **Beceri uyumu**: Soru, BECERİ HEDEFLERİ bölümündeki "
            f"bilişsel katman ve bileşenleri ölçüyor mu?"
        )
        idx += 1

    # Paragraf kisitlari
    paragraph = template.format_spec.get("paragraph", {})
    if not isinstance(paragraph, dict): paragraph = {}
    if paragraph.get("word_count_min") or paragraph.get("sentence_count_min"):
        areas.append(
            f"{idx}. **Paragraf kısıtları**: Senaryo metni kelime ve cümle sayısı "
            f"kısıtlarına uygun mu?"
        )
        idx += 1

    # self_solution tutarliligi
    areas.append(
        f"{idx}. **Üretici çözüm tutarlılığı** (self_solution_check): "
        f"Üretici LLM'in kendi çözümü (self_solution) doğru cevapla uyuşuyor mu? "
        f"Çözüm mantığı tutarlı mı?"
    )
    idx += 1

    # TYMM uyumu
    if template.tymm_uyum_kurallari:
        areas.append(
            f"{idx}. **TYMM uyumu** (tymm_compliance): "
            f"Soru, TYMM uyum kurallarındaki sınıf sınırlarına, yasaklara ve izinli içeriğe uygun mu?"
        )
        idx += 1

    # Coklu soru tutarliligi
    if template.question_count > 1:
        areas.append(
            f"{idx}. **Çoklu soru tutarlılığı**: "
            f"Tam olarak {template.question_count} soru üretilmiş mi? "
            f"Tüm sorular aynı senaryo ve görsele bağlı mı? "
            f"Her sorunun kendine özgü soru kökü, seçenekleri ve doğru cevabı var mı?"
        )
        idx += 1

    # Referans soru uyumu (baglamli YAML'lar)
    if template.has_reference_questions:
        areas.append(
            f"{idx}. **Referans soru uyumu** (reference_compliance): "
            f"Üretilen her soru, REFERANS DOĞRU CEVAPLAR bölümündeki senaryo yapısını, "
            f"seçenek formatını, doğru cevap mantığını ve çözüm akışını koruyor mu?"
        )
        idx += 1

    # Varyant kuralları uyumu
    if template.ozel_kurallar or template.sabit_ve_degisen:
        areas.append(
            f"{idx}. **Varyant kuralları uyumu**: "
            f"Soru, VARYANT KURALLARI bölümündeki özel kuralları ve sabit kalanları karşılıyor mu?"
        )
        idx += 1

    return "\n".join(areas)


def _build_chain(template: ParsedTemplate):
    """ParsedTemplate'ten dogrulama chain'i olusturur."""
    prompt = PromptTemplate(
        template=PROMPT_TEMPLATE,
        input_variables=["generated_question"],
        partial_variables={
            "sinif_seviyesi": str(template.sinif_seviyesi),
            "context_type": template.context.get("type", "?"),
            "validation_constraints": extract_for_validation_chain(template),
            "kontrol_alanlari": _build_check_areas(template),
            "format_instructions": _parser.get_format_instructions(),
        },
    )
    return prompt | _model | _parser


def validate_batch(
    template: ParsedTemplate,
    generated_question_text: str,
) -> BatchValidation:
    """Uretilen soruyu YAML kurallarina gore toplu dogrular.

    Args:
        template: 7 baslikli ParsedTemplate
        generated_question_text: Uretilen sorunun JSON metin temsili

    Returns:
        BatchValidation: Dogrulama sonucu (self_solution + TYMM kontrolleri dahil)
    """
    chain = _build_chain(template)
    pipeline_log("LLM-2", "Toplu doğrulama — model çağrılıyor…")
    result = chain.invoke({"generated_question": generated_question_text})
    pipeline_log("LLM-2", f"Toplu doğrulama tamamlandı (durum: {result.overall_status}).")
    return result
