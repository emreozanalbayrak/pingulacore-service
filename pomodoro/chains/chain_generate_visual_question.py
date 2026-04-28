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

from typing import Optional

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate

import hashlib

from pomodoro.models import GeneratedVisualQuestion
from pomodoro.pipeline_log import pipeline_log
from pomodoro.variant_rotation import get_variant_details, get_variant_names
from pomodoro.yaml_loader import ParsedTemplate, extract_for_question_chain, _dict_to_yaml_str
from utils.llm import ModelRole, get_model


def _variant_number_seeds(variant_name: str, idx: int) -> dict:
    """Varyant adindan deterministik ama varyantlar arasi farkli sayisal tohum uretir.

    Ayni varyant adi icin her zaman ayni tohumlari verir (reproducibility);
    farkli varyantlar farkli sayilar alir — bu parallel uretimde sayisal
    cesitliligi saglar.
    """
    h = int(hashlib.md5(variant_name.encode("utf-8")).hexdigest(), 16)
    return {
        "base": 12 + (idx * 17) + (h % 31),        # ~12..200 araliginda
        "divisor": 2 + ((h >> 8) % 8),              # 2..9
        "multiplier": 3 + ((h >> 16) % 10),         # 3..12
        "unit_digit": (h + idx) % 10,               # 0..9 birim basamak egilimi
        "secondary": 7 + (idx * 11) + ((h >> 24) % 17),  # ikincil kurgu sayisi
    }


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

## GÖREV

Aşağıdaki adımları sırayla uygula. Tüm çıktıyı tek seferde oluştur:

1. **Görsel sahne tasarla**: Sahnenin genel tarifini (scene_description), sahne öğelerini (scene_elements), varsa karakter ve hedef nesneyi, renk paletini belirle. scene_description içine nesne adı, etiket, başlık veya yön yazısı KOYMA — sadece nesnelerin fiziksel tarifini yaz.

2. **Senaryo yaz**: Sahneye uygun, {sinif_seviyesi}. sınıf düzeyinde kısa ve anlaşılır bir senaryo metni oluştur (scenario_text). Bu metin basılı bir sınav veya çalışma kağıdında yer alacaktır. Senaryo, çözümü tamamen vermeden en az bir çözüm-relevant sayısal ya da ilişkisel ipucu içermelidir; geri kalan kritik bilgi görselden okunmalıdır. Okuyucuya veya öğrenciye doğrudan seslenen ifadeler KESİNLİKLE KULLANILMAMALI.

3. **Gizli hesaplamaları yap**: Soru tipine göre gerekli gizli hesaplamaları yap (hidden_computation). Doğru cevabın ve çeldiricilerin temelini oluştur. Özellikle artış-azalış, transfer, eşitleme ve ardışık sayma durumlarında her aşamadaki miktarları ayrı ayrı kaydet.

4. **Görsel düzeni belirle**: Görselin düzenini (visual_layout) ve görsel öğeleri (visual_elements) tanımla. visual_elements içine "text", "label", "etiket" gibi yazı öğeleri EKLEME — sadece nesne çizimleri ve pozisyonlarını belirt.

{soru_uretim_talimati}

7. **HTML şablonu oluştur**: {html_talimati}

## ÖNEMLİ KURALLAR

{onemli_kurallar}

{reference_mode_instructions}

{variant_instruction}

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
            "Aşağıdaki kurallara uy:"
        )
        lines.append(
            "1. Her slot için verilen referans senaryoyu TEMEL AL; karakteri, "
            "bağlamı ve nesne seçimini değiştirebilirsin ama yapısal akışı koru."
        )
        lines.append(
            "2. Referans seçenek yapısını (kaç seçenek, ne tür içerik) aynen koru."
        )
        lines.append(
            "3. Doğru cevap referanstaki ile aynı mantıksal doğruluğa sahip olmalı."
        )
        lines.append(
            "4. Çözüm akışı referanstaki adımları izlemeli."
        )
        lines.append(
            "5. Soru kökü referanstaki soru_kokleri listesinden birini seç "
            "VEYA aynı yapıda yeni bir kök oluştur."
        )

    if template.varyant_tanimlari:
        lines.append(
            "\nVaryant tanımları verilmiştir. Her soru için uygun varyantı "
            "seç veya belirtilen varyant tanımına göre üret. "
            "SABİT KALANLAR bölümündeki maddelere kesinlikle uy."
        )

    return "\n".join(lines)


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
        f"{idx}. Karakter ismi seçerken YAML'daki isim_havuzundan RASTGELE bir isim seç — "
        f"havuzun tamamı adil biçimde kullanılmalı. Hiçbir ismi prompt'tan örnek alma; "
        f"isim_havuzu kendisi zaten gerekli çeşitliliği sağlar. Yaygın isimleri "
        f"(Ali, Ayse, Ece, Zeynep) da ender isimleri de eşit olasılıkla seç."
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
            "## ZORUNLU VARYANT SEÇİMİ\n\n"
            f"Bu soru için **\"{variant_name}\"** varyantı kullanılmalıdır. "
            f"Senaryonun konusu, nesneleri ve bağlamı bu varyant tanımına uygun olmalıdır. "
            f"Başka bir varyant KULLANMA."
        )

    sections = [
        "## ZORUNLU VARYANT KISITLARI\n",
        f"Bu soru YALNIZCA **\"{variant_name}\"** varyantına göre üretilmelidir.",
        "Aşağıdaki kısıtların TAMAMI zorunludur; hiçbiri atlanamaz.\n",
    ]

    # 1. Senaryo cekirdegi — en kritik hard constraint
    seed = details.get("senaryo_cekirdegi") or details.get("aciklama", "")
    if seed:
        sections.append("### SENARYO ÇEKİRDEĞİ (ZORUNLU)")
        sections.append(f"Senaryo şu çekirdek üzerine kurulmalıdır:\n{seed}")
        sections.append("Bu çekirdekten SAPMA veya FARKLI konu seçme YASAKTIR.\n")

    # 2. Gorsel notlari — zorunlu gorsel kurallari
    visual_notes = details.get("gorsel_notlari", [])
    if visual_notes:
        sections.append("### GÖRSEL ZORUNLULUKLARI")
        for note in visual_notes:
            sections.append(f"- ZORUNLU: {note}")
        sections.append("")

    # 3. Soru koku ornekleri — zorunlu soru koku kaliplari
    stem_examples = details.get("soru_koku_ornekleri", [])
    if stem_examples:
        sections.append("### SORU KÖKÜ SEÇİMİ (ZORUNLU)")
        sections.append("Soru kökü aşağıdakilerden biri OLMALI veya bunların yapısal eşdeğeri olmalı:")
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

    # 5. Farklilik zorunlulugu
    sections.append("### FARKLILIK ZORUNLULUĞU")
    sections.append(
        "Bu varyant, diğer varyantlardan TAMAMEN farklı bir soru üretmek içindir. "
        "Senaryo, nesneler, sayısal değerler ve görsel düzen yukarıdaki kısıtlara "
        "BİREBİR uymalı ve başka hiçbir varyanta benzememelidir."
    )

    # 6. Sayisal cesitlilik zorunlulugu + deterministik tohum
    all_variants = get_variant_names(template)
    if len(all_variants) > 1 and variant_name in all_variants:
        idx = all_variants.index(variant_name)
        seeds = _variant_number_seeds(variant_name, idx)
        siblings = [v for v in all_variants if v != variant_name]

        sections.append("")
        sections.append("### SAYISAL ÇEŞİTLİLİK ZORUNLULUĞU (KRİTİK)")
        sections.append(
            f"Bu varyant ({idx + 1}/{len(all_variants)}): \"{variant_name}\""
        )
        if siblings:
            sections.append(
                "Paralel olarak üretilen DİĞER varyantlar (bunlarla aynı sayıları "
                f"KULLANMA): {', '.join(siblings)}"
            )
        sections.append("")
        sections.append(
            "Bu varyanta ÖZEL, deterministik sayısal tohum değerler "
            "(diğer varyantlarda FARKLI olacaktır):"
        )
        sections.append(f"  - Temel kurgu sayısı önerisi: {seeds['base']}")
        sections.append(f"  - İkincil kurgu sayısı önerisi: {seeds['secondary']}")
        sections.append(f"  - Bölme/paylaşım için olası bölen: {seeds['divisor']}")
        sections.append(f"  - Çarpma/tekrar için olası çarpan: {seeds['multiplier']}")
        sections.append(f"  - Birim basamak eğilimi: {seeds['unit_digit']}")
        sections.append("")
        sections.append(
            "KRİTİK KURALLAR:\n"
            "1. Bu tohum değerleri YAML'daki sınıf seviyesi, sayı basamak sınırı ve "
            "problem mantığına UYGUN olacak şekilde kullan. YAML yasağı (ör. "
            "\"üç basamağı aşan yasak\", \"kalanlı bölme yasak\") her durumda önceliklidir.\n"
            "2. Yukarıdaki tohumlar birebir olmasa da yakın değerlere (±10-20%) "
            "yuvarlanabilir; ancak tam olarak aynı sayı dizisini başka varyantla "
            "paylaşma.\n"
            "3. Başka varyantlarda yaygın kullanılan klişe sayılar (10, 20, 50, 100, "
            "3×4, 2×5 gibi) bu varyantta KAÇINILMASI gerekenlerdir — yukarıdaki "
            "tohum değerlere sadık kal.\n"
            "4. Doğru cevabın sayısal değeri, çeldirici seçeneklerin sayısal "
            "değerleri ve senaryodaki TÜM miktarlar bu varyantta TOHUM TABANLI "
            "olmalı; 'standart örnekte ne vardı' yerine 'tohum bana ne veriyor' "
            "diye düşün."
        )

    return "\n".join(sections)


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
            "soru_uretim_talimati": _build_question_generation_instructions(template),
            "html_talimati": _build_html_instructions(template),
            "onemli_kurallar": _build_important_rules(template),
            "reference_mode_instructions": _build_reference_mode_instructions(template),
            "variant_instruction": _build_variant_instruction(template, variant_name),
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
) -> GeneratedVisualQuestion:
    """Tek bir LLM call ile sahne + soru + siklar + cozum uretir.

    Args:
        template: 7 baslikli ParsedTemplate
        difficulty: Zorluk seviyesi (kolay/orta/zor)
        feedback: Onceki deneme geri bildirimi (retry icin)
        variant_name: Kullanilacak varyant adi (None ise LLM secer)

    Returns:
        GeneratedVisualQuestion: Sahne, senaryo, soru, siklar, cozum, HTML
    """
    import random

    chain = _build_chain(template, difficulty, feedback, variant_name)
    pipeline_log("LLM-1", "Mega soru üretimi (sahne, soru, şıklar, HTML) — model çağrılıyor…")
    result = chain.invoke({})
    pipeline_log("LLM-1", "Mega soru üretimi tamamlandı.")

    # Siklari shuffle et: dogru cevap her zaman A olmasi engellensin.
    # Shuffle sonrasi q.correct_answer yeni etikete map'lenir.
    # Ayrica self_solution.chosen_answer (LLM'in kendi cevabi) ve html_content
    # (LLM'in urettigi statik HTML) shuffle oncesi siraya dayandigindan senkronize
    # edilmelidir: self_solution re-map, html_content ise bosaltilir — finalize
    # node'u build_question_html ile post-shuffle kanonik HTML'i yeniden uretir.
    self_solution = result.self_solution if isinstance(result.self_solution, dict) else None
    pre_shuffle_chosen_value: Optional[str] = None
    if self_solution and result.questions:
        old_chosen = self_solution.get("chosen_answer")
        if old_chosen:
            pre_shuffle_chosen_value = result.questions[0].options.get(old_chosen)

    for q in result.questions:
        labels = list(q.options.keys())
        values = list(q.options.values())
        correct_value = q.options[q.correct_answer]
        random.shuffle(values)
        q.options = dict(zip(labels, values))
        for label, value in q.options.items():
            if value == correct_value:
                q.correct_answer = label
                break

    if self_solution is not None and pre_shuffle_chosen_value is not None and result.questions:
        for label, value in result.questions[0].options.items():
            if value == pre_shuffle_chosen_value:
                self_solution["chosen_answer"] = label
                break

    # LLM'in urettigi statik html_content shuffle oncesi sik sirasini tasir;
    # finalize node'u build_question_html ile post-shuffle dogru HTML'i yazacagi
    # icin bu alani bosaltmak tek gercek kaynagi garantiler.
    result.html_content = ""

    return result
