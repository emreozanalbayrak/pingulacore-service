"""
Chain (opsiyonel): Turk Lirasi Sadakat Dogrulama

Sadece template.real_currency=True olan YAML'larda koşar.
LLM-5 (VISUAL_VALIDATOR) modelini kullanır; üretilen ana görseli + manifest'ten
yüklenen referans banknot/madeni para görsellerini birlikte gösterir ve
"görseldeki paralar referansa sadık mı?" sorusunu sorar.

Çıktı: CurrencyVerification(all_match, issues, missing_denominations)

NOT: Bu chain, pipeline'daki mevcut validate_visual/solve_visual_question
adımlarından AYRIDIR. Amacı sayıdan/layout'tan bağımsız olarak sadece para
birimi tasarım sadakatini incelemektir.
"""
from __future__ import annotations

from pathlib import Path

from langchain.messages import HumanMessage

from legacy_app.geometri.pomodoro.models import CurrencyVerification
from legacy_app.geometri.pomodoro.pipeline_log import pipeline_log
from legacy_app.shared.utils.currency_assets import get_asset_path
from legacy_app.shared.utils.image_data import encode_image_data_uri
from legacy_app.shared.utils.llm import ModelRole, get_model


_model = get_model(ModelRole.VISUAL_VALIDATOR)


VERIFY_PROMPT = """Sen Türk Lirası tasarımına hakim bir görsel denetçisin.

Aşağıda iki tür görsel var:
1. ÜRETİLEN GÖRSEL (ilk görsel): Eğitim materyali için üretilmiş sahne
2. REFERANS GÖRSELLER (sonraki görseller): Gerçek Türk Lirası banknot ve madeni paralarının orijinal tasarımı

## GÖREV

Üretilen görseldeki her Türk Lirası banknotu veya madeni parasını referanslarla karşılaştır ve şunları değerlendir:

- **Atatürk portresi**: Konum, açı, stil referansla eşleşiyor mu?
- **Rakam ve yazı**: Büyüklük, yazı tipi, yerleşim doğru mu?
- **Renk kodu**: Banknotun baskın rengi referansla aynı mı? (5 TL kahverengi/mor, 10 TL kırmızı, 20 TL yeşil, 50 TL turuncu, 100 TL mavi, 200 TL pembe)
- **Arka plan deseni**: Filigran, geometrik desen, güvenlik özellikleri benzer mi?
- **Madeni para**: Kenar dokusu, ortadaki simge, rakam konumu doğru mu?

## BEKLENEN PARA BİRİMLERİ

Senaryoda şu para birimleri yer almalı: {required_denominations}

## DEĞERLENDİRME KURALLARI

- Küçük stil farkları (örneğin renk tonu, açı) tolere edilebilir.
- Tamamen farklı bir ülke parası, yanlış rakam, yanlış portre veya icat edilmiş tasarım → all_match=false.
- Beklenen bir para birimi görselde hiç yoksa veya tanınamaz halde çizildiyse missing_denominations'a ekle.
- Sadece para tasarımına odaklan; sahnenin diğer öğelerini (karakterler, market rafları, çanta vb.) değerlendirme.

## ÇIKTI

JSON formatında döndür:
{{
  "all_match": true/false,
  "issues": ["..."],
  "missing_denominations": ["..."]
}}
"""


def verify_currency(
    main_image_path: str | Path,
    required_denominations: list[str],
) -> CurrencyVerification:
    """Üretilen görseldeki Türk Lirası tasarımlarını referanslarla karşılaştırır.

    Args:
        main_image_path: Üretilmiş ana görselin dosya yolu
        required_denominations: Manifest id'leri (örn. ["50_tl", "20_tl"])

    Returns:
        CurrencyVerification: sadakat sonucu
    """
    if not required_denominations:
        return CurrencyVerification(all_match=True, issues=[], missing_denominations=[])

    pipeline_log(
        "LLM-TL",
        f"Türk Lirası sadakat doğrulaması — {len(required_denominations)} para birimi kontrol ediliyor…",
    )

    prompt_text = VERIFY_PROMPT.format(
        required_denominations=", ".join(required_denominations),
    )

    # Multimodal mesaj: üretilen görsel + tüm referanslar
    content: list[dict] = [{"type": "text", "text": prompt_text}]

    # Üretilen görsel (ilk)
    main_uri = encode_image_data_uri(str(main_image_path))
    content.append({"type": "image_url", "image_url": {"url": main_uri}})

    # Referanslar (sırasıyla)
    for denom_id in required_denominations:
        ref_path = get_asset_path(denom_id)
        ref_uri = encode_image_data_uri(str(ref_path))
        content.append({"type": "image_url", "image_url": {"url": ref_uri}})

    structured_model = _model.with_structured_output(
        CurrencyVerification,
        method="json_schema",
    )

    message = HumanMessage(content=content)
    result = structured_model.invoke([message])
    pipeline_log(
        "LLM-TL",
        f"Türk Lirası doğrulama tamamlandı (all_match={result.all_match}, "
        f"sorun={len(result.issues)}, eksik={len(result.missing_denominations)}).",
    )
    return result
