"""
Chain 5: Gorsel Dogrulama (LLM-5)
Model: gemini-2.5-flash, temp=0.1

YAML basliklari: meta, context.generation (image_type, kurallar), format
Ana gorsel + (varsa) sik gorsellerini 6 boyutta dogrular.

Genisletme:
- Sik gorselleri varsa her birini ayri ayri degerlendirir
- failed_targets: hangi gorseller basarisiz ("main", "option_A", ...)
"""
from __future__ import annotations

from typing import Optional

from langchain.messages import HumanMessage

from legacy_app.geometri.pomodoro.models import GeneratedVisualQuestion, VisualValidation
from legacy_app.geometri.pomodoro.pipeline_log import pipeline_log
from legacy_app.geometri.pomodoro.yaml_loader import ParsedTemplate, extract_for_visual_validation_chain
from legacy_app.shared.utils.image_data import encode_image_data_uri
from legacy_app.shared.utils.llm import ModelRole, get_model


_model = get_model(ModelRole.VISUAL_VALIDATOR)


VALIDATION_PROMPT = """Sen {sinif_seviyesi}. sınıf için üretilen görselleri doğrulayan uzman bir görsel denetçisin.
Görsel tipi: {image_type}

Aşağıdaki görseli/görselleri, soru verilerini ve doğrulama kurallarını kullanarak 6 boyutta değerlendir.

## SORU VERİLERİ

Sahne: {scene_description}
Senaryo: {scenario_text}
Görsel düzeni: {visual_layout}
Görsel öğeler: {visual_elements}
Hesaplama verileri: {hidden_computation}
Soru kökü: {question_stem}
Seçenekler:
{options_text}
Beklenen doğru seçenek: {expected_answer}

## DOĞRULAMA KURALLARI

{validation_constraints}

## DEĞERLENDİRİLECEK GÖRSELLER

{image_list_description}

## GÖREV

{gorsel_sayisi_notu}

Her görsel için aşağıdaki 6 boyutta değerlendir:

{boyut_aciklamalari}

Genel durumu belirle: Tüm boyutlar ve tüm görseller uygunsa "uygun", herhangi bir sorun varsa "revizyon_zorunlu".
Sorunlu boyutları failed_dimensions listesinde, sorunlu görselleri failed_targets listesinde raporla.
Sorun varsa düzeltme önerilerini feedback'te yaz.

Yanıtını MUTLAKA aşağıdaki JSON formatında ver:
{{
  "content_accuracy": true/false,
  "visual_clarity": true/false,
  "age_appropriateness": true/false,
  "language_correctness": true/false,
  "label_check": true/false,
  "layout_quality": true/false,
  "pedagogical_support": true/false,
  "overall_status": "uygun" veya "revizyon_zorunlu",
  "feedback": "...",
  "failed_dimensions": ["..."],
  "failed_targets": ["..."]
}}
"""


def _build_dimension_descriptions(template: ParsedTemplate) -> str:
    """6 dogrulama boyutunun aciklamalarini olusturur."""
    sinif = template.sinif_seviyesi
    return (
        f"1. **content_accuracy**: Görsel soru verileriyle uyumlu mu? Öğeler doğru konumlandırılmış mı? "
        f"Etiketlerde yazan sayı ile gerçekte çizilen nesne adedi BİREBİR eşleşmeli. "
        f"Hesaplama verilerindeki sayılarla (hidden_computation) görseldeki nesne sayıları uyuşmalı. "
        f"Sayı uyuşmazlığı varsa content_accuracy MUTLAKA false olmalı. "
        f"Görseldeki nesneler yeniden sayıldığında veya grup yapısı yorumlandığında ulaşılan sonuç, "
        f"beklenen doğru seçenekle bire bir aynı olmalı; görünür sayım başka bir seçeneği destekliyorsa "
        f"content_accuracy MUTLAKA false olmalı. "
        f"Senaryoda metinle verilen sayılar, adım sayıları, eşitlik ilişkileri veya artış-azalış bilgileri "
        f"görseldeki görünür miktarlarla çelişmemeli. Özellikle önce-sonra, her gün, her rafta, her sepette, "
        f"aynı miktar gibi ifadeler varsa görsel bunları tam karşılamalı. "
        f"Senaryodaki ana nesne veya bağlam ile görseldeki ana temsil genel olarak uyumlu olmalı; "
        f"temsili çizim kabul edilebilir ama bağlamı bozacak kadar alakasız olmamalıdır.\n"
        f"2. **visual_clarity**: Okunaklı ve net mi? Öğeler kolayca ayırt edilebilir mi?\n"
        f"   Sayılması gereken nesneler tek bakışta güvenle sayılabiliyor mu? "
        f"Üst üste binmiş, yarısı gizlenmiş, perspektif yüzünden belirsizleşmiş, dekorla karışan veya "
        f"kap/torba/kavanoz içinde sıkışmış nesneler varsa visual_clarity MUTLAKA false olmalı. "
        f"Noktalı kâğıt veya kareli zemin varsa, nokta/kare aralıkları eşit değilse veya satır-sütunlar "
        f"düzenli bir ızgara gibi görünmüyorsa visual_clarity MUTLAKA false olmalı. "
        f"Noktalı/kareli arka plan ana şekilden daha baskın, fazla koyu veya yüksek kontrastlıysa da "
        f"visual_clarity MUTLAKA false olmalı.\n"
        f"3. **age_appropriateness**: {sinif}. sınıf öğrencisi için uygun sadelikte mi? Aşırı karmaşık değil mi? "
        f"Gorsel dili ilkokul cocuklarina uygun sade ve egitsel ilustrasyon tarzinda mi; yoksa fazla "
        f"fotogercekci, fazla suslu, gereksiz kadar renkli ya da tam tersine kupkuru ve renksiz mi?\n"
        f"4. **language_correctness**: Görseldeki tüm yazılar Türkçe mi? Yabancı dilde etiket var mı? "
        f"Görselde senaryo metni, soru kökü, paragraf veya açıklama cümlesi bulunuyorsa language_correctness MUTLAKA false olmalı. "
        f"Görselde yalnızca kısa etiketler (kişi adları, sayılar, adım numaraları, şekil adları, A/B/C harfleri) bulunabilir. "
        f"Görselin üstünde, altında veya herhangi bir alanında cümle veya paragraf metni varsa bu KRİTİK bir hatadır.\n"
        f"5. **label_check**: Görseldeki etiketler ve vurgular doğru ve okunaklı mı? "
        f"Etiketlerdeki sayılar ile çizilen nesne sayıları tutarlı mı? "
        f"Geometri gorsellerinde kose/nokta harfleri ilgili koseye yakin ama cizgi ve kose ustune binmeden, "
        f"kenarlardan az bir bosluk birakacak sekilde offsetli mi? "
        f"Metinden bilinmesi gereken gizli miktar görselde yanlışlıkla görünür hale gelmişse label_check false olabilir. "
        f"Görselde senaryo cümlesi, soru kökü ifadesi veya açıklama paragrafı yer alıyorsa label_check MUTLAKA false olmalı — "
        f"bu metinler HTML şablonunda ayrıca gösterilir ve görselde tekrar edilmemelidir.\n"
        f"6. **layout_quality**: Öğeler üst üste binmiyor mu? Sınırlar içinde mi? Etiketler birbirini kapatmıyor mu? "
        f"Geometri etiketleri sekil kenarlarina nefes payi birakarak yerlestirilmis mi? "
        f"Noktalı veya kareli zeminde şekil, zemin ızgarasına hizalı mı; yarım birimlik kayma, eşit olmayan "
        f"ızgara aralığı veya perspektif bozulması var mı? Noktalı/kareli arka plan silik ve yardımcı "
        f"bir katman gibi mi, yoksa şekille yarışacak kadar baskın mı?\n"
        f"7. **pedagogical_support**: Görsel, sorunun ölçmeyi amaçladığı beceriyi (BECERİ HEDEFİ bölümü) "
        f"destekliyor mu? Öğrenci görselden doğru cevaba ulaşabilir mi? "
        f"Ust metin veya paragraf tek basina dogru cevabi veriyorsa ve gorsel zorunlu degilse "
        f"pedagogical_support MUTLAKA false olmalı. "
        f"Görsel yanlışlıkla ÇELDİRİCİ KONTROLÜ bölümündeki stratejilerden birini destekliyor mu? "
        f"Görseldeki görünür sayım öğrenciyi beklenen doğru cevap yerine başka bir şıkka götürüyorsa "
        f"pedagogical_support MUTLAKA false olmalı. "
        f"Sayılması gereken nesneler ancak tahminle, tekrar tekrar bakarak ya da kümeyi zihinde ayırarak "
        f"bulunabiliyorsa pedagogical_support MUTLAKA false olmalı. "
        f"Eğer soru mantığında doğrudan görünmemesi gereken bir miktar görselde açıkça görünüyorsa ve bu durum "
        f"çözüm yolunu bozuyor ya da cevabı sızdırıyorsa pedagogical_support MUTLAKA false olmalı. "
        f"Metindeki faydalı ipucu ile görsel birlikte kullanılınca tek ve güvenilir bir çözüm oluşmalı; "
        f"biri diğerini bozuyorsa pedagogical_support MUTLAKA false olmalı. "
        f"Eğer görselde kusur var ama çözümü etkilemiyorsa bunu feedback'te belirt; ancak yalnızca çözümü bozan kusurlar nedeniyle "
        f"pedagogical_support false olmalı."
    )


def _build_options_text(question: GeneratedVisualQuestion) -> str:
    """Siklari dogrulama prompt'u icin formatlar."""
    if not question.questions:
        return "-"
    q = question.questions[0]
    lines = []
    for label, content in sorted(q.options.items()):
        lines.append(f"{label}) {content}")
    return "\n".join(lines)


def _build_expected_answer_text(question: GeneratedVisualQuestion) -> str:
    """Beklenen dogru secenegi metinlestirir."""
    if not question.questions:
        return "-"
    q = question.questions[0]
    label = (q.correct_answer or "").strip().upper()
    content = q.options.get(label, "")
    if label and content:
        return f"{label}) {content}"
    return label or "-"

def validate_visual(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    image_path: str,
    option_image_paths: Optional[dict[str, str]] = None,
) -> VisualValidation:
    """Uretilen gorseli/gorselleri 6 boyutta dogrular.

    Ana gorsel + varsa sik gorsellerini birlikte degerlendirir.

    Args:
        template: 7 baslikli ParsedTemplate
        question: Mega chain ciktisi
        image_path: Ana gorsel dosya yolu
        option_image_paths: Sik gorselleri {"A": path, "B": path, ...} (opsiyonel)

    Returns:
        VisualValidation: 6 boyutlu dogrulama + failed_targets
    """
    # Gorsel listesi aciklamasi
    image_descriptions = ["- Ana görsel (main)"]
    if option_image_paths:
        for label in sorted(option_image_paths.keys()):
            image_descriptions.append(f"- Şık {label} görseli (option_{label})")

    gorsel_sayisi_notu = "Sadece ana görseli değerlendir."
    if option_image_paths:
        gorsel_sayisi_notu = (
            f"Toplam {1 + len(option_image_paths)} görsel var. "
            "Hem ana görseli hem de şık görsellerini ayrı ayrı değerlendir. "
            "Şık görselleri arasında stil tutarlılığı da kontrol et."
        )

    # Prompt olustur
    prompt_text = VALIDATION_PROMPT.format(
        sinif_seviyesi=template.sinif_seviyesi,
        image_type=template.image_type,
        scene_description=question.scene_description,
        scenario_text=question.scenario_text,
        visual_layout=str(question.visual_layout),
        visual_elements=str(question.visual_elements),
        hidden_computation=str(question.hidden_computation or {}),
        question_stem=question.questions[0].question_stem if question.questions else "-",
        options_text=_build_options_text(question),
        expected_answer=_build_expected_answer_text(question),
        validation_constraints=extract_for_visual_validation_chain(template),
        image_list_description="\n".join(image_descriptions),
        gorsel_sayisi_notu=gorsel_sayisi_notu,
        boyut_aciklamalari=_build_dimension_descriptions(template),
    )

    # Multimodal mesaj olustur
    content = [{"type": "text", "text": prompt_text}]

    # Ana gorsel
    main_uri = encode_image_data_uri(image_path)
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

    # Vision + structured output
    structured_model = _model.with_structured_output(
        VisualValidation,
        method="json_schema",
    )

    message = HumanMessage(content=content)
    pipeline_log("LLM-5", "Görsel doğrulama (vision) — model çağrılıyor…")
    result = structured_model.invoke([message])
    pipeline_log("LLM-5", f"Görsel doğrulama tamamlandı (durum: {result.overall_status}).")
    return result
