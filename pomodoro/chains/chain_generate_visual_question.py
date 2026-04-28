"""
Chain 1: Mega Soru Uretimi (LLM-1)
Model: gemini-3.1-pro-preview, temp=0.2

Tek bir LLM call ile hepsini uretir:
  - Gorsel sahne tasarimi (scene_description, scene_elements, karakter, hedef, renk)
  - Senaryo metni
  - Gizli hesaplamalar
  - Gorsel duzeni ve ogeleri
  - Soru kokleri + siklar (QuestionItem)
  - [KOSULLU] Sik sahneleri (has_visual_options ise)
  - Ilk cozum denemesi (self_solution)
  - HTML sablonu

YAML basliklari: meta, context, format, dogru_cevap, distractors, tymm_uyum_kurallari
Prompt'taki her sey YAML'dan dinamik olarak gelir.
"""
from __future__ import annotations

import random
from typing import Optional

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate

from pomodoro.models import GeneratedVisualQuestion
from pomodoro.pipeline_log import pipeline_log
from pomodoro.variant_rotation import get_variant_details
from pomodoro.yaml_loader import ParsedTemplate, extract_for_question_chain, _dict_to_yaml_str
from utils.llm import ModelRole, get_model


_parser = PydanticOutputParser(pydantic_object=GeneratedVisualQuestion)
_model = get_model(ModelRole.QUESTION_GENERATOR)


# ---------------------------------------------------------------------------
# Prompt sablonu
#
# {sinif_seviyesi}     <- YAML meta.sinif_seviyesi
# {context_type}       <- YAML context.type
# {soru_aciklamasi}    <- YAML meta.aciklama
# {format_turu}        <- YAML format.type
# {yaml_constraints}   <- extract_for_question_chain() -- tum YAML basliklari
# {difficulty}         <- run() parametresi
# {onemli_kurallar}    <- _build_important_rules() -- YAML icerigine gore dinamik
# {soru_uretim_talimati} <- _build_question_generation_instructions()
# {html_talimati}      <- _build_html_instructions()
# {reference_mode_instructions} <- _build_reference_mode_instructions()
# {feedback_section}   <- Retry varsa onceki validation/solver feedback
# {format_instructions}<- PydanticOutputParser
# ---------------------------------------------------------------------------

PROMPT_TEMPLATE = """Sen {sinif_seviyesi}. sınıf için görsel destekli çoktan seçmeli soru üreten uzman bir eğitimcisin.
Soru tipi: {context_type}
Açıklama: {soru_aciklamasi}
Çıktı formatı: {format_turu}

Aşağıda sana verilen kuralların tamamı bu sorunun YAML şablonundan doğrudan alınmıştır.
Bu kurallara eksiksiz uyarak soru üret.

{yaml_constraints}

## ZORLUK SEVİYESİ
Zorluk: {difficulty}

{geometry_half_area_instruction}

{creativity_balance_instruction}

## GÖREV

Aşağıdaki adımları sırayla uygula. Tüm çıktıyı tek seferde oluştur:

1. **Sayıları sabitle (hidden_computation)**: İlk önce soru için kullanacağın TÜM sayısal değerleri belirle ve hidden_computation alanına yaz. Grup sayısı, eleman sayısı, toplam, fark, kalan — hepsini burada hesapla ve kaydet. **Bu adımdan sonra hiçbir sayıyı değiştirme.** Senaryo, görsel ve şıklar bu adımda belirlenen sayılardan türeyecek.

2. **Görsel sahne tasarla**: Sahnenin genel tarifini (scene_description), sahne öğelerini (scene_elements), varsa karakter ve hedef nesneyi, renk paletini belirle. scene_elements içindeki nesne adetleri ve grup büyüklükleri **Adım 1'deki sayılarla birebir aynı** olmalı. scene_description içine nesne adı, etiket, başlık veya yön yazısı KOYMA — sadece nesnelerin fiziksel tarifini yaz.

3. **Senaryo yaz**: Sahneye uygun, {sinif_seviyesi}. sınıf düzeyinde kısa ve anlaşılır bir senaryo metni oluştur (scenario_text). Senaryodaki sayısal değerler **Adım 1'deki değerlerle birebir aynı** olmalı — farklı sayı türetme. Bu metin basılı bir sınav veya çalışma kağıdında yer alacaktır. Senaryo, çözümü tamamen vermeden en az bir çözüm-relevant sayısal ya da ilişkisel ipucu içermelidir; geri kalan kritik bilgi görselden okunmalıdır. Okuyucuya veya öğrenciye doğrudan seslenen ifadeler KESİNLİKLE KULLANILMAMALI.

4. **Görsel düzeni belirle**: Görselin düzenini (visual_layout) ve görsel öğeleri (visual_elements) tanımla. visual_elements içindeki adetler **Adım 1'deki sayılarla birebir aynı** olmalı. visual_elements içine "text", "label", "etiket" gibi yazı öğeleri EKLEME — sadece nesne çizimleri ve pozisyonlarını belirt.

{soru_uretim_talimati}

7. **HTML şablonu oluştur**: {html_talimati}

## ÖNEMLİ KURALLAR

{onemli_kurallar}

{reference_mode_instructions}

{variant_instruction}

{number_hint_section}

{object_diversity_hint}

{feedback_section}

{format_instructions}
"""


def _build_question_generation_instructions(template: ParsedTemplate) -> str:
    """question_count'a gore soru uretim talimatlarini olusturur.

    question_count == 1: Mevcut tekli soru davranisi.
    question_count > 1:  Coklu soru — tek senaryo, tek gorsel, N farkli soru.
    """
    qc = template.question_count

    if qc <= 1:
        parts = [
            "5. **Soru ve şıkları oluştur**: Soru kökünü ve {labels} şıklarını oluştur. "
            "Doğru cevap DOĞRU CEVAP KURALI'na, çeldirici şıklar ÇELDİRİCİ STRATEJİLERİ'ne uygun olmalı."
            .format(labels="/".join(template.option_labels)),
        ]
        if template.has_visual_options:
            parts.append(
                "\n5b. **Şık sahnelerini oluştur**: Şıklar görsel olduğu için her şık ({labels}) "
                "için ayrı bir görsel sahne açıklaması yaz (option_scenes). Bu açıklamalar "
                "şık görsellerinin üretilmesinde kullanılacaktır."
                .format(labels=", ".join(template.option_labels))
            )
        parts.append(
            "\n6. **Soruyu çöz**: Ürettiğin soruyu kendin adım adım çöz. "
            "Seçtiğin cevabı ve çözüm mantığını self_solution alanına yaz. "
            "Bu, üretim doğruluğunu kontrol etmek içindir."
        )
        return "\n".join(parts)

    # question_count > 1
    lines = [
        f"5. **{qc} ayrı soru oluştur**: Yukarıdaki TEK senaryo ve TEK görsel "
        f"için {qc} farklı soru üret. Her soru:",
        "   - AYNI senaryoyu ve AYNI görseli kullanır (senaryoyu tekrar yazma, görsel öğeleri değiştirme)",
        "   - FARKLI bir soru kökü kullanır (SORU KÖKLERİ bölümündeki slot tanımlarından)",
        "   - FARKLI seçenek seti ve doğru cevap içerir",
        "   - Kendi çözüm açıklamasına (solution_explanation) sahiptir",
        "   - question_number alanı 1'den başlayarak sıralanır",
        "",
        "   Her sorunun şıkları DOĞRU CEVAP KURALI'na, çeldiriciler ÇELDİRİCİ STRATEJİLERİ'ne uygun olmalı.",
        "",
        f"   KRİTİK: Tüm {qc} soru `questions` listesinde ayrı QuestionItem olarak döndürülmeli.",
        "   KRİTİK: Senaryo metni (scenario_text) tüm sorular için ORTAKTIR — tek bir senaryo yaz.",
    ]

    # Slot bazli detayli talimatlar
    questions_data = template.context.get("questions", [])
    varyant_bicimleri = template.varyant_tanimlari.get("varyant_bicimleri", {})

    lines.append("")
    lines.append(f"   === HER SORU İÇİN DETAYLI SLOT TANIMLARI ({qc} soru) ===")

    for i, q_data in enumerate(questions_data):
        slot = q_data.get("slot", i + 1)
        beceri = q_data.get("beceri", {})
        if not isinstance(beceri, dict): beceri = {}
        katman = beceri.get("katman", "?")
        bilesenler = beceri.get("bilesenler", [])
        surec = beceri.get("surec_bileseni", "?")

        ref = next((r for r in template.referans_sorular if r.get("slot") == slot), {})

        lines.append(f"\n   --- Soru {slot} ({katman} · {surec}) ---")

        varyant_adi = ref.get("varyant_adi") or q_data.get("varyant_adi", "")
        if varyant_adi:
            lines.append(f"   Varyant: {varyant_adi}")
            for vb_key, vb_val in varyant_bicimleri.items():
                if isinstance(vb_val, dict) and varyant_adi and vb_key.replace("_", " ").lower() in varyant_adi.lower().replace(" - ", " ").replace("-", " "):
                    if vb_val.get("sunum"):
                        lines.append(f"   Sunum biçimi: {vb_val['sunum']}")
                    if vb_val.get("cevap_turu"):
                        lines.append(f"   Cevap türü: {vb_val['cevap_turu']}")
                    if vb_val.get("kritik_kural"):
                        lines.append(f"   Kritik kural: {vb_val['kritik_kural']}")

        if ref.get("soru_koku"):
            lines.append(f"   Soru kökü şablonu: {ref['soru_koku']}")
        if ref.get("dogru_cevap"):
            lines.append(f"   Referans doğru cevap: {ref['dogru_cevap']}")

        if bilesenler:
            lines.append(f"   Bilişsel hedef: {', '.join(bilesenler)}")

    # Anti-tekrar kurallari
    lines.append("")
    lines.append("   YARATICILIK KURALLARI:")
    lines.append("   - Her soru BİRBİRİNDEN BAĞIMSIZ bir bilişsel zorluk hedeflemelidir.")
    lines.append("   - Aynı soru kökünün farklı sözcüklerle tekrarı YASAKTIR.")
    lines.append("   - Her sorunun çeldiricileri kendi bilişsel hedefine özgü olmalı.")
    lines.append("   - Seçeneklerin şık metinleri sorular arasında kopyalanmamalı.")
    lines.append("   - Her sorunun doğru cevabına ulaşma YÖNTEMİ farklı olmalı.")

    lines.append("")
    lines.append(
        f"6. **Her soruyu ayrı çöz**: Ürettiğin {qc} sorunun her birini adım adım çöz. "
        "self_solution alanına tüm soruların çözümlerini yaz."
    )

    return "\n".join(lines)


def _build_html_instructions(template: ParsedTemplate) -> str:
    """HTML olusturma talimatini question_count'a gore dallandirir."""
    header = template.header_template or ""
    qc = template.question_count

    base_rules = (
        "\n\n   HTML KURALLARI:\n"
        '   - Görsel için TAM OLARAK şu placeholder\'ı kullan: <div class="visual-placeholder"></div>\n'
        "   - Bu placeholder'ın İÇİNE hiçbir şey koyma (iç div, metin, [Görsel] yazısı vb. YASAK)\n"
        "   - Placeholder tek bir boş div olmalı — sistem bunu otomatik olarak gerçek görselle değiştirecek\n"
        "   - HTML tam bir sayfa olmalı: <!DOCTYPE html>, <html>, <head>, <body> etiketleri dahil\n"
        "   - CSS stillerini <style> etiketi içinde tanımla\n"
    )

    if qc <= 1:
        return (
            f'Tüm içeriği birleştiren HTML şablonunu yaz (html_content). '
            f'HTML\'in başına şu yönerge metnini ekle: "{header}"'
            f'{base_rules}'
        )
    return (
        f'Tüm {qc} soruyu İÇEREN tek bir HTML şablonu yaz (html_content). '
        f'Üstte ortak senaryo metni, ardından görsel placeholder, sonra her soru ayrı '
        f'bir blok olarak sıralanmalı. HTML\'in başına şu yönerge metnini ekle: "{header}"'
        f'{base_rules}'
    )


def _build_reference_mode_instructions(template: ParsedTemplate) -> str:
    """Referans sorular ve/veya varyantlar varsa guided variation talimati dondurur."""
    if not template.has_reference_questions and not template.varyant_tanimlari:
        return ""

    lines = ["## REFERANS SORU MODU"]

    if template.has_reference_questions:
        lines.append(
            "\nBu YAML'da her soru slotu için referans tanımlar verilmiştir. "
            "Referanslar bir ESİN KAYNAĞIDIR; birebir taklit değildir:"
        )
        lines.append(
            "1. Referans senaryodan esinlen; karakteri, bağlamı, nesne seçimini ve "
            "olayın akışını özgürce farklılaştırabilirsin. Önemli olan bilişsel "
            "hedefi ve zorluk düzeyini korumak."
        )
        lines.append(
            "2. Seçenek sayısı ve biçim türü (metin/görsel/sayı) referansla aynı kalsın; "
            "ancak seçeneklerin içeriği ve ifadeleri taze olabilir."
        )
        lines.append(
            "3. Doğru cevap, referansla aynı MANTIKSAL işlemi temsil etmeli; "
            "aynı sayıları kullanmak zorunda değilsin."
        )
        lines.append(
            "4. Çözüm yöntemi referanstaki işlem mantığına uyumlu olmalı; "
            "fakat anlatım adımları farklı ifade edilebilir."
        )
        lines.append(
            "5. Soru kökünü soru_kokleri listesinden seçebilir veya aynı bilişsel "
            "hedefi vuran özgün bir kök yazabilirsin."
        )

    if template.varyant_tanimlari:
        lines.append(
            "\nVaryant tanımları bir çerçeve sunar: bilişsel hedefi ve işlem türünü korurken "
            "senaryo, nesne, görsel düzen ve dilde özgürce çeşitlendir. "
            "SABİT KALANLAR bölümündeki maddeler zorunludur; geri kalan her şeyde yaratıcı ol."
        )

    return "\n".join(lines)


def _build_creativity_balance_instruction(template: ParsedTemplate) -> str:
    """Geometri disi soru uretiminde kontrollu yaraticilik talimati."""
    if getattr(template, "visual_engine", "generative") == "geometric_deterministic":
        return ""

    return (
        "## KONTROLLÜ YARATICILIK\n\n"
        "Geometri dışı sorularda senaryo, nesne, mekân, karakter adı ve görsel düzen bakımından "
        "daha taze ve beklenmedik ama çocuk düzeyine uygun seçimler yap. Aynı klişe okul/market/"
        "sepet kurgularına sıkışma; bağlama doğal oturan farklı günlük yaşam alanları, nesneler "
        "ve küçük hikâye gerilimleri kurabilirsin.\n\n"
        "Yaratıcılık yalnızca sunum ve bağlamdadır: doğru cevap tanımı, YAML kuralları, "
        "hidden_computation, seçenek mantığı, sayılabilirlik ve çözüm tutarlılığı değişmez. "
        "Yaratıcı bir fikir matematiksel doğruluğu, tek doğru cevabı veya görsel-senaryo "
        "uyumunu zayıflatıyorsa fikri sadeleştir; doğruluk her zaman önceliklidir."
    )


def _build_geometry_half_area_instruction(template: ParsedTemplate) -> str:
    """Geometri sorularinda YAML izin veriyorsa kosegen/yarim alan kurgusuna izin verir."""
    if getattr(template, "visual_engine", "generative") != "geometric_deterministic":
        return ""

    return (
        "## GEOMETRİDE KÖŞEGEN / YARIM BİRİM ALAN\n\n"
        "Önce YAML kurallarını oku. Eğer YAML veya soru tipi yarım birim, köşegen, üçgen parça, "
        "diagonal/eğik kenar ya da 1/2 alan kullanımına izin veriyorsa; şeklin bazı birimleri "
        "köşegenle ikiye bölünmüş yarım karelerden oluşabilir. Bu durumda hidden_computation'da "
        "tam kareleri ve yarım kareleri ayrı ayrı yaz; örneğin `12 tam kare + 3 yarım kare = 13.5 birimkare`. "
        "Yarım birim alan kullanırsan soru kökünde veya senaryoda `köşegen kareyi iki eş yarıma ayırır` "
        "fikrini kısa ve doğal biçimde belirt; iki yarımın bir tam kare ettiğini sezdir ama toplam cevabı "
        "doğrudan verme.\n\n"
        "Eğer YAML açıkça `yalnız yatay-dikey kenar`, `çapraz/eğik kenar kullanılmamalı` veya "
        "benzer bir yasak veriyorsa köşegen/yarım alan kullanma. Bu izin, YAML kuralını geçersiz kılmaz."
    )


def _build_important_rules(template: ParsedTemplate) -> str:
    """YAML icerigine gore dinamik onemli kurallar listesi olusturur."""
    rules = []
    idx = 1

    # context.generation.kurallar
    kurallar = template.context.get("generation", {}).get("kurallar", [])
    if kurallar:
        rules.append(
            f"{idx}. KURALLAR bölümündeki tüm maddelere eksiksiz uy."
        )
        idx += 1

    # dogru_cevap (tanim vurgusu)
    if template.dogru_cevap:
        tanim = template.dogru_cevap.get("tanim", "")
        if tanim:
            rules.append(
                f"{idx}. Doğru cevap tanımı: \"{tanim}\". "
                f"Bu tanıma ve DOĞRU CEVAP KURALI bölümündeki tüm maddelere tam uyumlu olmalıdır."
            )
        else:
            rules.append(
                f"{idx}. Doğru cevap, DOĞRU CEVAP KURALI bölümüne tam uyumlu olmalıdır."
            )
        idx += 1

    # distractors (ornekler vurgusu)
    if template.distractors:
        rules.append(
            f"{idx}. Çeldirici şıkları ÇELDİRİCİ STRATEJİLERİ bölümündeki kalıplara "
            f"VE ÖRNEKLERE uygun oluştur. Her stratejinin 'ornek' alanını referans al."
        )
        idx += 1

    # format_spec.options
    if template.format_spec.get("options"):
        rules.append(
            f"{idx}. Seçeneklerin her birini adım adım simüle ederek doğrula."
        )
        idx += 1

    # format turu
    format_type = template.format_spec.get("type", "")
    if format_type:
        rules.append(
            f"{idx}. Çıktıyı {format_type} formatında oluştur."
        )
        idx += 1

    # format.options.word_count
    options = template.format_spec.get("options", {})
    if not isinstance(options, dict): options = {}
    opt_wmin = options.get("word_count_min")
    opt_wmax = options.get("word_count_max")
    if opt_wmin is not None or opt_wmax is not None:
        rules.append(
            f"{idx}. Her şık {opt_wmin}-{opt_wmax} kelime uzunluğunda olmalıdır."
        )
        idx += 1

    # Sayilar rakamla yazilmali
    rules.append(
        f"{idx}. Soru kökü ve senaryo metninde geçen tüm sayılar RAKAMLA yazılmalıdır; "
        f"kelimeyle yazılmamalıdır. Örneğin: 'üç' değil '3', 'yirmi dört' değil '24', "
        f"'elli' değil '50'."
    )
    idx += 1

    # Karsilastirma ifadeleri buyuk harf
    rules.append(
        f"{idx}. Soru kökü ve senaryo metninde geçen karşılaştırma/üstünlük ifadeleri "
        f"BÜYÜK HARFLE yazılmalıdır. Örnekler: EN BÜYÜKTÜR, EN KÜÇÜKTÜR, EN FAZLADIR, "
        f"EN AZDIR, BÜYÜKTÜR, KÜÇÜKTÜR, EŞİTTİR."
    )
    idx += 1

    rules.append(
        f"{idx}. Temsilî görsel kullanabilirsin; ancak temsil senaryodaki ana nesne ve bağlamla "
        f"GENEL OLARAK uyumlu olmalıdır. Simit deniyorsa alakasız bloklar, bilye deniyorsa rastgele "
        f"kutular kullanma. Temsil, öğrenciyi yanlış nesne saymaya veya yanlış işleme götürmemelidir."
    )
    idx += 1

    rules.append(
        f"{idx}. Senaryo metnindeki HER cümle problemin çözümüne, bağlamın kurulmasına veya görselin "
        f"yorumlanmasına hizmet etmelidir. 'Masada harika görünüyordu', 'çok mutlu oldular', "
        f"'ortam çok neşeliydi' gibi probleme katkısız, duygusal, dekoratif veya sadece süs amaçlı "
        f"kapanış cümleleri KESİNLİKLE yazma."
    )
    idx += 1

    rules.append(
        f"{idx}. Eğer senaryoda son cümle kullanılacaksa bu cümle nicelik, ilişki, hedef ya da işlem "
        f"bağlamını güçlendirmelidir; yalnızca atmosfer kuran boş bir kapanış olamaz."
    )
    idx += 1

    rules.append(
        f"{idx}. Görselden yapılacak doğrudan sayım, grup okuma, eksik miktarı tamamlama veya karşılaştırma "
        f"işlemi öğrenciyi TEK BİR doğru seçeneğe götürmelidir. Görselde görülen adetler, grup büyüklükleri, "
        f"eksik parçalar, kalan miktarlar ve etiketler doğru cevapla bire bir uyuşmalı; görsel başka bir şıkkı "
        f"destekleyecek biçimde kurulamaz."
    )
    idx += 1

    rules.append(
        f"{idx}. Görselden sayılması gereken ana nesneleri seçerken SAYILABİLİRLİK öncelikli düşün. "
        f"Sayım kritikse nesneler düz bakış açısından, satır-sütun ya da net ayrılmış gruplar halinde, "
        f"birbirine değmeden ve üst üste binmeden gösterilebilecek sahneler tasarla. "
        f"Yığın, dağınık küme, iç içe nesne, perspektif tepsi, yuva, kese, kapalı kavanoz, kutu içi veya "
        f"sayımı zorlaştıran dekoratif yerleşim seçme."
    )
    idx += 1

    rules.append(
        f"{idx}. Eğer soru mantığında bir miktarın doğrudan görselden sayılması GEREKMİYORSA, o miktarı "
        f"görselde yanlışlıkla görünür kılma. Metinden ya da etiketten bilinmesi gereken miktarı tek tek çizerek "
        f"öğrenciye cevabı sızdırma; bu durumda yalnızca kap, grup etiketi veya gerekli dış ipuçları görünür olabilir."
    )
    idx += 1

    rules.append(
        f"{idx}. Çok adımlı ya da önce-sonra görsellerinde her panel aynı ölçekte, aynı açıyla ve aynı sayma mantığıyla "
        f"kurulmalıdır. Her panelde değişen miktar tek bakışta karşılaştırılabilir olmalı; karakter, gölge veya dekor "
        f"sayılması gereken nesnelerin üstünü kapatmamalıdır."
    )
    idx += 1

    rules.append(
        f"{idx}. Aynı şablonda sürekli aynı klişe nesneyi tekrar etme. "
        f"Bağlama uygun, doğal ve kolay sayılabilir farklı nesneler seçebilirsin."
    )
    idx += 1

    rules.append(
        f"{idx}. Üst metin, çözümü tamamen gizleyen boş bir atmosfer paragrafı olmamalıdır. "
        f"En az bir çözüm-relevant sayısal ya da ilişkisel bilgi vermelidir: örneğin toplam, başlangıç, "
        f"hedef, gün sayısı, eşitlik ilişkisi, her gün aynı miktar, her rafta eşit sayıda gibi. "
        f"Ama tüm veriyi verip görseli gereksiz hale de getirmemelidir."
    )
    idx += 1

    rules.append(
        f"{idx}. Artış-azalış, eksilme, transfer, eşitleme veya adım adım değişim içeren sorularda "
        f"hidden_computation alanında her aşamayı açıkça yaz: başlangıç, ara durumlar, değişim miktarları, "
        f"son durum, metinde verilen bilgiler ve sadece görselden okunacak bilgiler ayrı ayrı izlenebilir olsun."
    )
    idx += 1

    rules.append(
        f"{idx}. Sayısal değerler çeşitli olmalı. Her seferinde aynı basit çarpım "
        f"(3×4, 2×5 gibi) kullanma. Sınıf seviyesine uygun farklı sayı çiftleri seç: "
        f"örneğin 4×7, 5×6, 3×9, 8×4, 36÷6, 45÷5 gibi. Aynı şablonda tekrar "
        f"üretildiğinde farklı sayılar kullanılmalı."
    )
    idx += 1

    # --- Senaryo kalitesi ---
    rules.append(
        f"{idx}. Senaryo metni, soru kökünde sorulan işlemi veya görevi ÖNCEDEN SÖYLEMEMELI. "
        f"Senaryo yalnızca sahneyi kurar; 'toplamı bulmaya çalışıyor', 'kaç tane gerektiğini hesaplıyor' "
        f"gibi soru kökünü tekrarlayan cümleler senaryoya KESİNLİKLE yazılmamalı. "
        f"Öğrenci ne yapması gerektiğini soru kökünden anlamalı, senaryodan değil."
    )
    idx += 1

    rules.append(
        f"{idx}. Son cümle dahil senaryo metnindeki her cümle en az bir sayısal veri, ilişki veya "
        f"kısıt vermelidir. 'Servis hazır oluyor', 'herkes çok beğendi', 'iş tamamlandı' gibi "
        f"çözüme sıfır katkı veren boş kapanış cümleleri ASLA kullanma. "
        f"Son cümle de mutlaka probleme bir bilgi eklemelidir."
    )
    idx += 1

    # --- Karakter ismi ---
    rules.append(
        f"{idx}. Karakter ismi tamamen serbest — önceden belirlenmiş bir listeden seçme, "
        f"soru kurgusu ve sahneye uygun özgün bir Türkçe isim kullan. "
        f"Her üretimde farklı bir isim tercih et."
    )
    idx += 1

    # --- Şıklarda birim ---
    rules.append(
        f"{idx}. Soru ölçülebilir bir büyüklük soruyorsa (km, GB, gram, metre, lira, adet, kişi vb.) "
        f"şıklardaki sayısal değerlerin yanına MUTLAKA uygun birim yazılmalı. "
        f"Örneğin '500' değil '500 GB'; '21' değil '21 km' olmalı. "
        f"Yalnızca birim belli olmayan saf sayma soruları (kaç tane?) birim gerektirmez."
    )
    idx += 1

    # --- HTML kalitesi ---
    rules.append(
        f"{idx}. HTML çıktısı MUTLAKA eksiksiz bir HTML belgesi olmalı (<!DOCTYPE html>, <html>, <head>, <body>). "
        f"Tüm stiller <style> bloğunda CSS sınıfları olarak tanımlanmalı; satır içi (inline) style kullanma. "
        f"'[Görsel Alanı: ...]' veya '[Görsel: ...]' gibi yer tutucu metin KESİNLİKLE kullanma. "
        f"Görsel bilgiyi HTML+CSS ile doğrudan oluştur (çubuk grafik, tablo, ızgara, ikon dizisi vb.). "
        f"Eğer görselde sayım gerekiyorsa, HTML'deki ögeler de görsel ile tutarlı şekilde sayılabilir olmalı."
    )
    idx += 1

    # --- Görsel-senaryo tutarlılığı ---
    rules.append(
        f"{idx}. scene_elements ve visual_elements alanlarındaki veriler (sayılar, nesneler, konumlar) "
        f"senaryo metni, soru kökü ve şıklarla BİREBİR tutarlı olmalı. Görselde sağ kefede 1 küp varsa "
        f"ama soru 'toplam kaç küp konulmalı' diyorsa, bu belirsizlik yaratır. "
        f"Görselde soru işareti veya boşluk bırakılan yer, sorulan bilinmeyeni TEK ve NET biçimde temsil etmeli."
    )
    idx += 1

    # self_solution
    if template.question_count > 1:
        rules.append(
            f"{idx}. Tüm {template.question_count} soruyu oluşturduktan sonra HER BİRİNİ KENDİN ÇÖZ "
            f"ve self_solution alanına yaz. Her sorunun çözümü doğru cevabıyla uyuşmalı."
        )
    else:
        rules.append(
            f"{idx}. Soruyu oluşturduktan sonra KENDİN ÇÖZ ve self_solution alanına yaz. "
            f"Çözümün doğru cevapla uyuşması ZORUNLUDUR."
        )
    idx += 1

    # TYMM
    if template.tymm_uyum_kurallari:
        rules.append(
            f"{idx}. TYMM uyum kurallarındaki sınıf sınırlarına ve yasaklara kesinlikle uy."
        )
        idx += 1

    # Referans soru modu
    if template.has_reference_questions:
        rules.append(
            f"{idx}. Referans soru tanımlarındaki senaryo, seçenek yapısı ve çözüm mantığına "
            f"yapısal olarak sadık kal. Birebir kopyalama ama eşdeğer yapı üret."
        )
        idx += 1

    # Varyant ozel kurallari
    if template.ozel_kurallar:
        rules.append(
            f"{idx}. ÖZEL KURALLAR bölümündeki tüm varyant kurallarına eksiksiz uy."
        )
        idx += 1

    if not rules:
        rules.append("1. YAML'daki tüm kurallara eksiksiz uy.")

    return "\n".join(rules)


def _build_variant_instruction(
    template: ParsedTemplate,
    variant_name: Optional[str],
) -> str:
    """Secilen varyant icin hard constraint talimatlari olusturur.

    Varyant detaylari (senaryo_cekirdegi, gorsel_notlari, soru_koku_ornekleri)
    varsa zorunlu kisitlamalar olarak enjekte eder. Yoksa basit talimat verir.
    """
    if not variant_name:
        return ""

    details = get_variant_details(template, variant_name)

    if not details:
        return (
            "## SEÇİLEN VARYANT\n\n"
            f"Bu soru için **\"{variant_name}\"** varyantı kullanılacak. "
            f"Varyantın bilişsel hedefini ve işlem türünü koru; senaryoyu, nesneleri ve "
            f"bağlamı kendi yaratıcılığınla çeşitlendirebilirsin."
        )

    sections = [
        "## SEÇİLEN VARYANT BAĞLAMI\n",
        f"Bu soru **\"{variant_name}\"** varyantına göre üretilecek.",
        "Aşağıdaki bilgiler bir ÇERÇEVE sunar: bilişsel hedefi ve işlem türünü koru, "
        "diğer unsurlarda (senaryo, nesne, karakter, görsel düzen, dil) özgürce çeşitlendir.\n",
    ]

    # 1. Senaryo cekirdegi — ilham kaynagi
    seed = details.get("senaryo_cekirdegi") or details.get("aciklama", "")
    if seed:
        sections.append("### SENARYO ÇEKİRDEĞİ (İLHAM)")
        sections.append(f"Aşağıdaki çekirdekten esinlen, ama bire bir kopyalama:\n{seed}")
        sections.append(
            "Bağlamı farklı bir yaşam alanına taşıyabilir, karakter ve nesneleri "
            "değiştirebilir, kurguyu özgürce yeniden yazabilirsin. Korunacak olan "
            "yalnızca soruda ölçülen bilişsel hedef ve işlem mantığıdır.\n"
        )

    # 2. Gorsel notlari — rehber
    visual_notes = details.get("gorsel_notlari", [])
    if visual_notes:
        sections.append("### GÖRSEL REHBERİ")
        for note in visual_notes:
            sections.append(f"- Öneri: {note}")
        sections.append(
            "Bu notlar görsel kurguya yön verir; ancak sahne düzenini, renkleri ve "
            "öğe yerleşimini kendi yaratıcılığınla belirleyebilirsin.\n"
        )

    # 3. Soru koku ornekleri — referans
    stem_examples = details.get("soru_koku_ornekleri", [])
    if stem_examples:
        sections.append("### SORU KÖKÜ ÖRNEKLERİ")
        sections.append("Aşağıdaki örneklerden birini seçebilir veya aynı bilişsel hedefi "
                        "vuran özgün bir soru kökü yazabilirsin:")
        for stem in stem_examples:
            sections.append(f"  - {stem}")
        sections.append("")

    # 4. Ek yapisal kisitlamalar (varsa)
    _EXTRA_FIELDS = [
        ("hedef_baglam", "HEDEF BAĞLAM"),
        ("tanimlayici_yargi_turu", "TANIMLAYICI YARGI TÜRÜ"),
        ("islem_turu", "İŞLEM TÜRÜ"),
        ("islem_duzeni", "İŞLEM DÜZENİ"),
        ("kullanilacak_nesneler", "KULLANILACAK NESNELER"),
        ("gorsel_tipi", "GÖRSEL TİPİ"),
        ("gorsel_tema", "GÖRSEL TEMA"),
    ]
    for field_key, label in _EXTRA_FIELDS:
        value = details.get(field_key)
        if not value:
            continue
        sections.append(f"### {label}")
        if isinstance(value, list):
            for item in value:
                sections.append(f"- {item}")
        elif isinstance(value, dict):
            for k, v in value.items():
                sections.append(f"  {k}: {v}")
        else:
            sections.append(str(value))
        sections.append("")

    # 5. Farklilik vurgusu
    sections.append("### ÇEŞİTLİLİK BEKLENTİSİ")
    sections.append(
        "Bu varyant, diğer varyantlardan ayrışan özgün bir soru üretmek içindir. "
        "Senaryo, nesneler, karakter, bağlam ve görsel düzen bakımından taze bir "
        "kurgu sun; aynı YAML'ın diğer varyantlarına ya da önceki üretimlere "
        "benzemesin."
    )

    return "\n".join(sections)



def _build_number_hint_section(
    excluded_number_sets: Optional[list[list[int]]] = None,
) -> str:
    """Onceki uretimlerde kullanilan sayi setlerini prompt'a ekler.

    LLM kendi soru tipine uygun sayilari serbest secer;
    sadece daha once kullanilmis TAM SET tekrar gelmez.
    """
    if not excluded_number_sets:
        return ""
    sets_str = "  |  ".join(
        "{" + ", ".join(str(n) for n in s) + "}"
        for s in excluded_number_sets[-10:]  # son 10 set yeterli
    )
    return (
        "## ZORUNLU SAYI ÇEŞİTLİLİĞİ\n\n"
        f"Bu şablonun önceki üretimlerinde kullanılan sayı setleri: {sets_str}.\n"
        f"hidden_computation'da belirleyeceğin ana sayılar bu setlerin HİÇBİRİYLE "
        f"TAM OLARAK ÖRTÜŞEMEZ. Bu bir zorunluluktur — tavsiye değil.\n"
        f"Birkaç sayının örtüşmesi kabul edilebilir; ancak tüm ana sayıların "
        f"aynı olduğu bir set YASAKTIR.\n"
        f"Kullandığın ana sayıları `used_numbers` alanına yaz (örn. [4, 7, 28])."
    )



def _build_object_diversity_hint(
    excluded_objects: Optional[list[str]] = None,
    suggested_object: Optional[str] = None,
) -> str:
    """Nesne cesitliligi talimati.

    suggested_object: bu uretim icin havuzdan claim edilmis nesne — guclu direktif.
    excluded_objects: onceki uretimlerde kullanilmis nesneler — ikincil engel.
    """
    lines = ["## BU ÜRETİMDE KULLANILACAK NESNE\n"]

    if suggested_object:
        lines.append(
            f"Bu üretimde ana nesne olarak **\"{suggested_object}\"** kullan. "
            f"Senaryo ve görsel bu nesne üzerine kurulmalı. "
            f"Nesne sınıf seviyesine uygun değilse yapısal olarak benzer ama "
            f"aynı kategoriden bir alternatif seçebilirsin — ama başka kategoriye geçme."
        )
    else:
        lines.append(
            "Soruda kullanacağın nesneleri ve ortamı özgürce seç. "
            "Meyve, sebze, kırtasiye, müzik aleti, spor ekipmanı, ev eşyası, "
            "oyuncak, giysi, yiyecek — sınıf seviyesine uygun her nesne kullanılabilir."
        )

    if excluded_objects:
        excluded_str = ", ".join(excluded_objects)
        lines.append(
            f"\nBu şablonun önceki üretimlerinde şu nesneler kullanıldı: {excluded_str}. "
            f"Bunları tekrar seçme."
        )

    lines.append(
        "\nKullandığın ana nesne(leri) `used_objects` alanına Türkçe olarak yaz "
        "(örn. `[\"havuç\", \"sepet\"]`)."
    )

    return "\n".join(lines)


def _build_feedback_section(feedback: Optional[str]) -> str:
    """Retry durumunda onceki feedback'i prompt'a ekler."""
    if not feedback:
        return ""

    return (
        "## ÖNCEKİ DENEME GERİ BİLDİRİMİ\n\n"
        "Önceki denemende aşağıdaki sorunlar tespit edildi. "
        "Bu sorunları düzelterek yeniden üret:\n\n"
        f"{feedback}"
    )


def _build_chain(
    template: ParsedTemplate,
    difficulty: str = "orta",
    feedback: Optional[str] = None,
    variant_name: Optional[str] = None,
    excluded_number_sets: Optional[list[list[int]]] = None,
    excluded_objects: Optional[list[str]] = None,
    suggested_object: Optional[str] = None,
):
    """ParsedTemplate'ten mega soru uretim chain'i olusturur."""
    prompt = PromptTemplate(
        template=PROMPT_TEMPLATE,
        input_variables=[],
        partial_variables={
            "sinif_seviyesi": str(template.sinif_seviyesi),
            "context_type": template.context.get("type", "?"),
            "soru_aciklamasi": template.meta.get("aciklama", "?"),
            "format_turu": template.format_spec.get("type", "?"),
            "yaml_constraints": extract_for_question_chain(template),
            "difficulty": difficulty,
            "geometry_half_area_instruction": _build_geometry_half_area_instruction(template),
            "creativity_balance_instruction": _build_creativity_balance_instruction(template),
            "soru_uretim_talimati": _build_question_generation_instructions(template),
            "html_talimati": _build_html_instructions(template),
            "onemli_kurallar": _build_important_rules(template),
            "reference_mode_instructions": _build_reference_mode_instructions(template),
            "variant_instruction": _build_variant_instruction(template, variant_name),
            "number_hint_section": _build_number_hint_section(excluded_number_sets),
            "object_diversity_hint": _build_object_diversity_hint(excluded_objects, suggested_object),
            "feedback_section": _build_feedback_section(feedback),
            "format_instructions": _parser.get_format_instructions(),
        },
    )
    return prompt | _model | _parser


def generate_visual_question(
    template: ParsedTemplate,
    difficulty: str = "orta",
    feedback: Optional[str] = None,
    variant_name: Optional[str] = None,
    excluded_number_sets: Optional[list[list[int]]] = None,
    excluded_objects: Optional[list[str]] = None,
    suggested_object: Optional[str] = None,
) -> GeneratedVisualQuestion:
    """Tek bir LLM call ile sahne + soru + siklar + cozum uretir.

    Args:
        template: 7 baslikli ParsedTemplate
        difficulty: Zorluk seviyesi (kolay/orta/zor)
        feedback: Onceki deneme geri bildirimi (retry icin)
        variant_name: Kullanilacak varyant adi (None ise LLM secer)
        claimed_numbers: Sayi havuzundan claim edilen sayi seti
        numbers_required: True ise claimed_numbers zorunlu, False ise tavsiye

    Returns:
        GeneratedVisualQuestion: Sahne, senaryo, soru, siklar, cozum, HTML
    """
    chain = _build_chain(template, difficulty, feedback, variant_name, excluded_number_sets, excluded_objects, suggested_object)
    pipeline_log("LLM-1", "Mega soru üretimi (sahne, soru, şıklar, HTML) — model çağrılıyor…")
    result = chain.invoke({})
    pipeline_log("LLM-1", "Mega soru üretimi tamamlandı.")

    # Siklari shuffle et: dogru cevap her zaman A olmasi engellensin.
    # Gorsel sik sahneleri varsa ayni permutasyonla tasinir; aksi halde
    # image_only sorularda A/B/C panelleri dogru cevap etiketiyle kayabilir.
    for q in result.questions:
        old_options = dict(q.options)
        old_option_scenes = dict(result.option_scenes or {})
        labels = list(q.options.keys())
        old_label_order = labels[:]
        random.shuffle(old_label_order)

        q.options = {
            new_label: old_options[old_label]
            for new_label, old_label in zip(labels, old_label_order)
        }

        if old_option_scenes and len(result.questions) == 1:
            result.option_scenes = {
                new_label: old_option_scenes[old_label]
                for new_label, old_label in zip(labels, old_label_order)
                if old_label in old_option_scenes
            }

        # correct_answer etiketini guncelle (icerik ayni, etiketi tasindi)
        old_correct = (q.correct_answer or "").strip().upper()
        for new_label, old_label in zip(labels, old_label_order):
            if old_label == old_correct:
                q.correct_answer = new_label
                break

        # self_solution.chosen_answer etiketini de yeni konumuna guncelle
        if result.self_solution and isinstance(result.self_solution, dict):
            old_chosen = str(result.self_solution.get("chosen_answer", "")).strip().upper()
            for new_label, old_label in zip(labels, old_label_order):
                if old_label == old_chosen:
                    result.self_solution["chosen_answer"] = new_label
                    break

    return result
