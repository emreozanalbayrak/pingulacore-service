"""
Image Generator Tools using direct google.genai SDK.

Provides diagram generation with quality validation via a judge loop.

NOTE: Image generation uses the Gemini image model.
The judge loop validates that generated images match paragraph content.
"""

from __future__ import annotations

import base64
import logging
import os
from dataclasses import dataclass, field
from io import BytesIO

from google import genai
from google.genai import types

__all__ = [
    "ImageGeneratorConfig",
    "ImageGenerationResult",
    "generate_diagram_with_judge",
    "generate_poster_with_judge",
    "generate_context_image_with_judge",
    "generate_option_images_grid",
    "generate_answer_critical_visual",
    "generate_question_visual_with_judge",
]

logger = logging.getLogger(__name__)


# ============================================================================
# CONFIGURATION
# ============================================================================


@dataclass
class ImageGeneratorConfig:
    """Configuration for image generation."""

    enabled: bool = False
    model: str = "gemini-3-pro-image-preview"
    judge_model: str = "gemini-3.1-pro-preview"
    temperature: float = 0.2
    max_retries: int = 2

    # Which subjects get images
    required_subjects: list[str] = field(default_factory=list)

    # Quality control
    max_judge_iterations: int = 3


# ============================================================================
# RESULT DATA CLASS
# ============================================================================


@dataclass
class ImageGenerationResult:
    """Result of image generation."""

    success: bool
    png_bytes: bytes | None = None
    png_base64: str | None = None
    error: str | None = None
    judge_iterations: int = 0


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _ensure_png_bytes(image_bytes: bytes) -> bytes:
    """Ensure image is in PNG format."""
    png_signature = b'\x89PNG\r\n\x1a\n'
    if image_bytes[:8] == png_signature:
        return image_bytes

    try:
        from PIL import Image
        img = Image.open(BytesIO(image_bytes))
        output = BytesIO()
        img.save(output, format='PNG')
        output.seek(0)
        return output.getvalue()
    except Exception as e:
        raise RuntimeError(f"Failed to convert image to PNG: {e}")


def _get_client() -> genai.Client:
    """Get or create a genai client."""
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GOOGLE_API_KEY or GEMINI_API_KEY environment variable required")
    return genai.Client(api_key=api_key)


# ============================================================================
# MAIN GENERATION FUNCTION
# ============================================================================


async def generate_diagram_with_judge(
    paragraph: str,
    subject: str,
    cfg: ImageGeneratorConfig,
) -> ImageGenerationResult:
    """
    Generate a diagram from paragraph with quality judge loop.

    Flow:
    1. Give paragraph to image model
    2. Judge checks if image matches paragraph
    3. If issues, regenerate (up to max iterations)

    Args:
        paragraph: The paragraph to visualize
        subject: Subject area
        cfg: Image generator configuration

    Returns:
        ImageGenerationResult with PNG bytes if successful
    """
    if not paragraph:
        return ImageGenerationResult(success=False, error="No paragraph provided")

    client = _get_client()

    prompt = f"""Bu paragrafin ANA KONUSUNU gosteren basit bir egitici illustrasyon ciz.

PARAGRAF:
\"\"\"{paragraph}\"\"\"

KRITIK KURALLAR:
1. BEYAZ ARKA PLAN - seffaf/transparent olmasin
2. TAMAMEN GORSEL/ILLUSTRASYON - HIC METIN YAZMA
3. SADECE ana nesneyi/sahneyi/kavrami ciz (ornek: bir hayvan, bir sahne, bir bitki)
4. Renkli ve profesyonel cocuk kitabi tarzi gorunum
5. Basit, sade, anlasilir

MUTLAK YAZI YASAGI (BU EN ONEMLI KURAL):
- GORSELIN HICBIR YERINDE YAZI/HARF/SAYI/KELIME OLMASIN
- Etiket, caption, baslik, aciklama YASAK
- Soru numarasi (1., 2., A), B)) YASAK
- Ne Turkce ne Ingilizce — HICBIR DILDE YAZI OLMASIN
- Insan karakterleri varsa bile uzerlerinde yazi olmasin
- Kitap, tabela, ekran, defter cizersen bile icinde YAZI OLMASIN (bos birak)

SADECE CIZIM: Goruntu sadece sekillerden, renklerden, figurlerden olussun. Metin iceren herhangi bir sey (kitap sayfasi, tabela, ekran) cizersen icleri BOS birak ya da soyut cizgilerle doldur."""

    best_image: bytes | None = None

    for iteration in range(cfg.max_judge_iterations):
        logger.info(f"[IMAGE] Iteration {iteration + 1}/{cfg.max_judge_iterations}")

        try:
            # Generate image
            for attempt in range(cfg.max_retries + 1):
                try:
                    response = await client.aio.models.generate_content(
                        model=cfg.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=cfg.temperature,
                        ),
                    )

                    # Extract image from response
                    png_bytes = None

                    # Check for inline data in parts
                    if response.candidates and response.candidates[0].content:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data:
                                if part.inline_data.data:
                                    png_bytes = part.inline_data.data
                                    if isinstance(png_bytes, str):
                                        png_bytes = base64.b64decode(png_bytes)
                                    break

                    if png_bytes:
                        png_bytes = _ensure_png_bytes(png_bytes)
                        logger.info(f"[IMAGE] Generated {len(png_bytes)} bytes")
                        break

                    logger.warning("[IMAGE] No image in response")

                except Exception as e:
                    logger.warning(f"[IMAGE] Attempt {attempt + 1} failed: {e}")

            if not png_bytes:
                continue

            best_image = png_bytes

            # Judge the image
            png_base64 = base64.b64encode(png_bytes).decode("utf-8")

            judge_prompt = f"""Bu gorselin kalitesini kontrol et.

PARAGRAF:
\"\"\"{paragraph}\"\"\"

KONTROL KRITERLERI (HER HANGI BIRI VARSA REDDET):
1. Gorselde OKUNABILIR YAZI/HARF/KELIME var mi? (Tek bir harf bile olsa REDDET)
2. Gorselde SAYI/RAKAM var mi? (Soru numarasi gibi: "1.", "2.", "A)" — Varsa REDDET)
3. Gorselde tabela, yazili kitap sayfasi, ekran yazisi, caption, baslik var mi? (Varsa REDDET)
4. Gorsel ANLAMSIZ/RASTGELE harfler (gibberish) iceriyor mu? (Varsa REDDET)
5. Gorsel paragrafla konu olarak uyumlu mu? (Uyumsuzsa REDDET)

KARAR:
- Gorsel TAMAMEN YAZISIZ (sadece sekil, renk, figur) ve paragrafla uyumlu ise: "KABUL"
- Her hangi bir yazi/harf/sayi/gibberish varsa: "REDDET: [neden]"

NOT: Insan karakterinin giysisinde logo/harf, arka plandaki kitap/tabela/ekranda yazi, kosedeki numara/baslik — HEPSI REDDET sebebidir.

Cevabini "KABUL" veya "REDDET: [neden]" formatinda ver."""

            try:
                # Pass image to judge
                judge_response = await client.aio.models.generate_content(
                    model=cfg.judge_model,
                    contents=[
                        types.Content(
                            parts=[
                                types.Part(text=judge_prompt),
                                types.Part(
                                    inline_data=types.Blob(
                                        mime_type="image/png",
                                        data=png_bytes,
                                    )
                                ),
                            ]
                        )
                    ],
                )

                result_text = str(judge_response.text).upper()

                if "KABUL" in result_text:
                    logger.info("[IMAGE] Judge approved")
                    return ImageGenerationResult(
                        success=True,
                        png_bytes=png_bytes,
                        png_base64=png_base64,
                        judge_iterations=iteration + 1,
                    )

                logger.info(f"[IMAGE] Judge rejected: {judge_response.text}")

            except Exception as e:
                logger.warning(f"[IMAGE JUDGE] Failed: {e}")
                # Accept image if judge fails
                return ImageGenerationResult(
                    success=True,
                    png_bytes=png_bytes,
                    png_base64=png_base64,
                    judge_iterations=iteration + 1,
                )

        except Exception as e:
            logger.error(f"[IMAGE] Iteration {iteration + 1} failed: {e}")

    # Return best image even if not perfect
    if best_image:
        png_base64 = base64.b64encode(best_image).decode("utf-8")
        return ImageGenerationResult(
            success=True,
            png_bytes=best_image,
            png_base64=png_base64,
            judge_iterations=cfg.max_judge_iterations,
        )

    return ImageGenerationResult(
        success=False,
        error="Image generation failed after all iterations",
        judge_iterations=cfg.max_judge_iterations,
    )


# ============================================================================
# POSTER (AFİŞ) GENERATION
# ============================================================================


async def generate_poster_with_judge(
    paragraph: str,
    topic: str,
    cfg: ImageGeneratorConfig,
    grade: int = 5,
) -> ImageGenerationResult:
    """
    Generate an educational poster (afiş) image with quality judge loop.

    Unlike diagram generation, this creates a visual poster/flyer that
    students see as the primary context for questions.

    Flow:
    1. Give topic + paragraph content to image model with poster instructions
    2. Judge checks poster quality and content alignment
    3. If issues, regenerate (up to max iterations)

    Args:
        paragraph: The paragraph content the poster should convey
        topic: Topic for the poster
        cfg: Image generator configuration

    Returns:
        ImageGenerationResult with PNG bytes if successful
    """
    if not paragraph:
        return ImageGenerationResult(success=False, error="No paragraph provided for poster")

    client = _get_client()

    prompt = f"""Egitici bir AFIS (poster) tasarla.

KONU: {topic}

AFIS ICERIGI (bu bilgileri gorsel olarak aktar):
\"\"\"{paragraph}\"\"\"

AFIS TASARIM KURALLARI:
1. BEYAZ veya ACIK RENK ARKA PLAN
2. Buyuk ve dikkat cekici BASLIK olmali (konu ile ilgili)
3. Kisa bilgilendirici maddeler veya sloganlar icersin
4. Konuyla ilgili GORSEL OGELER (ikonlar, semboller, basit resimler) kullan
5. Renkli, canli ve profesyonel poster tasarimi
6. TUM METINLER TURKCE olmali - Ingilizce YASAK
7. Okul panosuna asilabilir nitelikte
8. {grade}. sinif ogrencisine yonelik, sade ve anlasilir
9. Alt kisimda slogan veya cagri cumlesi olsun

KESINLIKLE YAPMA:
- Sadece duz metin yazma - GORSEL bir poster olmali
- Cok fazla metin kullanma - kisa ve oz ifadeler
- Ingilizce kelime kullanma
- Karanlik veya siyah arka plan kullanma

NOT: Bu bir AFIS/POSTER olmali - gorsel ogelerle zenginlestirilmis, dikkat cekici bir tasarim."""

    best_image: bytes | None = None

    for iteration in range(cfg.max_judge_iterations):
        logger.info(f"[POSTER] Iteration {iteration + 1}/{cfg.max_judge_iterations}")

        try:
            # Generate poster image
            png_bytes = None
            for attempt in range(cfg.max_retries + 1):
                try:
                    response = await client.aio.models.generate_content(
                        model=cfg.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=cfg.temperature,
                        ),
                    )

                    png_bytes = None
                    if response.candidates and response.candidates[0].content:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data:
                                if part.inline_data.data:
                                    png_bytes = part.inline_data.data
                                    if isinstance(png_bytes, str):
                                        png_bytes = base64.b64decode(png_bytes)
                                    break

                    if png_bytes:
                        png_bytes = _ensure_png_bytes(png_bytes)
                        logger.info(f"[POSTER] Generated {len(png_bytes)} bytes")
                        break

                    logger.warning("[POSTER] No image in response")

                except Exception as e:
                    logger.warning(f"[POSTER] Attempt {attempt + 1} failed: {e}")

            if not png_bytes:
                continue

            best_image = png_bytes

            # Judge the poster
            png_base64 = base64.b64encode(png_bytes).decode("utf-8")

            judge_prompt = f"""Bu egitici AFIS/POSTER gorselinin kalitesini kontrol et.

KONU: {topic}

KONTROL KRITERLERI:
1. Gorsel bir poster/afis mi? (Sadece duz metin degil, gorsel ogeler icermeli)
2. Konu ile ilgili mi? ({topic} konusuyla uyumlu mu?)
3. Turkce mi? (Ingilizce kelime var mi?)
4. Okunaklı ve anlasilir mi?
5. Dikkat cekici ve renkli mi?

KARAR:
- Eger gorsel bir poster/afis ise ve konu ile uyumlu ise: "KABUL"
- Eger sadece duz metin ise, konuyla uyumsuz ise veya Ingilizce iceriyorsa: "REDDET: [neden]"

Cevabini "KABUL" veya "REDDET: [neden]" formatinda ver."""

            try:
                judge_response = await client.aio.models.generate_content(
                    model=cfg.judge_model,
                    contents=[
                        types.Content(
                            parts=[
                                types.Part(text=judge_prompt),
                                types.Part(
                                    inline_data=types.Blob(
                                        mime_type="image/png",
                                        data=png_bytes,
                                    )
                                ),
                            ]
                        )
                    ],
                )

                result_text = str(judge_response.text).upper()

                if "KABUL" in result_text:
                    logger.info("[POSTER] Judge approved")
                    return ImageGenerationResult(
                        success=True,
                        png_bytes=png_bytes,
                        png_base64=png_base64,
                        judge_iterations=iteration + 1,
                    )

                logger.info(f"[POSTER] Judge rejected: {judge_response.text}")

            except Exception as e:
                logger.warning(f"[POSTER JUDGE] Failed: {e}")
                # Accept poster if judge fails
                return ImageGenerationResult(
                    success=True,
                    png_bytes=png_bytes,
                    png_base64=png_base64,
                    judge_iterations=iteration + 1,
                )

        except Exception as e:
            logger.error(f"[POSTER] Iteration {iteration + 1} failed: {e}")

    # Return best image even if not perfect
    if best_image:
        png_base64 = base64.b64encode(best_image).decode("utf-8")
        return ImageGenerationResult(
            success=True,
            png_bytes=best_image,
            png_base64=png_base64,
            judge_iterations=cfg.max_judge_iterations,
        )

    return ImageGenerationResult(
        success=False,
        error="Poster generation failed after all iterations",
        judge_iterations=cfg.max_judge_iterations,
    )


# ============================================================================
# CONTEXT IMAGE (INFOGRAPHIC/POSTER) GENERATION
# ============================================================================


async def generate_context_image_with_judge(
    context_text: str,
    topic: str,
    image_type: str,
    cfg: ImageGeneratorConfig,
    grade: int = 5,
) -> ImageGenerationResult:
    """
    Generate an educational infographic/poster image for a context question group.

    The image is embedded in the context HTML between the context text and questions.
    It should visualize key data/facts from the context without directly answering
    the questions.

    Args:
        context_text: The context text containing the scenario/data
        topic: Topic for the image
        image_type: Image type (infografik, poster, afis)
        cfg: Image generator configuration

    Returns:
        ImageGenerationResult with PNG bytes if successful
    """
    if not context_text:
        return ImageGenerationResult(success=False, error="No context text provided")

    client = _get_client()

    # Map image_type to Turkish description
    type_desc = {
        "infografik": "infografik (bilgi görseli)",
        "poster": "poster/afiş",
        "afis": "poster/afiş",
        "sutun_grafigi": "sütun grafiği",
        "pasta_grafigi": "pasta grafiği",
        "cizgi_grafigi": "çizgi grafiği",
        "gruplu_sutun_grafigi": "gruplu sütun grafiği",
        "tablo_gorseli": "zengin tablo görseli (ikon destekli, renkli)",
        "illustration": "illustrasyon/sahne gorseli",
        "soyagaci": "aile soyağacı diyagramı",
        "pictograph": "pictograph (şekil grafiği — figürlerle çizilmiş)",
    }.get(image_type, "infografik")

    # ═══════════════════════════════════════════════════════════════
    # CHART-SPECIFIC PROMPTS
    # ═══════════════════════════════════════════════════════════════

    _CHART_COMMON = """
ORTAK KURALLAR:
- BEYAZ arka plan, temiz ve sade tasarim
- Infografik, poster, ikon, cizim, karakter, slogan, aciklama metni YASAK
- SADECE grafik: eksenler, veriler — baska hicbir sey EKLEME
- BASLIK KOYMA — grafige HICBIR BASLIK yazisi ekleme! Ne ust tarafta ne alt tarafta baslik olmamali
- Turkce karakterler dogru olmali (ş, ı, ğ, ü, ö, ç)
- TUM METINLER TURKCE — Ingilizce YASAK
- Ders kitabindaki gibi sade, temiz, profesyonel grafik
"""

    _chart_types = {
        "sutun_grafigi": f"""SADECE bir SUTUN GRAFİGİ (bar chart) ciz.
{_CHART_COMMON}
SUTUN GRAFIGI KURALLARI:
- Y ekseni: sol tarafta, 0'dan baslayan deger araligi, cizgi isaretleri ile
- X ekseni: alt tarafta, kategori isimleri
- Her sutun FARKLI RENKTE olmali (yesil, sari, turuncu, kirmizi, kahverengi gibi)
- Sutunlarin USTUNDE deger yazili olmali (ör: 85%, 55 kisi)
- Y ekseni ETIKETI: sol tarafta dikey yazi (ör: "Ogrenci Sayisi")
""",
        "pasta_grafigi": f"""SADECE bir PASTA GRAFİGİ (pie chart) ciz.
{_CHART_COMMON}
PASTA GRAFIGI KURALLARI:
- Daire seklinde pasta grafigi ciz
- Her dilim FARKLI RENKTE olmali
- Her dilimin YANINDA veya USTUNDE yuzde degeri yazili olmali (ör: %35)
- Her dilimin YANINDA kategori ismi olmali
- Dilimler buyukten kucuge saat yonunde siralanmali
- Grafik altinda veya yaninda ACIKLAMA (legend) olabilir
- Toplam %100 olmali
""",
        "cizgi_grafigi": f"""SADECE bir CİZGİ GRAFİGİ (line chart) ciz.
{_CHART_COMMON}
CIZGI GRAFIGI KURALLARI:
- Y ekseni: sol tarafta, deger araligi, cizgi isaretleri ile
- X ekseni: alt tarafta, zaman/kategori isimleri
- Veri noktalari YUVARLAK isaretlerle gosterilmeli
- Noktalar arasinda CIZGI ile birlestirilmeli
- Her noktanin USTUNDE veya YANINDA deger yazili olmali
- Cizgi rengi belirgin olmali (mavi veya kirmizi)
- Y ekseni ETIKETI: sol tarafta dikey yazi
- Birden fazla cizgi varsa FARKLI RENKLERDE olmali ve ACIKLAMA (legend) eklenmeli
""",
        "gruplu_sutun_grafigi": f"""SADECE bir GRUPLU SUTUN GRAFİGİ (grouped bar chart) ciz.
{_CHART_COMMON}
GRUPLU SUTUN GRAFIGI KURALLARI:
- Her kategori icin 2 sutun YAN YANA olmali
- Iki grup FARKLI RENKLERDE olmali (ör: mavi ve turuncu)
- Grafik altinda ACIKLAMA (legend) olmali: hangi renk hangi grubu temsil ediyor
- Y ekseni: sol tarafta, 0'dan baslayan deger araligi
- X ekseni: alt tarafta, kategori isimleri
- Sutunlarin USTUNDE deger yazili olmali
- Y ekseni ETIKETI: sol tarafta dikey yazi
""",
        "tablo_gorseli": f"""Asagidaki verileri iceren sade bir TABLO gorseli ciz.
{_CHART_COMMON}
TABLO GORSELI KURALLARI:
- Baslik satiri KOYU RENK arka planli (mavi veya gri), beyaz yazilar
- Veri satirlari ZEBRA CIZGILI (bir beyaz, bir acik gri)
- Kenar cizgileri ince ve duzgun
- Hucrelerdeki yazilar okunakli ve ortalanmis
- Tablo sade ve profesyonel olmali — ders kitabindaki gibi
""",
    }

    # Determine which prompt to use
    _is_chart_type = image_type in _chart_types
    _has_table = "<table" in context_text.lower() if context_text else False

    if _is_chart_type:
        # Specific chart type requested
        chart_rules = _chart_types[image_type]
        prompt = f"""{chart_rules}

KONU: {topic}

VERI KAYNAGI:
\"\"\"{context_text}\"\"\"

KESINLIKLE YAPMA:
- Infografik, poster, ikon, cizim, karakter, ok, kutu, slogan EKLEME
- Sorularin cevabini dogrudan veren ifadeler ekleme
- Ingilizce kelime kullanma
- Karanlik veya siyah arka plan kullanma
- Sadece duz metin yazma veya tabloyu metin olarak kopyalama

NOT: Bu SADECE bir {type_desc} olmali — ders kitabindaki gibi sade, temiz, profesyonel."""

    elif image_type == "illustration":
        # Simple illustrative scene (no chart, no poster, no table)
        prompt = f"""Asagidaki senaryoyu gosteren kucuk, sade bir ILLUSTRASYON ciz.

KONU: {topic}

SENARYO:
\"\"\"{context_text}\"\"\"

ILLUSTRASYON KURALLARI:
- BEYAZ arka plan, temiz ve sade tasarim
- Senaryoda anlatilan ana karakter(ler)in yaptigi eylemi gosteren TEK BIR SAHNE ciz.
- Karakterler sade, cizgi-film benzeri, {grade}. sinif sinavina uygun.
- Arka planda senaryonun gectigi mekandan 1-2 detay olabilir.
- HICBIR METIN YAZMA (baslik, caption, konusma balonu icinde uzun yazi YASAK).
- Kisa Turkce etiket (1-2 kelime) yalnizca gerekiyorsa eklenebilir.
- Kucuk boyutlu (soru kenarina yerlestirilecek) ama ayrintili.
- TABLO/GRAFIK/INFOGRAFIK YASAK — sadece ILLUSTRASYON.
- Sorularin cevabini dogrudan veren spesifik bilgi YAZMA/GOSTERME.

KESINLIKLE YAPMA:
- Baslik veya yazi bloklari ekleme
- Ingilizce kelime kullanma
- Karanlik arka plan kullanma

NOT: Bu sade, kisa bir sahne illustrasyonu — baglam metnine goz atan ogrenci icin gorsel ipucu."""

    elif image_type == "infografik" and _has_table:
        # Infografik + table data → default to bar chart
        chart_rules = _chart_types["sutun_grafigi"]
        prompt = f"""{chart_rules}

KONU: {topic}

VERI KAYNAGI:
\"\"\"{context_text}\"\"\"

KESINLIKLE YAPMA:
- Infografik, poster, ikon, cizim, karakter, ok, kutu, slogan EKLEME
- Sorularin cevabini dogrudan veren ifadeler ekleme
- Ingilizce kelime kullanma
- Karanlik veya siyah arka plan kullanma
- Sadece duz metin yazma veya tabloyu metin olarak kopyalama

NOT: Bu SADECE bir sutun grafigi olmali — ders kitabindaki gibi sade, temiz, profesyonel."""

    else:
        # Generic infographic/poster
        infographic_extra = ""
        if image_type == "infografik":
            infographic_extra = """
INFOGRAFIK TASARIM KURALLARI (KRITIK — REFERANS YAPIYA TAM UYGUN OLMALI!):

REFERANS GOZ SAGLIGI INFOGRAFIGI ORNEGI:
  ┌─────────────── GOZ SAGLIGIMIZI KORUMAK ICIN NELER YAPMALIYIZ? ───────────┐
  │ [Ekran mesafesi]●──┐                         ┌──●[A vitamini tuketin]    │
  │ [Gunes gozlugu]●───┤    [BUYUK GOZ]          ├──●[Sigara dumani]         │
  │ [Gozleri dinlen]●──┤    [ILLUSTRASYON]       ├──●[Gozluk/lens]           │
  │ [Bilincli kirp] ●──┘                         └──●[Goz muayenesi]         │
  └───────────────────────────────────────────────────────────────────────────┘

ZORUNLU LAYOUT:
- ORTADA BUYUK bir ANA GORSEL/ILLUSTRASYON (konunun sembolu)
  * "goz sagligi" → BUYUK GOZ ILLUSTRASYONU
  * "dis sagligi" → BUYUK DIS/DISFIRCASI
  * "el yikama" → BUYUK SABUN/EL
  * "saglikli beslenme" → BUYUK TABAKTA SEBZE/MEYVE
- SOL TARAFTA 3-4 tavsiye kutusu, SAG TARAFTA 3-4 tavsiye kutusu
- Her kutu ayri RENKTE (mor, pembe, turuncu, mavi, kirmizi, yesil, lacivert)
- Her kutudan merkeze INCE BAGLANTI CIZGISI gider
- Her kutuda: NOKTA (●) + 2-5 kelimelik TURKCE TAVSIYE ("Ekran mesafesini koruyun")

KESIN YASAKLAR (BUNLARDAN BIRI VARSA REDDEDILSIN):
- ASLA sutun/cubuk grafik YAPMA — bu bir DATA GORSELLEMESI DEGIL
- ASLA tablo YAPMA — satir/sutun yapisi YASAK
- ASLA sayi/yuzde/istatistik yazma
- ASLA basliksiz/tek kutu format — MUTLAKA dagitik tavsiye kutulari
- ASLA dikey liste/bullet point — RADYAL dagilim zorunlu

STIL:
- ARKA PLAN: Beyaz veya cok acik pastel
- CIZGILER: Ince, soft renkler
- METIN: Turkce, kisa emirli cumle ("Yapin", "Koruyun", "Uzak durun")
- ILLUSTRASYONLAR: Cocuk kitabi tarzi, renkli, sempatik
- BOYUT: Her tavsiye kutusu okunakli ama sade

INFOGRAFIK = TAVSIYE DAGILIMI, GRAFIK DEGIL!
"""
        elif image_type == "pictograph":
            infographic_extra = """
PICTOGRAPH (SEKIL GRAFIGI) OZEL KURALLAR:

REFERANS PICTOGRAPH ORNEGI (Veli Meslek Grafigi):
  Veli Sayisi
  ↑
  ♀    ♀    ♀♂    ♀
  ♂♂   ♂♂♂  ♂♂    ♂♀
  ♀♂   ♀♀♂  ♀♀    ♂♀
  ♂♂   ♂♂♂  ♂♂    ♂♂
  ♂♂   ♂♂♂  ♂♂    ♂♂
  ┴────┴────┴────┴────→ Meslekler
  Memur Isci Ciftci Esnaf

  Not: Her sekil (♂) bir veliyi gostermektedir.

ZORUNLU LAYOUT:
- Y ekseni (yatay): KATEGORI adlari (Memur, Isci, Ciftci, Esnaf / Turkce, Matematik / vb.)
- X ekseni (dikey): Sayi gostergesi (Veli Sayisi, Ogrenci Sayisi, Soru Sayisi)
- Her KATEGORI icin UST USTE YIGILI KISI FIGURLERI (ayni renk, ayni sekil)
- Her figurun anlami: ALT ETIKETTE "Not: Her sekil 1 X'i gostermektedir"

FIGUR KULLANIMI:
- Konuya gore uygun SEKIL:
  * "meslek/insanlar" → KISI FIGURU (simit adam)
  * "meyve" → MEYVE IKONU (her elma = 1 birim)
  * "hayvan" → HAYVAN SILUETI
  * "kitap/okul" → KITAP/KALEM IKONU
- Hepsi AYNI BUYUKLUKTE ve AYNI RENKTE

KESIN YASAKLAR:
- ASLA duz CUBUK/SUTUN grafik cizme — pictograph = kategori bazinda tekrarlayan figurler
- ASLA 3D grafik
- ASLA renkli bar chart — SADECE sekil yigilmalar

STIL:
- Arka plan BEYAZ
- Figurler canli renkte (kirmizi, mavi, yesil)
- Alt etiket Turkce ("Her sekil bir X'i gostermektedir")
- Cocuk kitabi kalitesinde sade tasarim
"""
        elif image_type == "tablo_gorseli":
            infographic_extra = """
ZENGIN TABLO GORSELI KURALLARI (KRITIK — COCUK KITABI STILI):

REFERANS ORNEK (Ali Sorumluluk Tablosu):
  - Uste tablo BASLIGI: BUYUK, RENKLI, KUTULU
  - Sutun basliklari: Gun isimleri yaprak/bayrak seklinde
  - Satir basliklari: Gorev adi + ILGILI IKON (cocuk cizimi yaninda)
  - Hucre icerikleri: Renkli yildiz/isaret ikonlari (dolu/bos yildiz gibi)
  - Arka plan: Pastel mavi-yesil tonlari

REFERANS ORNEK (Haftalik Ders Programi):
  - Uste dekorativ baslik (BORDERLI, RENKLI)
  - Sutunlar gun bazli renklı sekilde ayri (pembe, mavi, mor, yesil, turuncu)
  - Her hucrede ders adi RENKLI KUTU icinde
  - Kenarlarda kucuk gorseller (kitap, kalem, cizgiler)
  - Cocuk kitabi atmosferi

ZORUNLU OZELLIKLER:
- Baslik ZORUNLU (tablo konusunu soyleyen, dikkat cekici)
- Satir/sutun basliklari belirgin RENKLI
- Hucrelerde metin Turkce
- Mumkun yerlerde KUCUK IKON/EMOJI ekle (yildiz, onay, cocuk, sembol)
- Pastel canli renkler (mavi, pembe, yesil, sarı)
- Kenarlarda kucuk dekorativ ogeler olabilir (cicek, kalem, kitap, cocuk)
- ARKA PLAN: Beyaz veya cok acik pastel desen

KESIN YASAKLAR:
- DUZ, sikici 2 sutun tablo YASAK (cok basit)
- Siyah/gri tek renk tablo YASAK
- Excel tarzi YASAK

Bu bir 2. sinif ders kitabi icin RENKLI, DIKKAT CEKICI tablo olmali!
"""
        elif image_type == "soyagaci":
            infographic_extra = """
SOYAGACI OZEL KURALLAR (KRITIK!):
- LAYOUT: Hiyerarsik aile agaci (yukaridan asagiya nesil siralamasi)
- En ustte: Dede/Nine (1 veya 2 kisi) — cercevede portreler, altinda isimler
- Ortada: Ebeveynler ve kardesleri — birlesen cift oklari
- En altta: Cocuklar/torunlar — yatay cizgiyle baglanmis
- Her kisi icin: Yuvarlak veya dikdortgen cerceve icinde PORTRE + ALTINDA ISIM
- Evlilik iliskisi: YATAY CIZGI iki kisi arasinda
- Ebeveyn-cocuk iliskisi: DIKEY CIZGI ebeveynlerden cocuklara
- Kardesler: YATAY CIZGI ile birbirine bagli
- Her portre renkli, cocuk kitabi tarzinda (kadin/erkek/cocuk ayirt edilebilir)
- TABLO YASAK — liste YASAK — sadece gercek AILE AGACI DIYAGRAMI
- Arka plan BEYAZ, cizgiler SIYAH, portreler RENKLI
"""
        prompt = f"""Egitici bir {type_desc} tasarla.

KONU: {topic}

BAGLAM METNI (bu bilgileri gorsel olarak aktar):
\"\"\"{context_text}\"\"\"

TASARIM KURALLARI:
1. BEYAZ veya ACIK RENK ARKA PLAN
2. BASLIK KOYMA — gorselde HICBIR BASLIK yazisi olmamali! (cunku soruda baslik sorulacak)
3. Baglam metnindeki ONEMLI VERILERI ve GERCEKLERI gorsel olarak sun
4. Konuyla ilgili GORSEL OGELER (ikonlar, semboller, basit cizimler) kullan
5. Renkli, sade ve profesyonel tasarim
6. TUM METINLER TURKCE olmali - Ingilizce YASAK
7. {grade}. sinif ogrencisine yonelik, okunaklı ve anlasilir
8. Kucuk boyutta (340px genislik) okunabilir olmali
9. Kisa bilgi maddeleri veya sloganlar kullanabilirsin
{infographic_extra}
KESINLIKLE YAPMA:
- BASLIK veya MANSET yazisi ekleme — gorsel baslıksiz olmali
- Sorularin cevabini dogrudan veren ifadeler ekleme
- Cok fazla metin kullanma - kisa ve oz ifadeler
- Ingilizce kelime kullanma
- Karanlik veya siyah arka plan kullanma
- Sadece duz metin yazma - GORSEL ogeler olmali

NOT: Bu bir {type_desc} olmali - gorsel ogelerle zenginlestirilmis, dikkat cekici bir tasarim."""

    best_image: bytes | None = None

    for iteration in range(cfg.max_judge_iterations):
        logger.info(f"[CONTEXT_IMAGE] Iteration {iteration + 1}/{cfg.max_judge_iterations}")

        try:
            # Generate image
            png_bytes = None
            for attempt in range(cfg.max_retries + 1):
                try:
                    response = await client.aio.models.generate_content(
                        model=cfg.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=cfg.temperature,
                        ),
                    )

                    png_bytes = None
                    if response.candidates and response.candidates[0].content:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data:
                                if part.inline_data.data:
                                    png_bytes = part.inline_data.data
                                    if isinstance(png_bytes, str):
                                        png_bytes = base64.b64decode(png_bytes)
                                    break

                    if png_bytes:
                        png_bytes = _ensure_png_bytes(png_bytes)
                        logger.info(f"[CONTEXT_IMAGE] Generated {len(png_bytes)} bytes")
                        break

                    logger.warning("[CONTEXT_IMAGE] No image in response")

                except Exception as e:
                    logger.warning(f"[CONTEXT_IMAGE] Attempt {attempt + 1} failed: {e}")

            if not png_bytes:
                continue

            best_image = png_bytes

            # Judge the image
            png_base64 = base64.b64encode(png_bytes).decode("utf-8")

            infografik_extra_judge = ""
            if image_type == "infografik":
                infografik_extra_judge = """
INFOGRAFIK ICIN EK KONTROL (KRITIK):
- LAYOUT kontrolu: Merkez gorsel + etrafta bilgi kutulari/baloncuklari formati olmali
- CUBUK GRAFIK, BAR CHART, TABLO varsa → REDDET (bu tavsiye/kural infografigi olmali)
- Ana bilgi "X yapin", "Y'den uzak durun" tarzinda tavsiye/kural icermeli
- Yuzde/sayisal deger odakli ise → REDDET (bu bir veri grafigi degil)
- Radyal/dagitik layout olmali (tek bir cubuk/tablo blogu DEGIL)
"""
            judge_prompt = f"""Bu egitici {type_desc} gorselinin kalitesini kontrol et.

KONU: {topic}

KONTROL KRITERLERI:
1. Gorsel bir {type_desc} mi? (Sadece duz metin degil, gorsel ogeler icermeli)
2. Konu ile ilgili mi? ({topic} konusuyla uyumlu mu?)
3. Turkce mi? (Ingilizce kelime var mi?)
4. Okunakli ve anlasilir mi? (Kucuk boyutta bile okunabilir mi?)
5. Dikkat cekici ve renkli mi?
{infografik_extra_judge}
KARAR:
- Eger gorsel bir {type_desc} ise ve konu ile uyumlu ise: "KABUL"
- Eger sadece duz metin ise, konuyla uyumsuz ise veya Ingilizce iceriyorsa: "REDDET: [neden]"

Cevabini "KABUL" veya "REDDET: [neden]" formatinda ver."""

            try:
                judge_response = await client.aio.models.generate_content(
                    model=cfg.judge_model,
                    contents=[
                        types.Content(
                            parts=[
                                types.Part(text=judge_prompt),
                                types.Part(
                                    inline_data=types.Blob(
                                        mime_type="image/png",
                                        data=png_bytes,
                                    )
                                ),
                            ]
                        )
                    ],
                )

                result_text = str(judge_response.text).upper()

                if "KABUL" in result_text:
                    logger.info("[CONTEXT_IMAGE] Judge approved")
                    return ImageGenerationResult(
                        success=True,
                        png_bytes=png_bytes,
                        png_base64=png_base64,
                        judge_iterations=iteration + 1,
                    )

                logger.info(f"[CONTEXT_IMAGE] Judge rejected: {judge_response.text}")

            except Exception as e:
                logger.warning(f"[CONTEXT_IMAGE JUDGE] Failed: {e}")
                # Accept image if judge fails
                return ImageGenerationResult(
                    success=True,
                    png_bytes=png_bytes,
                    png_base64=png_base64,
                    judge_iterations=iteration + 1,
                )

        except Exception as e:
            logger.error(f"[CONTEXT_IMAGE] Iteration {iteration + 1} failed: {e}")

    # Return best image even if not perfect
    if best_image:
        png_base64 = base64.b64encode(best_image).decode("utf-8")
        return ImageGenerationResult(
            success=True,
            png_bytes=best_image,
            png_base64=png_base64,
            judge_iterations=cfg.max_judge_iterations,
        )

    return ImageGenerationResult(
        success=False,
        error="Context image generation failed after all iterations",
        judge_iterations=cfg.max_judge_iterations,
    )


# ============================================================================
# QUESTION-AWARE VISUAL GENERATION (visual_context mode)
# ============================================================================

# Template base name → structured visual generation config
# text_level: TAM_METIN (exact sentences) | ICERIK (content complete) | GORSEL (illustration-heavy)
# hint: content guidance for the visual
# answer_concealment: what structural patterns to AVOID (prevents layout leaking the answer)
TEMPLATE_VISUAL_HINTS: dict[str, dict[str, str]] = {
    # Bolum 1.1 - Metnin Anlam Yonu
    "konu": {
        "text_level": "GORSEL",
        "hint": "Paragrafin ana konusunu temsil eden gorsel ogeler on planda olmali.",
        "answer_concealment": "Tek bir konuyu vurgulayan duzen YAPMA — birden fazla konu alani goster ki ogrenci secim yapsin.",
    },
    "ana_fikir": {
        "text_level": "ICERIK",
        "hint": "Yazarin mesajini sezdiren gorsel sahne. TUM seceneklerdeki fikirlerin gorselde bir karsiligi olmali ki celdiriciler guclu olsun.",
        "answer_concealment": "Ana fikri dogrudan yazan slogan/baslik KOYMA. Birden fazla fikri gorsel olarak esit agirlikta sun.",
    },
    "yardimci_fikir": {
        "text_level": "ICERIK",
        "hint": "Birden fazla bilgi noktasi gorsel olarak ayri ayri sunulmali.",
        "answer_concealment": "Bir bilgi noktasini diger(ler)inden belirgin sekilde FARKLI gosterme.",
    },
    # Bolum 1.2
    "baslik": {
        "text_level": "ICERIK",
        "hint": "Icerikten baslik cikarilabilecek gorsel sahne.",
        "answer_concealment": "Gorselde baslik/slogan metni YAZMA — ogrenci icerigi gorup baslik onersin.",
    },
    "anahtar_sozcuk": {
        "text_level": "TAM_METIN",
        "hint": "Anahtar sozcugun gecme/gecmeme durumu gorsel metinlerden anlasilmali.",
        "answer_concealment": "Belirli kelimeleri VURGULAMA/KALINLASTIRMA — tum kelimeler esit gorunmeli.",
    },
    "soru_cevap": {
        "text_level": "ICERIK",
        "hint": "Gorseldeki bilgilerden cevap cikarilabilecek yapilandirilmis icerik.",
        "answer_concealment": "Tek bir soruya odaklanan duzen YAPMA — birden fazla bilgi alani sun.",
    },
    # Bolum 2 - Anlatim
    "dusunceyi_gelistirme": {
        "text_level": "TAM_METIN",
        "hint": (
            "DGY dilsel ipuclari MUTLAKA metin olarak gorunmeli: "
            "tanimlama='...denir/dir', karsilastirma='daha/en', "
            "benzetme='gibi/sanki', orneklendirme='ornegin/mesela'."
        ),
        "answer_concealment": (
            "Gorsel DUZENI herhangi bir DGY teknigini CAGRISTIRMAMALI. "
            "Iki seyi yan yana koyma (karsilastirma belli olur), "
            "'gibi' kelimesini VURGULAMA (benzetme belli olur). "
            "Gorsel NOTR bir duzen kullanmali, cevap SADECE metindeki dilsel ipuclarindan bulunmali."
        ),
    },
    "hikaye_unsurlari": {
        "text_level": "ICERIK",
        "hint": "Yer, zaman, kisiler ve olay bilgisi gorsel sahnede NET gosterilmeli.",
        "answer_concealment": "Eksik unsuru gorsel olarak 'bos birakma' — tum alanlari dolu goster, eksiklik ICERIKTEN anlasilmali.",
    },
    "anlatici_turleri": {
        "text_level": "TAM_METIN",
        "hint": (
            "Fiil cekimleri (-dim/-dik vs -di/-lar) konusma balonlarinda AYNEN korunmali. "
            "Her karakter farkli perspektifle konusmali."
        ),
        "answer_concealment": "Karakterleri '1. kisi' / '3. kisi' diye ETIKETLEME — ogrenci fiil eklerinden cikarsin.",
    },
    "metinde_dil_ve_anlatim": {
        "text_level": "TAM_METIN",
        "hint": "Anlatim teknikleri (benzetme, kisilelestirme, ikileme, deyim) gorsel metinlerde korunmali.",
        "answer_concealment": "Teknikleri ETIKETLEME — ogrenci dilsel ipuclarindan tespit etmeli.",
    },
    "metinde_duygu": {
        "text_level": "ICERIK",
        "hint": "Duyguyu sezdiren DAVRANISLAR ve MIMIKLER gosterilmeli, duygu ismi YAZILMAMALI.",
        "answer_concealment": "Duygu ismini (uzuntu, sevinc vb.) gorselde YAZMA — davranislardan cikarilmali.",
    },
    "metinde_duyular": {
        "text_level": "ICERIK",
        "hint": "Hangi duyunun kullanildigini gosteren sahne.",
        "answer_concealment": "Duyu ismini (gorme, isitme vb.) gorselde YAZMA — gorsel ogelerden cikarilmali.",
    },
    "metinde_karakter": {
        "text_level": "ICERIK",
        "hint": "Karakterin DAVRANISLARI gorsel sahnede gosterilmeli.",
        "answer_concealment": "Karakter ozelligini (duzenli, bencil vb.) gorselde YAZMA — davranislardan cikarilmali.",
    },
    "metinler_arasi": {
        "text_level": "ICERIK",
        "hint": "IKI AYRI gorsel alan olmali, her metin icin bir bolum. Ortak ve farkli noktalar gorsel icerikten cikarilabilmeli.",
        "answer_concealment": "Farkliligi gorsel olarak VURGULAMA (farkli renk, boyut vb.) — esit gorunumde sun.",
    },
    # Bolum 3 - Yapi
    "paragraf_siralama": {
        "text_level": "TAM_METIN",
        "hint": "Her cumle ayri numarali kartta. CUMLELER TAM VE EKSIKSIZ olmali — kisaltma, ozet veya fragment YASAK.",
        "answer_concealment": "Kartlari gorsel olarak kronolojik/mantiksal SIRAYA DIZME — karisik sirala.",
    },
    "paragraf_cumle_ekleme": {
        "text_level": "TAM_METIN",
        "hint": "Paragraf gorselde tam cumleleriyle gosterilmeli, cumle eklenecek yer isaretli.",
        "answer_concealment": "Eksik yere ipucu veren gorsel oge KOYMA.",
    },
    "paragraf_metin": {
        "text_level": "TAM_METIN",
        "hint": "Giris-gelisme-sonuc yapisi gorsel olarak bolumlendirilmeli.",
        "answer_concealment": "Bolumleri 'giris/gelisme/sonuc' diye ETIKETLEME.",
    },
    # Bolum 4 - Ozel
    "yuzey_anlam": {
        "text_level": "ICERIK",
        "hint": "Cumlenin yuzey anlami gorsel olarak sunulmali.",
        "answer_concealment": "Yorumu dogrudan YAZMA — ogrenci gorsel sahneden cikarsin.",
    },
    "yuzey_derin_anlam": {
        "text_level": "ICERIK",
        "hint": "Mecazi ifadeler gorsel sahnede temsil edilmeli.",
        "answer_concealment": "Derin anlami acik yazi ile BELIRTME — gorsel metafor kullan.",
    },
    "derin_anlam": {
        "text_level": "ICERIK",
        "hint": "Mecazi/derin anlam gorsel sahneden cikarilabilmeli.",
        "answer_concealment": "Olayin dersini/mesajini dogrudan YAZMA — ogrenci gorsel olaydan cikarsin.",
    },
    "alegorik": {
        "text_level": "ICERIK",
        "hint": "Alegorik/sembolik anlam gorsel sahneden cikarilabilmeli.",
        "answer_concealment": "Sembolun anlamini aciklayan metin EKLEME.",
    },
    "elestirme_cozum": {
        "text_level": "ICERIK",
        "hint": "Problem durumu gorsel olarak sunulmali. Tum secenek cozumlerin gorselde bir karsiligi olsun.",
        "answer_concealment": "Tek bir cozumu on plana CIKARMA — problem sahnesini esit agirlikta goster.",
    },
    "cozumleme_yorumlama": {
        "text_level": "ICERIK",
        "hint": "Analiz icin gerekli bilgiler gorsel olarak sunulmali.",
        "answer_concealment": "Tek bir yorumu vurgulayan duzen YAPMA.",
    },
    "paragraf_turu": {
        "text_level": "TAM_METIN",
        "hint": "Metnin turunu belirlemeye yetecek yapisal ipuclari gorselde olmali (betimleme=duyu detaylari, oykuelme=olay akisi, vb.).",
        "answer_concealment": "Paragraf turunu ETIKETLEME veya tur ismi YAZMA.",
    },
    "metin_ici_karsilastirma": {
        "text_level": "ICERIK",
        "hint": "Karsilastirilacak ogeler gorselde sunulmali. Ortak ve farkli noktalar icerikten cikarilabilmeli.",
        "answer_concealment": "Farkliligi gorsel olarak VURGULAMA — esit gorunumde sun.",
    },
    # Bolum 6
    "sozel_mantik": {
        "text_level": "TAM_METIN",
        "hint": "Mantiksal iliskiler ve kosullar gorsel sema/tablo ile net gosterilmeli.",
        "answer_concealment": "Cevabi dogrudan gosteren ok/baglantiYAPMA.",
    },
}


def _get_template_visual_hint(template_id: str) -> dict[str, str]:
    """Get structured visual generation config for a template by prefix match."""
    for prefix, hint_data in TEMPLATE_VISUAL_HINTS.items():
        if template_id.startswith(prefix):
            return hint_data
    return {
        "text_level": "ICERIK",
        "hint": "Paragraf icerigini gorsel ogelerle aktar.",
        "answer_concealment": "",
    }


async def generate_question_visual_with_judge(
    paragraph: str,
    question: str,
    options: dict[str, str],
    correct_answer: str,
    template_id: str,
    topic: str,
    cfg: ImageGeneratorConfig,
) -> ImageGenerationResult:
    """
    Generate a question-aware visual where the question is solvable from the image alone.

    Unlike supplementary diagrams, this creates a visual that REPLACES the paragraph.
    The AI receives full question context (paragraph, question, options, correct answer)
    and chooses the best visual format (speech bubbles, poster, infographic, scene, etc.).

    A solvability judge verifies: "Can a student answer the question from the visual alone?"

    Args:
        paragraph: The paragraph content to visualize (will be hidden in output).
        question: The question stem.
        options: Dict of option labels to texts (e.g., {"A": "...", "B": "..."}).
        correct_answer: The correct option label (e.g., "A").
        template_id: Template identifier (e.g., "konu_standard") for hint lookup.
        topic: Topic string.
        cfg: Image generator configuration.

    Returns:
        ImageGenerationResult with PNG bytes if successful.
    """
    if not paragraph:
        return ImageGenerationResult(success=False, error="No paragraph provided")

    client = _get_client()
    hint_data = _get_template_visual_hint(template_id)
    template_hint = hint_data["hint"]
    text_level = hint_data["text_level"]
    answer_concealment = hint_data["answer_concealment"]

    # Build options text
    options_text = "\n".join(
        f"{label}) {text}" for label, text in sorted(options.items())
    )

    # Build text_level instruction
    text_level_instructions = {
        "TAM_METIN": (
            "CUMLELER TAM VE EKSIKSIZ olmali — kisaltma, ozet veya fragment YASAK. "
            "Konusma balonlari, metin kartlari veya numarali paneller icinde birebir ayni cumleler yer almali. "
            "Dilsel ipuclari (fiil ekleri, edatlar, deyimler) AYNEN korunmali."
        ),
        "ICERIK": (
            "Paragrafin ANLAM ICERIGI eksiksiz aktarilmali. Ifade bicimi uyarlanabilir ama bilgi kaybi OLMAMALI. "
            "TUM seceneklerin gorselde bir karsiligi olmali ki celdiriciler guclu olsun."
        ),
        "GORSEL": (
            "Illustrasyon on planda. Metin minimal etiketlerle sinirli. "
            "Gorsel sahneler ve ogeler bilgiyi aktarmali — kavram isimleri YAZILMAMALI, davranislardan cikarilmali."
        ),
    }

    base_prompt = f"""Sen egitici gorsel tasarim uzmanisin. Asagidaki soru icin ogrencinin SADECE gorselden soruyu cozebilecegi bir gorsel tasarla.

ONEMLI: Paragraf metni gizlenecek. Ogrenci YALNIZCA senin gorselini gorecek. Bu yuzden gorselde soruyu cevaplamaya yetecek TUM BILGI olmali.

== SORU BILGILERI ==
SABLON TURU: {template_id}
KONU: {topic}

PARAGRAF (bu metin gizlenecek, bilgisini gorsele aktar):
\"\"\"{paragraph}\"\"\"

SORU KOKU:
{question}

SECENEKLER:
{options_text}

DOGRU CEVAP: {correct_answer}

== GORSEL FORMAT SECIMI ==
Asagidaki formatlardan soruya EN UYGUN olani SEC. Her soru icin farkli format secebilirsin:

1. KONUSMA BALONLU SAHNE: Karakterler konusma balonlarinda metin soyluyorlar.
2. POSTER/AFIS: Dikkat cekici baslik + kisa bilgi maddeleri + gorsel ogeler.
3. INFOGRAFIK: Kategorilere ayrilmis veri, surec diyagrami, akis semasi.
4. TABLO/LISTE: Yapilandirilmis bilgi tabloda veya listeyle sunulur.
5. SAHNE ILLUSTRASYONU: Bir olayi/durumu gosteren cizim + kisa metin etiketleri.
6. NUMARALI KART DIZISI: Her biri numarali kart icinde tam metin parcasi.
7. GAZETE/DERGI SAYFASI: Baslik + sutunlar + gorsel, gazete formati.
8. AKIS SEMASI: Kutular ve oklar ile surec veya mantik akisi.

== SABLON OZEL KURAL ==
{template_hint}

== METIN KORUMA SEVIYESI: {text_level} ==
{text_level_instructions.get(text_level, text_level_instructions["ICERIK"])}

== CEVAP GIZLEME KURALI (KRITIK) ==
{answer_concealment}

GENEL PRENSIP: Gorselin DUZENI/FORMATI/YAPISI tek basina dogru cevabi ELE VERMEMELI.
Cevap yalnizca gorselin ICERIGI okunarak/yorumlanarak bulunabilmeli.

YAPISAL SIZINTI KALIPLARI (bunlardan KACIN):
1. Iki panelli yan yana duzen + seceneklerde "karsilastirma" varsa → SIZINTI
2. Sirali/kronolojik gorsel duzen + siralama sorusu → SIZINTI
3. Eksik/bos gorsel alani + "yoktur/kullanilmamistir" tipi secenek → SIZINTI
4. Tek vurgulu/merkezi oge + "ana/asil/en onemli" tipi secenek → SIZINTI
5. Duygu/karakter/kavram ismi dogrudan gorselde yazili → SIZINTI
6. Panel/kart sayisi = dogru cevaptaki oge sayisi → SIZINTI

== KRITIK KURALLAR ==
1. BEYAZ veya ACIK RENK ARKA PLAN
2. TUM METINLER TURKCE — Ingilizce YASAK
3. Gorseldeki metin OKUNAKLI ve NET olmali (kucuk boyutta bile)
4. Soruyu cevaplamak icin GEREKLI TUM BILGIYI gorsele yerlestir
5. Dogru cevabi DOGRUDAN VERME ama dogru cevaba ulasmak icin yeterli ipucunu koy
6. Renkli, profesyonel, sinav kitabi kalitesinde
7. 5. sinif ogrencisine uygun, sade ve anlasilir
8. Gorsel BASLIGI notr olmali — cevabi, konuyu veya anahtar kavrami dogrudan yazan baslik YASAK. Ornek: "Civi Yazisinin Kil Tabletlerdeki Izleri" yerine "Eski Bir Yazinin Seruveni" gibi notr baslik kullan.
9. NUMARALI KARTLAR/PANELLER okuma sirasina gore dizilmeli: I/1 sol ust, II/2 sag ust, III/3 sol alt, IV/4 sag alt (veya ustten alta satirsal sira). Numaralar ASLA karisik konumda OLMAMALI.

KESINLIKLE YAPMA:
- Soru kokunu gorselde gosterme
- Secenekleri (A, B, C, D) gorselde gosterme
- Dogru cevabi dogrudan yazan ifade kullanma
- Sadece duz metin blogu olusturma — GORSEL OGELER sart
- Gorselin yapisal duzeni ile dogru cevap arasinda ilinti kurmak (CEVAP SIZINTISI)
- Cumlecikleri kisaltmak veya ozetlemek (TAM_METIN seviyesinde tam cumle SART)

NOT: Soru kokunde "Bu metinde" veya "metnin" gibi ifadeler olabilir.
Ogrenciye gosterilecek soruda bunlar otomatik olarak "Bu gorselde" / "gorselin" ile degistirilecek.
Sen gorseli tasarlarken bunu dikkate al — ogrenci "Bu GORSELDE ... hangisinden bahsedilmektedir?" seklinde gorecek."""

    # Replace metin references in question for judge prompt too
    from agentic.generic_workflow import _replace_metin_with_gorsel
    _visual_question = _replace_metin_with_gorsel(question)

    judge_prompt_template = f"""Sen bir egitim icerik denetcisisin. Asagidaki soru icin ogrencinin SADECE gorseli gorecegini varsay (paragraf metni gizlenecek). Gorselden soruyu dogru cevaplayabilir mi?

SORU (ogrencinin gorecegi hali):
{_visual_question}

SECENEKLER:
{options_text}

DOGRU CEVAP: {correct_answer}
METIN KORUMA SEVIYESI: {text_level}

KONTROL LISTESI:
1. BILGI YETERLILIGI: Gorselde soruyu cevaplamak icin yeterli bilgi var mi?
   - Eger DGY/anlatici/dil sorusu ise: Dilsel ipuclari (fiil ekleri, edatlar) goruluyor mu?
   - Eger icerik sorusu ise: Konu/fikir gorsellerden anlasilabiliyor mu?
   - Eger siralama sorusu ise: Tum cumleler/ogeler goruluyor mu?

2. OKUNAKLILIK: Gorseldeki metinler (varsa) okunakli mi? Kucuk boyutta bile okunabilir mi?

3. YANILTICI DEGIL: Gorsel dogru cevabi DOGRUDAN vermiyor mu? (vermemeli — ipucu yeterli)

4. GORSEL KALITE: Profesyonel ve sinav kitabi kalitesinde mi?

5. TURKCE: Tum metinler Turkce mi? Ingilizce kelime var mi?

6. CEVAP SIZINTISI: Gorselin DUZENI/FORMATI tek basina cevabi belli ediyor mu?
   - Soru kokunu oku, seceneklere bak, sonra SADECE gorselin YAPISINA (icerigine DEGIL) bak.
   - Gorsel yapisi (iki panel, kart sayisi, renk kodlamasi, vurgu, boyut farki) cevabi ele veriyor mu?
   - Ornek: Iki seyi yan yana koymak + seceneklerde "karsilastirma" varsa → SIZINTI
   - Ornek: Duygu ismi dogrudan gorselde yaziliysa → SIZINTI
   - Eger gorsel FORMATI ile cevap tahmin edilebiliyorsa: REDDET

7. METIN BUTUNLUGU: Metin koruma seviyesi "{text_level}" ise:
   - TAM_METIN: Her cumle/ifade TAM ve EKSIKSIZ gorunuyor mu? Kisaltma veya fragment var mi? Varsa REDDET.
   - ICERIK: Paragrafin tum bilgi noktalari gorselde mevcut mu? Bilgi kaybi var mi?
   - GORSEL: Gorsel ogeler yeterli mi?

KARAR:
- Eger ogrenci gorselden soruyu dogru cevaplayabilir ve CEVAP SIZINTISI YOKSA: "KABUL"
- Eger bilgi yetersiz, okunamaz, cevap sizintisi var veya metin butunlugu bozuksa: "REDDET: [sorunu acikla]"

Cevabini "KABUL" veya "REDDET: [neden]" formatinda ver."""

    best_image: bytes | None = None
    rejection_feedback = ""

    for iteration in range(cfg.max_judge_iterations):
        logger.info(f"[VISUAL] Iteration {iteration + 1}/{cfg.max_judge_iterations}")

        try:
            # Build prompt with rejection feedback if available
            current_prompt = base_prompt
            if rejection_feedback:
                current_prompt += (
                    f"\n\nONCEKI DENEMEDE SORUN: {rejection_feedback}\n"
                    f"Bu sorunu coz ve gorseli iyilestir."
                )

            # Generate image
            png_bytes = None
            for attempt in range(cfg.max_retries + 1):
                try:
                    response = await client.aio.models.generate_content(
                        model=cfg.model,
                        contents=current_prompt,
                        config=types.GenerateContentConfig(
                            temperature=cfg.temperature,
                        ),
                    )

                    if response.candidates and response.candidates[0].content:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, "inline_data") and part.inline_data:
                                if part.inline_data.data:
                                    png_bytes = part.inline_data.data
                                    if isinstance(png_bytes, str):
                                        png_bytes = base64.b64decode(png_bytes)
                                    break

                    if png_bytes:
                        png_bytes = _ensure_png_bytes(png_bytes)
                        logger.info(f"[VISUAL] Generated {len(png_bytes)} bytes")
                        break

                    logger.warning("[VISUAL] No image in response")

                except Exception as e:
                    logger.warning(f"[VISUAL] Attempt {attempt + 1} failed: {e}")

            if not png_bytes:
                continue

            best_image = png_bytes

            # Judge: solvability check
            png_base64 = base64.b64encode(png_bytes).decode("utf-8")

            try:
                judge_response = await client.aio.models.generate_content(
                    model=cfg.judge_model,
                    contents=[
                        types.Content(
                            parts=[
                                types.Part(text=judge_prompt_template),
                                types.Part(
                                    inline_data=types.Blob(
                                        mime_type="image/png",
                                        data=png_bytes,
                                    )
                                ),
                            ]
                        )
                    ],
                )

                result_text = str(judge_response.text).upper()

                if "KABUL" in result_text:
                    logger.info("[VISUAL] Judge approved — solvability confirmed")
                    return ImageGenerationResult(
                        success=True,
                        png_bytes=png_bytes,
                        png_base64=png_base64,
                        judge_iterations=iteration + 1,
                    )

                # Extract rejection reason for feedback loop
                reject_text = str(judge_response.text)
                if "REDDET" in reject_text.upper():
                    rejection_feedback = reject_text.split(":", 1)[-1].strip() if ":" in reject_text else reject_text
                else:
                    rejection_feedback = reject_text

                logger.info(f"[VISUAL] Judge rejected: {reject_text}")

            except Exception as e:
                logger.warning(f"[VISUAL JUDGE] Failed: {e}")
                # Accept image if judge fails (graceful fallback)
                return ImageGenerationResult(
                    success=True,
                    png_bytes=png_bytes,
                    png_base64=png_base64,
                    judge_iterations=iteration + 1,
                )

        except Exception as e:
            logger.error(f"[VISUAL] Iteration {iteration + 1} failed: {e}")

    # Return best image even if not perfect
    if best_image:
        png_base64 = base64.b64encode(best_image).decode("utf-8")
        return ImageGenerationResult(
            success=True,
            png_bytes=best_image,
            png_base64=png_base64,
            judge_iterations=cfg.max_judge_iterations,
        )

    return ImageGenerationResult(
        success=False,
        error="Question visual generation failed after all iterations",
        judge_iterations=cfg.max_judge_iterations,
    )


# ============================================================================
# OPTION IMAGE GENERATION (gorsel_siklar templates)
# ============================================================================


async def generate_option_images_grid(
    options: dict[str, str],
    image_style: str,
    cfg: ImageGeneratorConfig,
    shared_visual_format: str = "",
) -> dict[str, ImageGenerationResult]:
    """Dispatch option image generation based on image_style.

    - photo: Gemini image model (2x2 grid + per-quadrant judge)
    - table: Programmatic HTML render (parse text → build table)
    - chart: Programmatic render (LLM extracts data → Python builds chart)
    - mockup: Programmatic render (LLM extracts data → Python builds device UI)
    - other: Fallback to LLM HTML generation
    """
    labels = sorted(options.keys())[:4]
    if len(labels) < 3:
        return {l: ImageGenerationResult(success=False, error="Need at least 3 options") for l in labels}

    if image_style == "photo":
        return await _generate_photo_grid_with_judge(options, cfg, shared_visual_format)
    elif image_style == "table":
        return await _render_table_with_judge(options, cfg, shared_visual_format)
    elif image_style == "chart":
        return await _render_chart_programmatic(options, cfg, shared_visual_format)
    elif image_style == "mockup":
        return await _render_mockup_programmatic(options, cfg, shared_visual_format)
    else:
        # Fallback for future styles
        return await _render_via_llm_with_judge(options, shared_visual_format, image_style, cfg)


# ---- Photo: Gemini 2x2 grid + judge ----

async def _generate_photo_grid_with_judge(
    options: dict[str, str],
    cfg: ImageGeneratorConfig,
    shared_visual_format: str = "",
) -> dict[str, ImageGenerationResult]:
    """Generate photo options via Gemini 2x2 grid, with judge quality loop."""
    labels = sorted(options.keys())[:4]
    n = len(labels)

    if shared_visual_format:
        format_section = (
            f"## ORTAK GORSEL FORMAT ({n} gorsel BIREBIR AYNI formatta olacak)\n"
            f"{shared_visual_format}\n\n"
            f"## SADECE VERILER FARKLI — her karede asagidaki verileri goster:"
        )
    else:
        format_section = (
            f"## {n} gorsel AYNI STIL, AYNI RENK PALETI, AYNI FONT, AYNI LAYOUT ile cizilmeli.\n"
            "## Sadece VERILER/ICERIK farkli:"
        )

    options_lines = "\n\n".join(f"{i+1}) {options[labels[i]]}" for i in range(n))

    if n == 3:
        layout_instruction = (
            f"TEK bir resimde 1x3 grid halinde 3 gorsel ciz. 3 gorsel birbirine YAPISIK olmali.\n\n"
            f"Yerlesim: Sol = 1, Orta = 2, Sag = 3"
        )
    else:
        layout_instruction = (
            f"TEK bir resimde 2x2 grid halinde 4 gorsel ciz. 4 gorsel birbirine YAPISIK olmali.\n\n"
            f"Yerlesim: Sol ust = 1, Sag ust = 2, Sol alt = 3, Sag alt = 4"
        )

    prompt = f"""{layout_instruction}

{format_section}

{options_lines}

KRITIK KURALLAR:
1. BEYAZ ARKA PLAN
2. Her kare ESIT BOYUTTA
3. {n} gorsel BIREBIR AYNI FORMATTA — sadece veriler/icerik farkli
4. SADECE GORSEL — metin/yazi/etiket EKLEME
5. Renkli, net, sinav kitabi kalitesinde
6. Tasvirdeki nesne/canli/kavram NET GORUNMELI

KESINLIKLE YAPMA (COK ONEMLI):
- Harf/numara/etiket YAZMA (A, B, C, D veya 1, 2, 3, 4 YAZMA)
- Kareler arasina cizgi, border, frame, ayirici KOYMA
- Gorsellerin etrafina cerceve, kutu, outline CIZME
- {n} gorseli BIRBIRINDEN AYIRAN hicbir gorsel oge EKLEME
Sadece {n} gorseli yan yana{"" if n == 3 else " ve alt alta"}, ARALIK BIRAKMADAN, ETIKET KOYMADAN ciz."""

    client = _get_client()
    best_results: dict[str, ImageGenerationResult] | None = None

    for iteration in range(cfg.max_judge_iterations):
        logger.info(f"[PHOTO_GRID] Iteration {iteration + 1}/{cfg.max_judge_iterations}")

        # Generate grid
        png_bytes = None
        for attempt in range(cfg.max_retries + 1):
            try:
                response = await client.aio.models.generate_content(
                    model=cfg.model,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=cfg.temperature),
                )
                png_bytes = _extract_image_bytes(response)
                if png_bytes:
                    png_bytes = _ensure_png_bytes(png_bytes)
                    break
                logger.warning(f"[PHOTO_GRID] No image (attempt {attempt + 1})")
            except Exception as e:
                logger.warning(f"[PHOTO_GRID] Attempt {attempt + 1} failed: {e}")

        if not png_bytes:
            continue

        # Crop into individual images
        from PIL import Image, ImageOps
        img = Image.open(BytesIO(png_bytes))
        w, h = img.size

        if n == 3:
            # 1x3 horizontal strip
            third = w // 3
            boxes = {
                labels[0]: (0, 0, third, h),
                labels[1]: (third, 0, 2 * third, h),
                labels[2]: (2 * third, 0, w, h),
            }
        else:
            # 2x2 grid
            mid_x, mid_y = w // 2, h // 2
            boxes = {
                labels[0]: (0, 0, mid_x, mid_y),
                labels[1]: (mid_x, 0, w, mid_y),
                labels[2]: (0, mid_y, mid_x, h),
                labels[3]: (mid_x, mid_y, w, h),
            }

        results: dict[str, ImageGenerationResult] = {}
        # All quadrants are already same size from the grid crop (mid_x × mid_y)
        # Just use them directly — no trim/normalize needed for consistent sizing
        for label, box in boxes.items():
            quad = img.crop(box)
            buf = BytesIO()
            quad.save(buf, format="PNG")
            qb = buf.getvalue()
            results[label] = ImageGenerationResult(
                success=True, png_bytes=qb,
                png_base64=base64.b64encode(qb).decode("utf-8"),
                judge_iterations=iteration + 1,
            )

        best_results = results
        logger.info(f"[PHOTO_GRID] Generated {w}x{h} grid, cropped into {n}")

        # Judge: send all PNGs together for comprehensive check
        label_str = ", ".join(labels)
        try:
            judge_parts = [
                types.Part(text=(
                    f"Bu {n} gorsel bir sinav sorusunun {label_str} siklaridir.\n"
                    f"{n} gorsel AYNI GENEL KATEGORI icinde olmali (ornek: hepsi kelebek, hepsi yanardag).\n"
                    "Farklar DETAYLARDA olmali (renk deseni, sekil, boyut, yapi).\n\n"
                    "KONTROL:\n"
                    "1. Her karede TEK BIR nesne/canli var mi? (Birden fazla varsa REDDET)\n"
                    f"2. {n} gorsel birbirinden GORSEL OLARAK ayirt edilebilir mi?\n"
                    "   - Farkli renk, farkli sekil/form, farkli detaylar olmali\n"
                    "   - Hepsi AYNI KATEGORI ama FARKLI VARYANT/ALT TUR olmali — bu DOGRU\n"
                    f"   - {n} gorsel NEREDEYSE AYNI gorunuyorsa (sadece cok kucuk farklar) → REDDET\n"
                    f"3. Gorsellerde NUMARA veya ETIKET (1,2,3,4 veya A,B,C,D) var mi? Varsa REDDET\n"
                    "4. Nesneler tam gorunuyor mu, kesilmis mi?\n\n"
                    'Hepsi iyi ise: "KABUL"\n'
                    'Sorun varsa: "REDDET: [neden]"'
                ))
            ]
            for label in labels:
                if label in results and results[label].png_bytes:
                    judge_parts.append(
                        types.Part(inline_data=types.Blob(
                            mime_type="image/png", data=results[label].png_bytes,
                        ))
                    )

            judge_response = await client.aio.models.generate_content(
                model=cfg.judge_model,
                contents=[types.Content(parts=judge_parts)],
            )
            result_text = str(judge_response.text).upper()
            if "KABUL" in result_text:
                logger.info("[PHOTO_GRID] Judge approved all quadrants")
                return results
            logger.info(f"[PHOTO_GRID] Judge rejected: {judge_response.text}")
        except Exception as e:
            logger.warning(f"[PHOTO_GRID] Judge failed: {e}")
            return results  # accept if judge fails

    return best_results or {l: ImageGenerationResult(success=False, error="Photo grid failed") for l in labels}


async def _render_html_map_to_pngs(
    html_map: dict[str, str],
    viewport_width: int = 500,
    tag: str = "RENDER",
) -> dict[str, ImageGenerationResult]:
    """Shared Playwright renderer: takes a dict of {label: full_html} and returns PNG results.

    Used by table, chart, and mockup programmatic renderers to avoid code duplication.
    """
    from playwright.async_api import async_playwright

    results: dict[str, ImageGenerationResult] = {}
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        for label, html in html_map.items():
            page = await browser.new_page(viewport={"width": viewport_width, "height": 600})
            await page.set_content(html, wait_until="networkidle")
            box = await page.evaluate(
                "() => { const b = document.body; return {w: b.scrollWidth, h: b.scrollHeight}; }"
            )
            await page.set_viewport_size({"width": box["w"] + 4, "height": box["h"] + 4})
            png_bytes = await page.screenshot(type="png", full_page=True)
            await page.close()

            results[label] = ImageGenerationResult(
                success=True,
                png_bytes=png_bytes,
                png_base64=base64.b64encode(png_bytes).decode("utf-8"),
            )
            logger.info(f"[{tag}] Rendered {label}: {len(png_bytes)} bytes")

        await browser.close()

    logger.info(f"[{tag}] Rendered {len(results)}/{len(html_map)} images")
    return results


# ---- Chart: matplotlib ----

# ---- Unified LLM HTML Renderer + Judge/Fixer (chart, table, mockup) ----


async def _render_via_llm_with_judge(
    options: dict[str, str],
    shared_visual_format: str,
    image_style: str,
    cfg: ImageGeneratorConfig,
) -> dict[str, ImageGenerationResult]:
    """Unified pipeline: LLM generates HTML/CSS → Playwright screenshots → Judge checks → Fixer retries.

    Works for chart, table, and mockup styles. The LLM adapts to any visual type.
    Judge ensures 4 options have identical format/layout/colors/fonts.
    """
    from pydantic import BaseModel, Field
    import json

    labels = sorted(options.keys())[:4]
    client = _get_client()

    n = len(labels)

    class OptionHTMLOutput(BaseModel):
        html_a: str = Field(description="Complete HTML/CSS for option A")
        html_b: str = Field(description="Complete HTML/CSS for option B")
        html_c: str = Field(description="Complete HTML/CSS for option C")
        html_d: str | None = Field(default=None, description="Complete HTML/CSS for option D (4 secenekli ise)")

    options_text = "\n".join(f"{l}) {options[l]}" for l in labels)
    field_list = "html_a, html_b, html_c" + (", html_d" if n >= 4 else "")

    base_prompt = f"""GOREV: {n} sik icin AYNI STILDE HTML/CSS gorsel kodu uret.

GORSEL TIPI: {image_style}
GORSEL TANIMI: {shared_visual_format}

{n} SIK VERISI:
{options_text}

KURALLAR:
1. Her sik icin AYRI bir HTML snippet uret ({field_list})
2. {n} snippet BIREBIR AYNI CSS, AYNI LAYOUT, AYNI FONT, AYNI RENKLER, AYNI BOYUT
3. SADECE veriler/icerik farkli — gorunum TAMAMEN AYNI
4. Gorsel tipine uygun tasarim:
   - chart: bar/cizgi/pasta grafik (SVG veya CSS ile, veriye uygun tip sec)
   - table: satirli/sutunlu tablo (net border, kalin baslik)
   - mockup: cihaz/ekran/arayuz (baglamina uygun cerceve)
5. Sinav kitabi kalitesinde, temiz, sade, profesyonel
6. Beyaz arka plan uzerinde
7. Inline CSS kullan (external stylesheet YASAK)
8. Genislik en fazla 250px — bu dar alanda OKUNAKLI olmali
9. OKUNABILIRLIK BIRINCI ONCELIK: font en az 12px, metin kesilmemeli, tum icerik rahatca okunmali
10. Turkce karakterler dogru gorunmeli (UTF-8)
11. Her snippet BAGIMSIZ calismali"""

    best_results: dict[str, ImageGenerationResult] | None = None
    last_judge_feedback = ""

    for iteration in range(cfg.max_judge_iterations):
        logger.info(f"[{image_style.upper()}] Iteration {iteration + 1}/{cfg.max_judge_iterations}")

        # Step 1: LLM generates HTML for all 4 options
        feedback_section = ""
        if iteration > 0 and last_judge_feedback:
            feedback_section = f"\n\nONCEKI DENEME GERI BILDIRIMI:\n{last_judge_feedback}\nBu sorunlari DUZELT!"

        try:
            output = await client.aio.models.generate_content(
                model=cfg.judge_model,
                contents=base_prompt + feedback_section,
                config=types.GenerateContentConfig(
                    temperature=0.2,
                    response_mime_type="application/json",
                    response_schema=OptionHTMLOutput,
                ),
            )

            if not (hasattr(output, 'text') and output.text):
                raise ValueError("No text in LLM response")

            data = json.loads(output.text)
            field_keys = ["html_a", "html_b", "html_c", "html_d"]
            html_map = {}
            for i, label in enumerate(labels):
                val = data.get(field_keys[i], "")
                if val and val.strip():
                    html_map[label] = val

            if len(html_map) < n:
                logger.warning(f"[{image_style.upper()}] LLM returned {len(html_map)}/{n} HTML snippets")
                if not html_map:
                    continue

        except Exception as e:
            logger.error(f"[{image_style.upper()}] LLM HTML generation failed: {e}")
            continue

        # Step 2: Playwright renders all 4 HTML → PNG
        from playwright.async_api import async_playwright

        results: dict[str, ImageGenerationResult] = {}
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                for label, html in html_map.items():
                    full_html = (
                        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
                        f'<style>body{{margin:0;padding:8px;background:white;display:inline-block;}}</style>'
                        f'</head><body>{html}</body></html>'
                    )
                    page = await browser.new_page(viewport={"width": 300, "height": 600})
                    await page.set_content(full_html, wait_until="networkidle")
                    box = await page.evaluate(
                        "() => { const b = document.body; return {w: b.scrollWidth, h: b.scrollHeight}; }"
                    )
                    await page.set_viewport_size({"width": box["w"] + 4, "height": box["h"] + 4})
                    png_bytes = await page.screenshot(type="png", full_page=True)
                    await page.close()

                    results[label] = ImageGenerationResult(
                        success=True, png_bytes=png_bytes,
                        png_base64=base64.b64encode(png_bytes).decode("utf-8"),
                        judge_iterations=iteration + 1,
                    )
                await browser.close()
        except Exception as e:
            logger.error(f"[{image_style.upper()}] Playwright rendering failed: {e}")
            continue

        best_results = results

        # Step 3: Judge — send all PNGs together for consistency check
        label_str = ", ".join(labels)
        try:
            judge_parts = [
                types.Part(text=(
                    f"Bu {n} gorsel bir sinav sorusunun {label_str} siklaridir.\n\n"
                    "KONTROL (hepsine EVET olmali):\n"
                    f"1. FORMAT TUTARLILIGI: {n} gorsel birebir ayni layout/yapi mi?\n"
                    "2. RENK TUTARLILIGI: Ayni renk paleti, ayni arka plan mi?\n"
                    "3. FONT TUTARLILIGI: Ayni font ailesi, ayni boyutlar mi?\n"
                    f"4. BOYUT UYUMU: {n} gorsel yaklasik ayni genislik ve yukseklikte mi?\n"
                    "5. TASMA/OVERFLOW: Metin veya oge kutunun disina tasiyor mu?\n"
                    "6. OKUNABILIRLIK: Tum metinler net okunabiliyor mu?\n"
                    "7. PROFESYONELLIK: Sinav kitabi kalitesinde mi?\n\n"
                    'Hepsi iyi ise: "KABUL"\n'
                    'Sorun varsa: "REDDET: [hangi sikta ne sorun var, detayli]"'
                ))
            ]
            for label in labels:
                if label in results and results[label].png_bytes:
                    judge_parts.append(
                        types.Part(inline_data=types.Blob(
                            mime_type="image/png", data=results[label].png_bytes,
                        ))
                    )

            judge_response = await client.aio.models.generate_content(
                model=cfg.judge_model,
                contents=[types.Content(parts=judge_parts)],
            )

            result_text = str(judge_response.text).upper()
            if "KABUL" in result_text:
                logger.info(f"[{image_style.upper()}] Judge approved all options")
                return results

            # Judge rejected — store feedback for fixer
            feedback = judge_response.text or "Stil tutarsizligi"
            last_judge_feedback = feedback
            logger.info(f"[{image_style.upper()}] Judge rejected: {feedback}")

        except Exception as e:
            logger.warning(f"[{image_style.upper()}] Judge failed: {e}")
            return results  # Accept if judge fails

    # Return best results after all iterations
    if best_results:
        logger.info(f"[{image_style.upper()}] Returning best result after {cfg.max_judge_iterations} iterations")
        return best_results

    return {l: ImageGenerationResult(success=False, error="LLM HTML rendering failed") for l in labels}



# ---- Table: Programmatic data-driven render ----

def _build_table_html(data: dict[str, str]) -> str:
    """Build a readable 2-column key-value HTML table."""
    rows = ""
    for key, value in data.items():
        rows += (
            f'<tr>'
            f'<td style="border:2px solid #444;padding:14px 20px;font-weight:bold;'
            f'background:#f0f0f0;white-space:nowrap;font-size:20px;">{key}</td>'
            f'<td style="border:2px solid #444;padding:14px 20px;font-size:20px;'
            f'max-width:300px;word-wrap:break-word;">{value}</td>'
            f'</tr>'
        )
    return (
        f'<table style="border-collapse:collapse;font-family:Arial,Helvetica,sans-serif;'
        f'margin:8px;">{rows}</table>'
    )


async def _render_table_with_judge(
    options: dict[str, str],
    cfg: ImageGeneratorConfig,
    shared_visual_format: str = "",
) -> dict[str, ImageGenerationResult]:
    """Extract structured table data from option texts via LLM, then render programmatically.

    Flow: LLM extracts headers + cell values → Python builds table HTML → Playwright screenshots.
    Same pattern as chart and mockup — no free-text parsing needed.
    """
    from pydantic import BaseModel, Field
    import json

    labels = sorted(options.keys())[:4]
    client = _get_client()

    class TableRenderData(BaseModel):
        headers: list[str] = Field(description="Tablo sutun/satir basliklari (ornek: ['Yer','Zaman','Olay','Kisi'])")
        values_a: list[str] = Field(description="A sikki icin her basliga karsilik gelen degerler")
        values_b: list[str] = Field(description="B sikki icin degerler")
        values_c: list[str] = Field(description="C sikki icin degerler")
        values_d: list[str] | None = Field(default=None, description="D sikki icin degerler (4 secenekli ise)")

    n = len(labels)
    options_text = "\n".join(f"{l}) {options[l]}" for l in labels)

    prompt = f"""Asagidaki {n} tablo secenegi icin YAPISAL VERI cikar.

GORSEL TANIMI: {shared_visual_format}

{n} SECENEK:
{options_text}

KURALLAR:
1. headers: Tum seceneklerde ORTAK olan kategori/baslik isimlerini cikar (ornek: Yer, Zaman, Olay, Kisi)
2. Her secenek icin headers ile AYNI SIRADA ve AYNI SAYIDA deger yaz
3. Degerleri secenekten OLDUGU GIBI al — kisaltma, degistirme, birlestirme YASAK
4. Her secenegin KENDINE OZGU degerlerini yaz — baska secenekten KOPYALAMA
{f"5. values_d BIRAKILABILIR — sadece {n} secenegin verisini cikar" if n < 4 else ""}
"""

    try:
        response = await client.aio.models.generate_content(
            model=cfg.judge_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=TableRenderData,
            ),
        )

        data = TableRenderData.model_validate_json(response.text)
        logger.info(f"[TABLE] Extracted headers: {data.headers}")

    except Exception as e:
        logger.error(f"[TABLE] Data extraction failed: {e}")
        return {l: ImageGenerationResult(success=False, error=f"Table data extraction failed: {e}") for l in labels}

    # Build table HTMLs from structured data
    value_sets = {
        labels[0]: data.values_a,
        labels[1]: data.values_b,
        labels[2]: data.values_c,
    }
    if n >= 4 and data.values_d is not None:
        value_sets[labels[3]] = data.values_d

    html_map = {}
    for label, values in value_sets.items():
        table_dict = dict(zip(data.headers, values))
        html_body = _build_table_html(table_dict)
        html_map[label] = (
            f'<!DOCTYPE html><html><head><meta charset="utf-8">'
            f'<style>body{{margin:0;padding:0;background:white;display:inline-block;}}</style>'
            f'</head><body>{html_body}</body></html>'
        )

    return await _render_html_map_to_pngs(html_map, viewport_width=500, tag="TABLE")


def _extract_image_bytes(response) -> bytes | None:
    """Extract PNG bytes from a Gemini generate_content response."""
    if response.candidates and response.candidates[0].content:
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                if part.inline_data.data:
                    data = part.inline_data.data
                    if isinstance(data, str):
                        return base64.b64decode(data)
                    return data
    return None


# ============================================================================
# PROGRAMMATIC CHART RENDERER
# ============================================================================

_CHART_CSS = """
body { margin: 0; padding: 0; background: white; font-family: Arial, Helvetica, sans-serif; }
.chart { width: 560px; padding: 20px; background: white; }
.chart-title { font-size: 22px; font-weight: bold; text-align: center; margin-bottom: 16px; color: #333; }
.chart-area { display: flex; align-items: flex-end; justify-content: center; gap: 20px; height: 280px;
              border-left: 2px solid #555; border-bottom: 2px solid #555; padding: 0 16px 0 20px; }
.bar-col { display: flex; flex-direction: column; align-items: center; flex: 1; height: 100%;
           justify-content: flex-end; min-width: 0; }
.bar-value { font-size: 18px; font-weight: bold; margin-bottom: 4px; color: #333; white-space: nowrap; }
.bar { width: 60px; border-radius: 4px 4px 0 0; min-height: 4px; }
.bar-label { font-size: 17px; color: #555; margin-top: 6px; text-align: center; }
"""

_DEFAULT_CHART_COLORS = ["#4472C4", "#ED7D31", "#A5A5A5", "#FFC000", "#5B9BD5", "#70AD47"]


def _build_bar_chart_html(
    title: str,
    categories: list[str],
    values: list[float],
    unit: str = "",
) -> str:
    """Build a deterministic bar chart HTML from structured data."""
    colors = _DEFAULT_CHART_COLORS
    max_val = max(values) if values else 1
    if max_val <= 0:
        max_val = 1

    bars = ""
    for i, (cat, val) in enumerate(zip(categories, values)):
        height_pct = max((val / max_val) * 100, 2)  # min 2% so zero bars are visible
        color = colors[i % len(colors)]
        display_val = f"{val:g}" if val == int(val) else f"{val}"
        bars += (
            f'<div class="bar-col">'
            f'<div class="bar-value">{display_val}{unit}</div>'
            f'<div class="bar" style="height:{height_pct:.0f}%;background:{color}"></div>'
            f'<div class="bar-label">{cat}</div>'
            f'</div>'
        )

    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<style>{_CHART_CSS}</style></head><body>'
        f'<div class="chart"><div class="chart-title">{title}</div>'
        f'<div class="chart-area">{bars}</div></div></body></html>'
    )


async def _render_chart_programmatic(
    options: dict[str, str],
    cfg: ImageGeneratorConfig,
    shared_visual_format: str = "",
) -> dict[str, ImageGenerationResult]:
    """Extract structured chart data from option texts via LLM, then render programmatically.

    Flow: LLM extracts numbers/categories → Python builds bar chart HTML → Playwright screenshots.
    No HTML-in-JSON → no parse failures. Deterministic rendering → perfect consistency.
    """
    from pydantic import BaseModel, Field
    import json

    labels = sorted(options.keys())[:4]
    client = _get_client()

    class ChartRenderData(BaseModel):
        title: str = Field(description="Grafik basligi")
        unit: str = Field(description="Deger birimi (ornek: ° veya kisi veya kg). Bos string ise birim yok")
        categories: list[str] = Field(description="Kategori isimleri (cubuk etiketleri)")
        values_a: list[float] = Field(description="A sikki icin sayisal degerler")
        values_b: list[float] = Field(description="B sikki icin sayisal degerler")
        values_c: list[float] = Field(description="C sikki icin sayisal degerler")
        values_d: list[float] | None = Field(default=None, description="D sikki icin sayisal degerler (4 secenekli ise)")

    n = len(labels)
    options_text = "\n".join(f"{l}) {options[l]}" for l in labels)

    prompt = f"""Asagidaki {n} grafik secenegi icin YAPISAL VERI cikar.

GORSEL TANIMI: {shared_visual_format}

{n} SECENEK:
{options_text}

KURALLAR:
1. Her secenekteki SAYISAL DEGERLERI cikar
2. Kategoriler (cubuk isimleri) tum seceneklerde AYNI olmali
3. Sadece degerler farkli olmali
4. unit: eger degerler derece ise "°", kisi ise " kisi", bos ise ""
{f"5. values_d BIRAKILABILIR — sadece {n} secenegin verisini cikar" if n < 4 else ""}
"""

    try:
        response = await client.aio.models.generate_content(
            model=cfg.judge_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=ChartRenderData,
            ),
        )

        data = ChartRenderData.model_validate_json(response.text)
        logger.info(f"[CHART] Extracted data: {data.title}, {len(data.categories)} categories")

    except Exception as e:
        logger.error(f"[CHART] Data extraction failed: {e}")
        return {l: ImageGenerationResult(success=False, error=f"Chart data extraction failed: {e}") for l in labels}

    # Build chart HTMLs
    value_sets = {
        labels[0]: data.values_a,
        labels[1]: data.values_b,
        labels[2]: data.values_c,
    }
    if n >= 4 and data.values_d is not None:
        value_sets[labels[3]] = data.values_d

    html_map = {
        label: _build_bar_chart_html(title=data.title, categories=data.categories, values=values, unit=data.unit)
        for label, values in value_sets.items()
    }

    return await _render_html_map_to_pngs(html_map, viewport_width=620, tag="CHART")


# ============================================================================
# PROGRAMMATIC MOCKUP RENDERER
# ============================================================================

_MOCKUP_CSS_WATCH = """
body { margin: 0; padding: 0; background: white; font-family: Arial, Helvetica, sans-serif; }
.watch { width: 300px; background: #1a1a2e; border-radius: 32px; padding: 28px 24px;
         color: white; text-align: center; }
.watch-title { font-size: 16px; color: #ccc; text-transform: uppercase; letter-spacing: 1px;
               margin-bottom: 18px; }
.watch-value { font-size: 56px; font-weight: bold; margin-bottom: 6px; }
.watch-value-unit { font-size: 22px; font-weight: normal; color: #aaa; }
.watch-sub { font-size: 15px; color: #999; margin-bottom: 14px; }
.watch-diff { font-size: 17px; font-weight: bold; margin-bottom: 10px; }
.watch-icon { font-size: 24px; }
"""

_MOCKUP_CSS_PHONE = """
body { margin: 0; padding: 0; background: white; font-family: Arial, Helvetica, sans-serif; }
.phone { width: 320px; background: #f8f9fa; border: 2px solid #ddd; border-radius: 24px;
         padding: 24px 20px; text-align: center; }
.phone-title { font-size: 19px; font-weight: bold; color: #333; margin-bottom: 16px;
               padding-bottom: 10px; border-bottom: 2px solid #eee; }
.phone-row { display: flex; justify-content: space-between; padding: 10px 6px;
             border-bottom: 1px solid #eee; font-size: 16px; }
.phone-label { color: #666; }
.phone-value { font-weight: bold; color: #333; }
.phone-highlight { font-size: 17px; font-weight: bold; text-align: center; margin-top: 14px;
                   padding: 10px; border-radius: 8px; }
"""

_MOCKUP_CSS_PANEL = """
body { margin: 0; padding: 0; background: white; font-family: Arial, Helvetica, sans-serif; }
.panel { width: 320px; background: white; border: 2px solid #333; border-radius: 14px;
         padding: 20px; }
.panel-title { font-size: 19px; font-weight: bold; text-align: center; color: #333;
               margin-bottom: 14px; padding-bottom: 10px; border-bottom: 2px solid #eee; }
.panel-row { display: flex; justify-content: space-between; padding: 8px 0;
             font-size: 16px; color: #444; }
.panel-label { font-weight: bold; }
.panel-value { color: #333; }
.panel-footer { font-size: 16px; font-weight: bold; text-align: center; margin-top: 12px;
                padding: 10px; border-radius: 6px; }
"""


def _build_mockup_html(
    device_type: str,
    rows: list[tuple[str, str]],
    highlight: str = "",
    highlight_positive: bool = True,
) -> str:
    """Build a deterministic mockup HTML from structured data."""
    if device_type == "smartwatch":
        # Smartwatch: title + big central value + remaining rows as sub-lines
        css = _MOCKUP_CSS_WATCH
        title = rows[0][1] if rows else ""
        value = rows[1][1] if len(rows) > 1 else ""
        sub_lines = ""
        for _, v in rows[2:]:
            sub_lines += f'<div class="watch-sub">{v}</div>'
        diff_color = "#4CAF50" if highlight_positive else "#f44336"
        content = (
            f'<div class="watch">'
            f'<div class="watch-title">{title}</div>'
            f'<div class="watch-value">{value}</div>'
            f'{sub_lines}'
            f'<div class="watch-diff" style="color:{diff_color}">{highlight}</div>'
            f'<div class="watch-icon">⭐</div>'
            f'</div>'
        )
    else:
        # Phone and panel share the same layout, only CSS differs
        prefix = "phone" if device_type == "phone" else "panel"
        css = _MOCKUP_CSS_PHONE if device_type == "phone" else _MOCKUP_CSS_PANEL
        title = rows[0][1] if rows else ""
        data_rows = ""
        for label, value in rows[1:]:
            data_rows += f'<div class="{prefix}-row"><span class="{prefix}-label">{label}</span><span class="{prefix}-value">{value}</span></div>'
        hl_bg = "#e8f5e9" if highlight_positive else "#fce4ec"
        hl_color = "#2e7d32" if highlight_positive else "#c62828"
        footer_cls = "phone-highlight" if device_type == "phone" else "panel-footer"
        content = (
            f'<div class="{prefix}">'
            f'<div class="{prefix}-title">{title}</div>'
            f'{data_rows}'
            f'<div class="{footer_cls}" style="background:{hl_bg};color:{hl_color}">{highlight}</div>'
            f'</div>'
        )

    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<style>{css}</style></head><body>{content}</body></html>'
    )


async def _render_mockup_programmatic(
    options: dict[str, str],
    cfg: ImageGeneratorConfig,
    shared_visual_format: str = "",
) -> dict[str, ImageGenerationResult]:
    """Extract structured mockup data from option texts via LLM, then render programmatically.

    Flow: LLM extracts field values → Python builds device UI HTML → Playwright screenshots.
    """
    from pydantic import BaseModel, Field
    import json

    labels = sorted(options.keys())[:4]
    client = _get_client()

    class MockupRenderData(BaseModel):
        device_type: str = Field(description="Cihaz tipi: smartwatch | phone | panel")
        field_labels: list[str] = Field(description="Tum seceneklerde ORTAK alan etiketleri (ornek: ['Baslik','Sonuc','Hedef'])")
        values_a: list[str] = Field(description="A sikki icin her etikete karsilik degerler")
        values_b: list[str] = Field(description="B sikki icin degerler")
        values_c: list[str] = Field(description="C sikki icin degerler")
        values_d: list[str] | None = Field(default=None, description="D sikki icin degerler (4 secenekli ise)")
        highlight_a: str = Field(description="A sikki vurgulanan bilgi (ozet/fark)")
        highlight_b: str = Field(description="B sikki vurgulanan bilgi")
        highlight_c: str = Field(description="C sikki vurgulanan bilgi")
        highlight_d: str | None = Field(default=None, description="D sikki vurgulanan bilgi (4 secenekli ise)")
        highlight_a_positive: bool = Field(description="A pozitif mi (yesil) yoksa negatif mi (kirmizi)")
        highlight_b_positive: bool = Field(description="B pozitif mi")
        highlight_c_positive: bool = Field(description="C pozitif mi")
        highlight_d_positive: bool | None = Field(default=None, description="D pozitif mi (4 secenekli ise)")

    n = len(labels)
    options_text = "\n".join(f"{l}) {options[l]}" for l in labels)

    prompt = f"""Asagidaki {n} mockup secenegi icin YAPISAL VERI cikar.

GORSEL TANIMI: {shared_visual_format}

{n} SECENEK:
{options_text}

KURALLAR:
1. field_labels: Tum seceneklerde ORTAK olan alan etiketlerini cikar (ornek: Baslik, Hedef, Sonuc)
2. Her secenek icin field_labels ile AYNI SIRADA ve AYNI SAYIDA deger yaz
3. Degerleri secenekten OLDUGU GIBI al — kisaltma, degistirme, birlestirme YASAK
4. Her secenegin highlight'i AYRI — ozet veya fark bilgisi
5. highlight_X_positive: deger pozitif/basarili ise true, negatif/basarisiz ise false
6. device_type: akilli saat ise "smartwatch", telefon ise "phone", diger ise "panel"
7. Her secenegin KENDINE OZGU verilerini yaz — baska secenekten KOPYALAMA
{f"8. values_d, highlight_d, highlight_d_positive BIRAKILABILIR — sadece {n} secenegin verisini cikar" if n < 4 else ""}
"""

    try:
        response = await client.aio.models.generate_content(
            model=cfg.judge_model,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                response_mime_type="application/json",
                response_schema=MockupRenderData,
            ),
        )

        data = MockupRenderData.model_validate_json(response.text)
        logger.info(f"[MOCKUP] Extracted data: device={data.device_type}, fields={data.field_labels}")

    except Exception as e:
        logger.error(f"[MOCKUP] Data extraction failed: {e}")
        return {l: ImageGenerationResult(success=False, error=f"Mockup data extraction failed: {e}") for l in labels}

    # Build mockup HTMLs
    option_values = {
        labels[0]: (data.values_a, data.highlight_a, data.highlight_a_positive),
        labels[1]: (data.values_b, data.highlight_b, data.highlight_b_positive),
        labels[2]: (data.values_c, data.highlight_c, data.highlight_c_positive),
    }
    if n >= 4 and data.values_d is not None:
        option_values[labels[3]] = (data.values_d, data.highlight_d or "", data.highlight_d_positive or False)

    html_map = {}
    for label, (values, highlight, hl_positive) in option_values.items():
        rows = list(zip(data.field_labels, values))
        html_map[label] = _build_mockup_html(
            device_type=data.device_type,
            rows=rows,
            highlight=highlight,
            highlight_positive=hl_positive,
        )

    return await _render_html_map_to_pngs(html_map, viewport_width=420, tag="MOCKUP")


# ============================================================================
# PARAGRAPH ILLUSTRATION GENERATION
# ============================================================================


async def generate_paragraph_illustration(
    paragraph: str,
    topic: str,
    grade: int,
    cfg: ImageGeneratorConfig,
    beceri_etiketi: dict | None = None,
) -> ImageGenerationResult:
    """
    Generate an educational illustration for a paragraph.

    Called AFTER successful question generation and save. The illustration
    visualizes the paragraph's main topic/event — it does not need to be
    directly related to the question's solution.

    Non-blocking: errors are logged but don't affect the question.

    Args:
        paragraph: The educational paragraph to illustrate
        topic: Topic name
        grade: Grade level (2, 3, 5, etc.)
        cfg: Image generator configuration
        beceri_etiketi: Optional skill label dict {katman, bilesenler, surec_bileseni}

    Returns:
        ImageGenerationResult with PNG bytes if successful
    """
    if not paragraph:
        return ImageGenerationResult(success=False, error="No paragraph for illustration")

    from ..generators.html_generator import grade_to_age_range
    age_range = grade_to_age_range(grade)

    client = _get_client()

    prompt = f"""Egitici bir ILLUSTRASYON ciz.

KONU: {topic}
SINIF SEVIYESI: {grade}. sinif ({age_range} yas)

PARAGRAF (bu metnin ana konusunu/olayini gorsel olarak canlandir):
\"\"\"{paragraph}\"\"\"

ILLUSTRASYON KURALLARI:
1. BEYAZ veya ACIK RENK ARKA PLAN
2. Paragraftaki ana konuyu veya ana olayi TEK SAHNE olarak ciz
3. {grade}. sinif ogrencisine uygun, sade ve sevimli bir cizim tarzi kullan
4. Renkli, canli ve ders kitabi tarzinda olmali
5. YAZI veya METIN EKLEME — sadece gorsel ogeler olmali
6. Tek sahneli ve odakli bir illustrasyon olmali
7. Cocuk dostu, pozitif ve egitici bir gorsel olmali
8. Karmasik detaylar EKLEME — sade ve anlasilir tut

KESINLIKLE YAPMA:
- Gorsele metin, baslik, etiket veya yazi YAZMA
- Birden fazla sahne veya kare kullanma
- Karanlik, korkutucu veya karmasik gorseller olusturma
- Ingilizce kelime veya harf kullanma
- Soyut veya kavramsal diyagramlar cizme — SOMUT gorsel olmali

NOT: Bu bir ders kitabi illustrasyonudur. Paragraftaki konuyu {age_range} yas grubu cocuklarin anlayacagi sadelikte, tek sahneli bir cizim olarak canlandir."""

    best_image: bytes | None = None

    for iteration in range(cfg.max_judge_iterations):
        logger.info(f"[ILLUSTRATION] Iteration {iteration + 1}/{cfg.max_judge_iterations}")

        try:
            png_bytes = None
            for attempt in range(cfg.max_retries + 1):
                try:
                    response = await client.aio.models.generate_content(
                        model=cfg.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(
                            temperature=cfg.temperature,
                        ),
                    )

                    png_bytes = None
                    if response.candidates and response.candidates[0].content:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, 'inline_data') and part.inline_data:
                                if part.inline_data.data:
                                    png_bytes = part.inline_data.data
                                    if isinstance(png_bytes, str):
                                        png_bytes = base64.b64decode(png_bytes)
                                    break

                    if png_bytes:
                        png_bytes = _ensure_png_bytes(png_bytes)
                        logger.info(f"[ILLUSTRATION] Generated {len(png_bytes)} bytes")
                        break

                    logger.warning("[ILLUSTRATION] No image in response")

                except Exception as e:
                    logger.warning(f"[ILLUSTRATION] Attempt {attempt + 1} failed: {e}")

            if not png_bytes:
                continue

            best_image = png_bytes

            # Judge the illustration
            png_base64 = base64.b64encode(png_bytes).decode("utf-8")

            judge_prompt = f"""Bu egitici ILLUSTRASYON gorselinin kalitesini kontrol et.

KONU: {topic}
SINIF: {grade}. sinif ({age_range} yas)

KONTROL KRITERLERI:
1. Gorsel paragrafin konusuyla ilgili mi? (Konu: {topic})
2. {grade}. sinif ({age_range} yas) ogrencisine uygun mu?
3. Gorselde metin/yazi var mi? (OLMAMALI)
4. Tek sahneli ve sade mi?
5. Cocuk dostu ve pozitif mi?

KARAR:
- Eger gorsel konuyla uyumlu, sade ve yas grubuna uygunsa: "KABUL"
- Eger konuyla uyumsuz, metin iceriyor veya uygunsuzsa: "REDDET: [neden]"

Cevabini "KABUL" veya "REDDET: [neden]" formatinda ver."""

            try:
                judge_response = await client.aio.models.generate_content(
                    model=cfg.judge_model,
                    contents=[
                        types.Content(
                            parts=[
                                types.Part(text=judge_prompt),
                                types.Part(
                                    inline_data=types.Blob(
                                        mime_type="image/png",
                                        data=png_bytes,
                                    )
                                ),
                            ]
                        )
                    ],
                )

                result_text = str(judge_response.text).upper()

                if "KABUL" in result_text:
                    logger.info("[ILLUSTRATION] Judge approved")
                    return ImageGenerationResult(
                        success=True,
                        png_bytes=png_bytes,
                        png_base64=png_base64,
                        judge_iterations=iteration + 1,
                    )

                logger.info(f"[ILLUSTRATION] Judge rejected: {judge_response.text}")

            except Exception as e:
                logger.warning(f"[ILLUSTRATION JUDGE] Failed: {e}")
                return ImageGenerationResult(
                    success=True,
                    png_bytes=png_bytes,
                    png_base64=png_base64,
                    judge_iterations=iteration + 1,
                )

        except Exception as e:
            logger.error(f"[ILLUSTRATION] Iteration {iteration + 1} failed: {e}")

    if best_image:
        png_base64 = base64.b64encode(best_image).decode("utf-8")
        return ImageGenerationResult(
            success=True,
            png_bytes=best_image,
            png_base64=png_base64,
            judge_iterations=cfg.max_judge_iterations,
        )

    return ImageGenerationResult(
        success=False,
        error="Illustration generation failed after all iterations",
        judge_iterations=cfg.max_judge_iterations,
    )


# ============================================================================
# ANSWER-CRITICAL VISUAL GENERATION (Bolum 7)
# ============================================================================


def _build_answer_critical_prompt(
    paragraph: str,
    question: str,
    correct_answer: str,
    options: dict,
    visual_type: str,
    visual_spec: dict,
) -> str:
    """Build an answer-aware image prompt specialized by visual_type."""
    opt_lines = "\n".join(f"  {k}) {v}" for k, v in (options or {}).items())
    spec_lines = (
        "\n".join(f"  - {k}: {v}" for k, v in (visual_spec or {}).items())
        or "  (yok)"
    )

    if visual_type == "symbol_pair":
        n_symbols = (visual_spec or {}).get("sembol_sayisi", 2)
        type_instruction = f"""TIP: SEMBOL TANIMI PANELI + SENARYO (Bolum 7.1)

Paragrafta IKI BOLUM var:
1. BOLUM 1 — SEMBOL TANIMLARI (ornek: "Sebeke isareti: Telefonun cekim gucunu ifade eder.")
2. BOLUM 2 — SENARYO (ornek: "Ozan: Anne, sarji cok az kaldi...")

GORSEL YAPISI (iki parcali, dikey):

┌─────────────────────────────────┐
│  UST PANEL — SEMBOL TANIMLARI   │
│                                 │
│  [IKON1]  Tanim basligi: Kisa   │
│  [IKON2]  Tanim basligi: Kisa   │
│  [IKON3]  Tanim basligi: Kisa   │
└─────────────────────────────────┘
        │
┌─────────────────────────────────┐
│    ALT KISIM — SENARYO          │
│  [Karakter cizimi]               │
│       [Konusma balonu: Senaryo]  │
│  Karakterin adi (alt etiket)     │
└─────────────────────────────────┘

UST PANEL KURALLARI:
- Paragraf BOLUM 1'deki HER sembol icin AYRI bir satir ciz
- Her satirda: SOL TARAFTA ikon (renkli, sade), SAG TARAFTA kisa Turkce etiket
- Ikonlar: Basit, net, 2. sinif duzeyinde (batarya/wifi/sebeke/trafik/hava)
- Ikonlarin etrafinda ince cerceve veya nokta stil
- Metin KISA ama NET (ornek: "Sebeke: Telefon cekim gucu")

ALT KISIM KURALLARI:
- Paragraf BOLUM 2'deki karakter/durumu RESMI olarak ciz
- Karakter SOL, konusma balonu SAG (veya tersi)
- Konusma balonu icinde senaryo metni Turkce
- Karakterin adi alt etikette: "Ozan", "Ayse" vb.

GENEL:
- BEYAZ arka plan, sade cocuk kitabi illustrasyon stili
- Iki bolum arasi INCE cizgi veya bosluk
- TEKST Turkce: "Sebeke", "Wifi", "Batarya" gibi
- Boyut: dikey yoneli (ust panel + alt senaryo)
- Ders kitabi kalitesinde, 2. sinif ogrencisinin begenecegi renkler"""
    elif visual_type == "scene":
        type_instruction = """TIP: SAHNE (GORSEL INCELEME)
- Paragraftaki olayi/durumu gosteren ZENGIN bir sahne ciz.
- Kahramanlar, mekan, eylem acikca gorulmeli.
- Paragraftaki SPESIFIK ayrintilar (renkler, nesneler, sayilar) sahnede GORSEL olarak yer almali.
- Metin YAZMA — sadece illustrasyon."""
    elif visual_type == "table":
        rows = (visual_spec or {}).get("tablo_satir", 4)
        cols = (visual_spec or {}).get("tablo_sutun", 3)
        type_instruction = f"""TIP: TABLO
- NOT: TABLO LLM tarafindan HTML olarak render edilmesi daha iyi sonuc verir.
- Image model ile: {rows} satir × {cols} sutunluk temiz bir tablo ciz.
- Satir ve sutun basliklari net okunur olmali.
- Turkce metin/rakamlar duzgun yazilmali (cikti gorsel olarak)."""
    elif visual_type == "chart":
        type_instruction = """TIP: GRAFIK (BAR/CIZGI)
- Paragraftaki verileri gosteren bar veya cizgi grafik ciz.
- Eksenler, etiketler, degerler net okunur olmali.
- Veri noktalari paragraftaki sayilarla BIREBIR ayni olmali.
- Turkce etiketler, beyaz arka plan, profesyonel sinav kitabi kalitesi."""
    elif visual_type == "pictograph":
        type_instruction = """TIP: PICTOGRAPH (SEKIL GRAFIGI — COCUK KITABI)

REFERANS: Veli meslek grafigi — her kategori ustunde ust uste yigilmis KISI FIGURLERI:
  Veli Sayisi
  ↑
  ♂♂    ♂♂♂    ♂♂    ♂♂
  ♂♂    ♂♂♂    ♂♂    ♂♂
  ♂♂    ♂♂♂    ♂♂    ♂♂
  ♂♂    ♂♂     ♂     ♂
  ─────────────────────→ Meslekler
  Memur Isci Ciftci Esnaf

  Not: Her sekil (♂) bir veliyi gostermektedir.

ZORUNLU LAYOUT:
- X ekseni (yatay): 3-5 KATEGORI etiketi (Turkce)
- Y ekseni (dikey): SAYI (Soru Sayisi / Veli Sayisi / Ogrenci Sayisi / vb.)
- Her kategori icin UST USTE YIGILI FIGURLER (paragrafta verilen sayi kadar)
- Figur tipi konuya gore:
  * Kisi/veli/ogrenci → INSAN FIGURU (basit cizgi adam, aynu renk)
  * Meyve (elma, muz) → MEYVE IKONU
  * Hayvan → HAYVAN SILUETI
  * Spor → TOP/SPORCU
- Hepsi AYNI BUYUKLUKTE, AYNI RENKTE ve DUZENLI hizali
- Alt etikette Turkce: "Not: Her sekil bir X'i gostermektedir"

YAPI:
- Arka plan BEYAZ
- Figurler canli (kirmizi veya mavi)
- Eksen cizgileri SIYAH, ince
- Konuya uygun figur sec — DUZ CUBUK/BAR kullanmak YASAK!
- Bu bir cocuk kitabindaki tipik sekil grafigi — sade, gorsel, sayilabilir"""
    elif visual_type == "infografik":
        type_instruction = """TIP: INFOGRAFIK
- Paragraftaki bilgileri gorsel ogeler (ikonlar, sayilar, bolumler) ile sunan bir infografik ciz.
- Kategoriler/bolumler acikca ayrilmis olmali.
- Her bolumde kisa Turkce etiket (1-3 kelime) olabilir."""
    elif visual_type == "logic_diagram":
        type_instruction = """TIP: MANTIK DIYAGRAMI (SIRALAMA, AILE, KURAL)
- Paragraftaki mantik iliskisini (sira, aile agaci, kural seti) gorsel olarak sun.
- Oklar, kutular, hiyerarsi acikca gorulmeli.
- Icerikteki kisi/nesne adlari sembollerle temsil edilebilir ya da kisa etiketle yazilabilir."""
    else:
        type_instruction = """TIP: GENERIC ANSWER-CRITICAL
- Gorsel, sorunun cevaplanabilmesi icin gerekli tum ipuclarini icermelidir.
- Dogru cevap yalnizca gorsel + paragraf birlikte incelenerek bulunabilmelidir."""

    return f"""Bu soru ICIN ANSWER-CRITICAL bir gorsel ciz. Gorsel, cevabin bulunmasi icin ZORUNLU olmalidir.

PARAGRAF:
\"\"\"{paragraph}\"\"\"

SORU: {question}

SECENEKLER:
{opt_lines}

DOGRU CEVAP: {correct_answer}

VISUAL SPEC:
{spec_lines}

{type_instruction}

KRITIK KURALLAR:
1. Gorsel, dogru cevaba goturen ayirici bilgiyi ICERMELIDIR.
2. Gorsel, yanlis secenekleri (celdiricileri) uygun sekilde ELEYEBILMELI ama dogruyu dogrulamali.
3. HIC ACIKLAMA/CAPTION METNI YAZMA.
4. Sadece gorsel ogeler + (gerekiyorsa) cok kisa Turkce etiketler (1-3 kelime).
5. Beyaz arka plan, sinav kitabi kalitesi, renkli ama sade.
6. Paragrafta GECMEYEN ekstra bilgi EKLEME.

DUAL-KAYNAK ZORUNLULUGU (EN KRITIK KURAL!):
- GORSEL TEK BASINA dogru cevabi VERMEMELI.
  Gorseli tek basina (paragrafsiz) inceleyen biri, hangi secenegin dogru oldugunu KESIN soyleyememeli.
- PARAGRAF TEK BASINA dogru cevabi VERMEMELI.
  Paragrafi tek basina (gorselsiz) okuyan biri, hangi secenegin dogru oldugunu KESIN soyleyememeli.
- Dogru cevap ancak GORSEL + PARAGRAF birlikte incelenerek bulunabilir olmalidir.
- Gorselde: paragraftaki ipucunun hangi secenekle eslestigini GOSTEREN bicimsel bilgi olmalidir
  (orn: simge tipi, sekil ozelligi, sayi/tablo hucresi).
- TEST: Paragraf kapali, sadece gorsel gorunsun; ogrenci bocalamaiidir (en az 2 makul aday).
  Ayni sekilde: gorsel kapali, sadece paragraf gorunsun; ogrenci yine bocalamaiidir.
"""


def _build_answer_aware_judge_prompt(
    paragraph: str,
    question: str,
    correct_answer: str,
    options: dict,
    visual_type: str,
    visual_spec: dict,
) -> str:
    """Judge prompt that checks image against question+correct_answer."""
    opt_lines = "\n".join(f"  {k}) {v}" for k, v in (options or {}).items())
    spec_lines = (
        "\n".join(f"  - {k}: {v}" for k, v in (visual_spec or {}).items())
        or "  (yok)"
    )
    return f"""Bu answer-critical gorselin kalitesini kontrol et.

PARAGRAF:
\"\"\"{paragraph}\"\"\"

SORU: {question}

SECENEKLER:
{opt_lines}

DOGRU CEVAP: {correct_answer}

VISUAL TIP: {visual_type}
VISUAL SPEC:
{spec_lines}

KONTROL KRITERLERI:
1. Gorsel, VISUAL SPEC kurallarina uyuyor mu? (orn. sembol_sayisi: 2 ise TAM 2 sembol var mi?)
2. Gorsel, paragrafla tutarli mi?
3. Gorsel + paragraf birlikte incelendiginde DOGRU CEVAP bulunabilir mi?
4. Gorsel ustunde uzun metin paragraf, caption, aciklama VAR mi? (Varsa REDDET)
5. Gorsel bicimsel olarak temiz ve 2. sinif ogrencisi icin uygun mu?

CIFT-KAYNAK TESTI (KRITIK — HER IKI YONDE ZORUNLU):
a) Paragraf KAPATILDIGINDA, sadece gorsele bakarak DOGRU CEVAP {correct_answer} kesin belirlenebilir mi?
   - Eger EVET → REDDET: "gorsel tek basina yeterli — paragraf gereksiz kaliyor"
   - Eger HAYIR (en az 2 makul secenek icinde bocalarsa) → TAMAM, bu yonde dual-source saglaniyor.
b) Gorsel KAPATILDIGINDA, sadece paragrafi okuyarak DOGRU CEVAP {correct_answer} kesin belirlenebilir mi?
   - Eger EVET → REDDET: "paragraf tek basina yeterli — gorsel gereksiz kaliyor"
   - Eger HAYIR → TAMAM, bu yonde dual-source saglaniyor.
c) Yalnizca (a) ve (b)'nin ikisi de HAYIR ise → KABUL (gercekten dual-source soru).

KARAR:
- Tum kriterler VE CIFT-KAYNAK TESTI (a)+(b) saglaniyorsa: "KABUL"
- Aksi halde: "REDDET: [eksiklik neden — hangi kriter/hangi yon]"
"""


async def generate_answer_critical_visual(
    paragraph: str,
    question: str,
    correct_answer: str,
    options: dict,
    visual_type: str,
    visual_spec: dict,
    subject: str,
    cfg: ImageGeneratorConfig,
) -> ImageGenerationResult:
    """
    Generate an answer-critical visual for Bolum 7 templates.

    Unlike generate_diagram_with_judge, the prompt and judge are aware of
    the question stem, options, correct answer and template-specific visual_spec.

    Flow:
    1. Build answer-aware prompt (branches by visual_type: symbol_pair, scene, chart, etc).
    2. Generate image via Gemini image model.
    3. Judge against question + correct_answer + visual_spec.
    4. Retry up to cfg.max_judge_iterations.
    5. Return best image (success=False only if ALL iterations produce no image at all).
    """
    if not paragraph:
        return ImageGenerationResult(success=False, error="No paragraph provided")

    client = _get_client()

    prompt = _build_answer_critical_prompt(
        paragraph, question, correct_answer, options, visual_type, visual_spec
    )

    best_image: bytes | None = None

    for iteration in range(cfg.max_judge_iterations):
        logger.info(
            f"[IMAGE-CRITIC] Iteration {iteration + 1}/{cfg.max_judge_iterations} "
            f"(visual_type={visual_type})"
        )
        png_bytes: bytes | None = None

        try:
            for attempt in range(cfg.max_retries + 1):
                try:
                    response = await client.aio.models.generate_content(
                        model=cfg.model,
                        contents=prompt,
                        config=types.GenerateContentConfig(temperature=cfg.temperature),
                    )
                    if response.candidates and response.candidates[0].content:
                        for part in response.candidates[0].content.parts:
                            if hasattr(part, "inline_data") and part.inline_data:
                                if part.inline_data.data:
                                    data = part.inline_data.data
                                    if isinstance(data, str):
                                        data = base64.b64decode(data)
                                    png_bytes = _ensure_png_bytes(data)
                                    break
                    if png_bytes:
                        break
                    logger.warning("[IMAGE-CRITIC] No image in response")
                except Exception as e:
                    logger.warning(
                        f"[IMAGE-CRITIC] Attempt {attempt + 1} failed: {e}"
                    )

            if not png_bytes:
                continue

            best_image = png_bytes

            judge_prompt = _build_answer_aware_judge_prompt(
                paragraph, question, correct_answer, options, visual_type, visual_spec
            )
            try:
                judge_response = await client.aio.models.generate_content(
                    model=cfg.judge_model,
                    contents=[
                        types.Content(
                            parts=[
                                types.Part(text=judge_prompt),
                                types.Part(
                                    inline_data=types.Blob(
                                        mime_type="image/png",
                                        data=png_bytes,
                                    )
                                ),
                            ]
                        )
                    ],
                )
                result_text = str(judge_response.text or "").upper()
                if "KABUL" in result_text:
                    logger.info("[IMAGE-CRITIC] Judge approved")
                    return ImageGenerationResult(
                        success=True,
                        png_bytes=png_bytes,
                        png_base64=base64.b64encode(png_bytes).decode("utf-8"),
                        judge_iterations=iteration + 1,
                    )
                logger.info(
                    f"[IMAGE-CRITIC] Judge rejected: {judge_response.text}"
                )
            except Exception as e:
                logger.warning(f"[IMAGE-CRITIC] Judge failed: {e}")
                # If judge fails, accept the image (best-effort)
                return ImageGenerationResult(
                    success=True,
                    png_bytes=png_bytes,
                    png_base64=base64.b64encode(png_bytes).decode("utf-8"),
                    judge_iterations=iteration + 1,
                )
        except Exception as e:
            logger.error(
                f"[IMAGE-CRITIC] Iteration {iteration + 1} failed: {e}"
            )

    if best_image:
        logger.info("[IMAGE-CRITIC] Returning best-effort image after max iterations")
        return ImageGenerationResult(
            success=True,
            png_bytes=best_image,
            png_base64=base64.b64encode(best_image).decode("utf-8"),
            judge_iterations=cfg.max_judge_iterations,
        )

    return ImageGenerationResult(
        success=False,
        error="Answer-critical visual generation failed after all iterations",
        judge_iterations=cfg.max_judge_iterations,
    )
