"""
Chain 4: Gorsel Uretimi (LLM-4a + LLM-4b)
Model (prompt): gemini-2.5-flash (LLM-4a) - gorsel prompt muhendisligi
Model (gorsel): gemini-3-pro-image-preview (LLM-4b) - native genai client

Ana gorsel ve sik gorselleri AYRI kurallarla uretilir:
- Ana gorsel: extract_for_main_image_chain() — YAML'daki ana_gorsel kurallari
- Sik gorselleri: extract_for_option_image_chain() + option_scenes (LLM uretimi)
  Sadece has_visual_options=True ise uretilir.
"""
from __future__ import annotations

import base64
from pathlib import Path
from typing import Any, Optional

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate

import re

from pomodoro.models import GeneratedImages, GeneratedVisualQuestion
from pomodoro.yaml_loader import (
    ParsedTemplate,
    extract_for_main_image_chain,
    extract_for_option_image_chain,
)
from utils.currency_assets import (
    build_reference_block,
    resolve_required_denominations,
    upload_reference_files,
)
from utils.llm import MODEL_REGISTRY, ModelRole, get_image_client, get_model


_prompt_engineer_model = get_model(ModelRole.VISUAL_PROMPT_ENGINEER)


def _build_answer_alignment_reference(question: GeneratedVisualQuestion) -> str:
    """Soru-kökü ve beklenen doğru seçeneği gorsel prompt'una ekler."""
    if not question.questions:
        return "- Soru bulunamadi"

    q = question.questions[0]
    correct_label = (q.correct_answer or "").strip().upper()
    correct_text = q.options.get(correct_label, "")

    lines = [f"- Soru kökü: {q.question_stem}"]
    if correct_label and correct_text:
        lines.append(f"- Beklenen doğru seçenek: {correct_label}) {correct_text}")
    elif correct_label:
        lines.append(f"- Beklenen doğru seçenek etiketi: {correct_label}")
    lines.append(
        "- Görselde görülen nesneler yeniden sayıldığında veya grup yapısı okunduğunda öğrenci bu doğru "
        "seçeneğe ulaşmalıdır."
    )
    return "\n".join(lines)


def _collect_numeric_paths(data: object, prefix: str = "") -> list[str]:
    """Ic ice veri yapilarindaki sayisal alanlari yol bazli toplar."""
    items: list[str] = []
    if isinstance(data, dict):
        for key, value in data.items():
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            items.extend(_collect_numeric_paths(value, next_prefix))
    elif isinstance(data, list):
        for idx, value in enumerate(data):
            next_prefix = f"{prefix}[{idx}]"
            items.extend(_collect_numeric_paths(value, next_prefix))
    elif isinstance(data, (int, float)) and not isinstance(data, bool):
        label = prefix or "value"
        items.append(f"- {label}: tam olarak {data}")
    return items


def _build_exact_count_checklist(question: GeneratedVisualQuestion) -> str:
    """Question verisinden prompt'a eklenecek sayisal kontrol listesini uretir."""
    checklist: list[str] = []
    checklist.extend(_collect_numeric_paths(question.scene_elements or {}))
    checklist.extend(_collect_numeric_paths(question.hidden_computation or {}))

    if not checklist:
        checklist.append("- Sayisal ogeleri response once sayarak sabitle")

    return "\n".join(checklist)


def _build_countability_guardrails(question: GeneratedVisualQuestion) -> str:
    """Sayma hatalarini azaltmak icin sahneye ozel koruma maddeleri uretir."""
    combined = " ".join(
        [
            question.scene_description,
            question.scenario_text,
            str(question.visual_layout),
            str(question.visual_elements),
            str(question.hidden_computation or {}),
        ]
    ).lower()

    rules = [
        "- Sayılması gereken TÜM ana nesneleri düz, 2D eğitim afişi mantığında ve tamamen görünür çiz.",
        "- Sayılacak nesneleri açık boşluklarla ayır; birbirine temas eden, üst üste binen, yarısı gizlenen veya perspektif yüzünden küçülen nesne kullanma.",
        "- Sayım kritikse nesneleri satır-sütun, tek sıra veya net bölünmüş grup blokları halinde yerleştir.",
        "- Arka planı sade tut; dekoratif yaprak, gölge, kırıntı, desen veya tekrar eden aksesuarlar sayılması gereken nesnelerle karışmamalı.",
        "- Doğrudan sayılması gerekmeyen gizli miktarları tek tek görünür hale getirme; gerekiyorsa sadece etiket, kap veya grup göstergesi kullan.",
    ]

    if any(token in combined for token in ("adım", "başlangıç", "sonra", "önce", "panel", "sequence")):
        rules.extend(
            [
                "- Çok adımlı sahnelerde her paneli aynı açı, aynı ölçek ve aynı düzenle çiz.",
                "- Her panelde nesneleri aynı hizada grid veya sıra düzeninde tut; karakterler ve oklar nesneleri kapatmamalı.",
            ]
        )

    if any(token in combined for token in ("kese", "çanta", "kavanoz", "kutu", "tepsi", "sepet", "yuva", "torba")):
        rules.extend(
            [
                "- Kap veya taşıma nesnesi varsa, sayılması gereken öğeleri kabın içinde üst üste sıkıştırma.",
                "- Kabın içindeki nesnelerin görülmesi gerekmiyorsa içeriği hiç gösterme; görülmesi gerekiyorsa her nesne tam görünür ve tek tek ayrık olsun.",
            ]
        )

    if any(token in combined for token in ("deste", "düzine", "onluk", "birlik")):
        rules.extend(
            [
                "- Onluk/deste/düzine temsillerinde grup sayısı ile tekli nesneleri açıkça ayır.",
                "- Bağlı grup nesneleri tekil kalemlerle karışmasın; her onluk deste ayrı bir blok olarak görünmeli.",
            ]
        )

    return "\n".join(rules)


# ---------------------------------------------------------------------------
# Ana gorsel prompt sablonu
# ---------------------------------------------------------------------------

MAIN_IMAGE_PROMPT_TEMPLATE = """Sen {sinif_seviyesi}. sınıf eğitim materyali görselleri için prompt mühendisisin.
Görsel tipi: {image_type}

Aşağıdaki soru verileri ve görsel kurallarına dayanarak, bir görsel üretim modeline verilecek
detaylı ve yapılandırılmış bir görsel prompt oluştur.

## SORU VERİLERİ (yalnızca bağlam amaçlı — aşağıdaki metinler görsele YAZILMAMALIDIR)

Sahne: {scene_description}
Senaryo (BU METİN GÖRSELE YAZILMAYACAK, SADECE BAĞLAM İÇİN): {scenario_text}
Görsel düzeni: {visual_layout}
Görsel öğeler: {visual_elements}
Hesaplama verileri: {hidden_computation}

## SAYISAL KONTROL LİSTESİ

{exact_count_checklist}

## SAYILABİLİRLİK KORUMALARI

{countability_guardrails}

## CEVAP HİZALAMA KONTROLÜ

{answer_alignment_reference}

## ANA GÖRSEL KURALLARI

{main_image_constraints}

## NESNE SAYISI DOĞRULUĞU (KRİTİK)

- Görseldeki her nesne grubundaki öğe sayısı, hesaplama verilerinde belirtilen sayıyla BİREBİR eşleşmelidir.
- Sayısal etiket (örneğin "6") varsa etiket ile görselde çizilen nesne adedi MUTLAKA ayni olmalidir. Etiket 6 ise tam 6 nesne çizilmeli, ne 5 ne 7.
- Görseli üretmeden önce her grupta kaç nesne olacağını açıkça belirt ve bu sayıyı prompt boyunca koru.
- Öğrenci görseldeki ana nesneleri yeniden saydığında, gördüğü miktar doğru seçenekten farklı bir sonuca götürmemelidir.
- Bir sepette 3 nesne çizip doğru cevabı 5 yapan, ya da eksik miktarı görselde başka bir sayıya işaret eden kurgu KESİNLİKLE üretme.
- Artış-azalış, transfer, eksilme veya eşitleme içeren sahnelerde her aşamadaki miktarların hangisinin metinden, hangisinin görselden okunacağı net olmalı; görünür sayılar senaryodaki ipuçlarıyla çelişmemelidir.
- Eğer senaryo "her gün aynı miktar", "eşit sayıda", "aynı kadar arttı", "aynı kadar eksildi" diyorsa görselde de HER aşama bu kurala uymalıdır.

## KESİN YASAKLAR (tüm görseller için geçerli, istisnasız)

- ÖNCELİKLİ YASAK: Görselde senaryo metni, üst metin, soru kökü ifadesi veya soru cümlesi KESİNLİKLE yer almamalıdır. Görselin üstüne, altına veya herhangi bir yerine soru metni, senaryo cümlesi ya da açıklama paragrafı YAZILMAMALIDIR. Bu metinler HTML'de ayrıca gösterilmektedir; görselde TEKRAR edilmemelidir.
- Soru kökündeki ifadeler (örn. "Hangi renk karttaki işlemin sonucu en büyüktür?", "Oyunu kim kazanır?", "Toplam kaç boncuk kullanılmıştır?") görsele hiçbir biçimde yansıtılmamalıdır.
- Görselde yalnızca etiketler (kişi adları, şekil adları, sayılar, adım numaraları gibi kısa tanımlayıcılar) yer alabilir. Cümle, paragraf veya soru ifadesi ASLA görselde bulunmamalıdır.
- Cevabı, karşılaştırma sonucunu veya doğru seçeneği ele veren herhangi bir yazı, sembol veya işaret görselde bulunmamalıdır.
- Ust metin veya paragraf tek basina cozum vermemelidir; gorsel olmadan dogru cevap bulunabilecek kadar
  acik sayisal iliskiyi metinde tamamlama.
- Görselde çizilen nesne sayısı ile etiketlerdeki sayı arasında ASLA tutarsızlık olmamalıdır.
- Sayılması gereken nesneler dekoratif kümeler halinde değil, tek tek sayılabilir düzenli satır/sütun veya açık gruplar halinde gösterilmelidir.
- Belirsiz, üst üste binmiş veya birbirini kapatan nesneler kullanma. Her nesne tekil olarak ayırt edilebilmelidir.
- Öğrenci sayım yapmak için tahmin, yakınlaştırma veya nesneleri zihinde ayırma ihtiyacı duymamalıdır.
- Metinden bilinmesi gereken ama görselden bilinmemesi gereken miktarları tek tek çizip cevap sızdırma.
- Kapalı kutu, kavanoz, kese veya tepsi içinde yarısı gizlenen nesnelerle "sayılabilir" sahne kurma.
- Geometri gorsellerinde harf veya nokta etiketlerini tam kose ustune bindirme; etiketler ilgili koseyi
  gosterecek kadar yakin ama cizgilere degmeyecek ve kenarlardan az bir bosluk birakacak sekilde
  disariya offsetli yerlestirilmelidir.
- Noktalı kâğıt veya kareli zemin kullanılıyorsa arka plan çizgileri/noktaları ana şekilden daha silik,
  açık gri ve düşük kontrastlı olmalı; öğrencinin dikkatini şekilden çalmamalıdır.
- Noktalı kâğıt kullanılıyorsa tüm noktalar eşit aralıklı, hizalı ve düzenli bir ızgara mantığında
  görünmelidir; bazı satırlar koyu, bazıları seyrek, kaymış veya serbest el görünümünde olmamalıdır.
- Fotogercekci, sinematik, dramatik isikli, tamamen siyah-duz-cizgiye indirgenmis veya kupkuru teknik
  cizim gibi gorsel uretme.
- Bunun yerine ilkokul cocuklarina uygun sade, temiz, dengeli ve acikca ilustratif bir egitsel dil kullan.
- Renkleri abartma: goruntu gereksiz kadar renkli, suslu veya dikkat dagitici olmamali; olculu renk, hafif
  yumusak ton farklari ve okunurlugu artiran basit vurgular yeterlidir.

## GÖREV

Yukarıdaki verileri kullanarak, bir görsel üretim modeline (Gemini Image) verilecek
detaylı bir prompt yaz.

{gorev_maddeleri}

Prompt kısa ve net olsun, gereksiz tekrar yapma.
Görseldeki tüm yazılar ve etiketler Türkçe olmalıdır.

KRİTİK HATIRLATMA: Üretilecek görsel prompt'unda senaryo metni, soru kökü veya soru cümlesi KESİNLİKLE yer almamalıdır. Görselde yalnızca etiketler (isimler, sayılar, adım numaraları) bulunmalıdır. Soru metni görsele YAZDIRILMAMALIDIR.

{feedback_section}
"""

# ---------------------------------------------------------------------------
# Sik gorseli prompt sablonu
# ---------------------------------------------------------------------------

OPTION_IMAGE_PROMPT_TEMPLATE = """Sen {sinif_seviyesi}. sınıf eğitim materyali görselleri için prompt mühendisisin.

Aşağıdaki şık için bir görsel üretim prompt'u oluştur.

## ŞIK BİLGİSİ

Şık etiketi: {option_label}
Şık sahne açıklaması: {option_scene_description}

## ŞIK GÖRSELİ KURALLARI

{option_image_constraints}

## ANA GÖRSEL BAĞLAMI

Senaryo: {scenario_text}
Ana sahne: {scene_description}

## GÖREV

Bu şık için sade, net ve tutarlı bir görsel üretim prompt'u yaz.
Diğer şıklarla aynı stilde olmalı.
Görseldeki tüm yazılar Türkçe olmalıdır.

{feedback_section}
"""


def _sanitize_engineered_prompt(
    engineered_prompt: str,
    scenario_text: str,
    question: GeneratedVisualQuestion,
) -> str:
    """LLM-4a ciktisindaki senaryo metni, soru koku ve uzun cumleleri temizler.

    LLM-4a bazen kurallara ragmen senaryo metnini veya soru kokunu
    gorsel prompt'una dahil eder. Bu fonksiyon bu metinleri bulup cikarir
    ve gorselde YALNIZCA etiket (isim, sayi, adim numarasi) kalmasini saglar.
    """
    result = engineered_prompt

    # 1. Senaryo metnini cumlelerine bol ve her birini prompt'tan cikar
    if scenario_text:
        sentences = re.split(r'[.!?]+', scenario_text)
        for sentence in sentences:
            sentence = sentence.strip()
            if len(sentence) > 15:  # Kisa parcalari atlayarak false-positive onle
                result = result.replace(sentence, "")

    # 2. Soru koklerini cikar
    if question.questions:
        for q in question.questions:
            stem = q.question_stem or ""
            # HTML etiketlerini temizle
            clean_stem = re.sub(r'<[^>]+>', '', stem).strip()
            if clean_stem and len(clean_stem) > 10:
                result = result.replace(clean_stem, "")
                result = result.replace(stem, "")

    # 3. Anti-text hatirlatma ekle
    anti_text_reminder = (
        "\n\nZORUNLU GÖRSEL KURALI: "
        "Bu görselde HİÇBİR senaryo cümlesi, soru kökü, paragraf veya açıklama metni BULUNMAMALIDIR. "
        "Görselde YALNIZCA kısa etiketler (kişi adları, sayılar, adım numaraları, şekil adları, "
        "A/B/C harfleri) yer alabilir. Cümle veya paragraf içeren görsel KESİNLİKLE üretilmemelidir."
    )
    result = result.rstrip() + anti_text_reminder

    return result


def _build_image_task_items(template: ParsedTemplate) -> str:
    """YAML context.generation.structure listesini gorsel gorevlerine cevirir."""
    generation = template.context.get("generation", {})
    structure = generation.get("structure", [])

    items = [f"- {rule}" for rule in structure]
    if not items:
        items.append("- Sahne düzeninin tam tarifi")
        items.append("- Öğelerin yerleşimi ve görünümü")

    items.append("- Renk paleti ve genel stil (sade, çocuk dostu)")
    items.append("- Tüm etiketlerin Türkçe olması")
    return "\n".join(items)


def _build_feedback(feedback: Optional[str]) -> str:
    """Retry durumunda onceki gorsel dogrulama feedback'ini ekler."""
    if not feedback:
        return ""
    return (
        "## ÖNCEKİ DENEME GERİ BİLDİRİMİ\n\n"
        f"Önceki görselde şu sorunlar tespit edildi:\n{feedback}"
    )


def _engineer_main_visual_prompt(
    question: GeneratedVisualQuestion,
    template: ParsedTemplate,
    feedback: Optional[str] = None,
) -> str:
    """Ana gorsel icin prompt muhendisligi (LLM-4a) + post-processing."""
    prompt = PromptTemplate(
        template=MAIN_IMAGE_PROMPT_TEMPLATE,
        input_variables=[],
        partial_variables={
            "sinif_seviyesi": str(template.sinif_seviyesi),
            "image_type": template.image_type,
            "scene_description": question.scene_description,
            "scenario_text": question.scenario_text,
            "visual_layout": str(question.visual_layout),
            "visual_elements": str(question.visual_elements),
            "hidden_computation": str(question.hidden_computation or {}),
            "exact_count_checklist": _build_exact_count_checklist(question),
            "countability_guardrails": _build_countability_guardrails(question),
            "answer_alignment_reference": _build_answer_alignment_reference(question),
            "main_image_constraints": extract_for_main_image_chain(template),
            "gorev_maddeleri": _build_image_task_items(template),
            "feedback_section": _build_feedback(feedback),
        },
    )
    chain = prompt | _prompt_engineer_model | StrOutputParser()
    raw_prompt = chain.invoke({})
    return _sanitize_engineered_prompt(raw_prompt, question.scenario_text, question)


def _engineer_option_visual_prompt(
    label: str,
    scene_description: str,
    question: GeneratedVisualQuestion,
    template: ParsedTemplate,
    feedback: Optional[str] = None,
) -> str:
    """Sik gorseli icin prompt muhendisligi (LLM-4a)."""
    prompt = PromptTemplate(
        template=OPTION_IMAGE_PROMPT_TEMPLATE,
        input_variables=[],
        partial_variables={
            "sinif_seviyesi": str(template.sinif_seviyesi),
            "option_label": label,
            "option_scene_description": scene_description,
            "option_image_constraints": extract_for_option_image_chain(template),
            "scenario_text": question.scenario_text,
            "scene_description": question.scene_description,
            "feedback_section": _build_feedback(feedback),
        },
    )
    chain = prompt | _prompt_engineer_model | StrOutputParser()
    return chain.invoke({})


# ---------------------------------------------------------------------------
# Native genai gorsel uretimi (LLM-4b)
# ---------------------------------------------------------------------------

def _generate_image_native(
    prompt_text: str,
    output_path: Path,
    reference_files: Optional[list[Any]] = None,
) -> str:
    """Native genai client ile gorsel uretir ve dosyaya kaydeder.

    reference_files verilirse (Gemini Files API'ya onceden yuklenmis file
    objeleri) multimodal input olarak prompt ile birlikte modele gecirilir.
    PIL.Image inline yerine URI-tabanli file referansi kullanilir — bu yontem
    cok gorselli prompt'larda daha guvenilir sonuclar verir ve base64 inline'i
    onler. Ornek kullanim: Turk Lirasi banknot referansi.
    """
    client = get_image_client()
    config = MODEL_REGISTRY[ModelRole.IMAGE_GENERATOR]

    anti_text_block = (
        "\n\n=== KESİN METİN YASAĞI ===\n"
        "- Bu görselde HİÇBİR cümle, paragraf, senaryo metni veya soru kökü BULUNMAMALIDIR.\n"
        "- Görselin üstüne, altına veya herhangi bir yerine açıklama metni YAZDIRMA.\n"
        "- Görselde YALNIZCA kısa etiketler olabilir: kişi adları, sayılar, adım numaraları (1. Adım, 2. Adım gibi), şekil adları, A/B/C harfleri.\n"
        "- Soru cümlesi, senaryo veya paragraf metni görsele yazılırsa görsel HATALI sayılır.\n"
    )
    attempts = [
        prompt_text + anti_text_block,
        (
            prompt_text
            + "\n\nEK ZORUNLU TALIMAT:\n"
              "- Yanitta mutlaka tek bir PNG gorseli uret.\n"
              "- Sadece metin donme; gorsel cikisi zorunludur.\n"
              "- Nesne sayilarini yeniden say ve eksiksiz koru.\n"
              "- Sayilacak nesneleri ayri ayri, tam gorunur ve satir/sutun duzeninde ciz.\n"
              "- Kese, kutu, kavanoz, yuva veya tepsi icinde ust uste binen nesne kullanma.\n"
              "- Sayilmamasi gereken gizli miktarlari gorunur hale getirme.\n"
              "- Gorselde soru cumleleri, senaryo metni veya aciklama paragrafi KESINLIKLE yer almamali. Sadece kisa etiketler (isim, sayi, adim numarasi) olabilir.\n"
            + anti_text_block
        ),
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)

    reference_files = reference_files or []

    for attempt_prompt in attempts:
        # Multimodal contents: metin prompt + (opsiyonel) yuklenmis referans file'lar
        contents: list = [attempt_prompt, *reference_files]

        response = client.models.generate_content(
            model=config["model"],
            contents=contents,
            config={
                "response_modalities": ["TEXT", "IMAGE"],
            },
        )

        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data is not None:
                image_data = part.inline_data.data
                if isinstance(image_data, str):
                    image_data = base64.b64decode(image_data)
                with open(output_path, "wb") as f:
                    f.write(image_data)
                return str(output_path)

    raise RuntimeError("Gorsel uretim yaniti gorsel icermiyor.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_images(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    output_dir: str | Path = "output/images",
    feedback: Optional[str] = None,
) -> GeneratedImages:
    """Ana gorsel + (kosullu) sik gorsellerini uretir.

    Ana gorsel: extract_for_main_image_chain() kurallari ile
    Sik gorselleri: extract_for_option_image_chain() + option_scenes ile
                    (sadece has_visual_options=True ve option_scenes doluysa)

    real_currency=true ise Turk Lirasi referans gorselleri ana gorsel uretimine
    multimodal input olarak gecirilir.

    Args:
        template: 7 baslikli ParsedTemplate
        question: Mega chain ciktisi (GeneratedVisualQuestion)
        output_dir: Gorsel cikti dizini
        feedback: Onceki gorsel dogrulama geri bildirimi (retry icin)

    Returns:
        GeneratedImages: Ana gorsel + (opsiyonel) sik gorselleri
    """
    output_dir = Path(output_dir)

    # 0. Turk Lirasi referans gorsellerini (varsa) Gemini Files API'ye yukle.
    # Denominasyonlara LLM-1 karar verir (question.chosen_denominations).
    reference_files: list[Any] = []
    currency_reference_block = ""
    denomination_notes = ""
    if template.real_currency:
        denom_ids = question.chosen_denominations or []
        if not denom_ids:
            raise RuntimeError(
                "real_currency=true ama LLM-1 chosen_denominations alanini "
                "doldurmadi. Soru uretici promp'unda TL reference section dahil "
                "degilse kontrol et veya YAML'a ornek senaryo ekle."
            )
        denom_ids = resolve_required_denominations(denom_ids)
        uploaded = upload_reference_files(denom_ids)
        reference_files = [f for _, f in uploaded]
        currency_reference_block = build_reference_block(
            [d for d, _ in uploaded]
        )
        denomination_notes = (
            f"Türk Lirası referans görselleri (LLM-seçimi): {', '.join(denom_ids)}. "
            "Sahnede bu para birimleri gerçek tasarımlarıyla görünmeli."
        )

    # 1. Ana gorsel prompt muhendisligi (LLM-4a)
    main_prompt = _engineer_main_visual_prompt(question, template, feedback)
    if currency_reference_block:
        # Referans bloku LLM-4a ciktisinin sonuna eklenir; Gemini image modeline
        # bu blok + ekli uploaded file'lar birlikte ulasir.
        main_prompt = f"{main_prompt}\n\n{currency_reference_block}"

    # 2. Ana gorsel uretimi (LLM-4b)
    main_path = output_dir / "main_visual.png"
    main_image_path = _generate_image_native(
        main_prompt, main_path, reference_files=reference_files or None
    )

    # 3. Sik gorselleri (kosullu)
    option_images = None
    if template.has_visual_options and question.option_scenes:
        option_images = {}
        for label, scene_desc in question.option_scenes.items():
            opt_prompt = _engineer_option_visual_prompt(
                label, scene_desc, question, template, feedback
            )
            if currency_reference_block:
                opt_prompt = f"{opt_prompt}\n\n{currency_reference_block}"
            opt_path = output_dir / f"option_{label}.png"
            option_images[label] = _generate_image_native(
                opt_prompt, opt_path, reference_files=reference_files or None,
            )

    notes = f"Görsel tipi: {template.image_type}"
    if denomination_notes:
        notes = f"{notes}. {denomination_notes}"

    return GeneratedImages(
        main_image_path=main_image_path,
        option_images=option_images,
        generation_notes=notes,
    )
