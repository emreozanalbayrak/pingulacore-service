"""
Goerselli soru uretim pipeline'i icin Pydantic cikti modelleri.
Her chain'in ciktisi burada tanimlanir.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Chain 1 ciktisi: Mega Soru Uretimi (sahne + soru + siklar + cozum)
# ---------------------------------------------------------------------------

class QuestionItem(BaseModel):
    """Tek bir sorunun yapisi (coklu soru setlerinde kullanilir)."""

    question_number: int = Field(description="Soru numarasi")
    question_stem: str = Field(description="Soru kok cumlesi")
    options: dict[str, str] = Field(
        description="Siklar: {'A': '...', 'B': '...', 'C': '...', 'D': '...'}"
    )
    correct_answer: str = Field(description="Dogru sik etiketi (A, B, C veya D)")
    solution_explanation: str = Field(description="Cozum aciklamasi")
    question_type: Optional[str] = Field(
        default=None,
        description="Soru tipi (soru_tipi_havuzundan)"
    )


class GeneratedVisualQuestion(BaseModel):
    """LLM-1 mega ciktisi: sahne + soru + siklar + cozum.

    Eskiden sahne tasarimi (SceneDesign) ayri chain'deydi,
    artik tek LLM call ile hepsi birlikte uretilir.
    """

    # --- Sahne tasarimi (eskiden ayri SceneDesign modeli idi) ---
    scene_description: str = Field(
        description="Sahnenin genel tarifi (orn: '6x7 kareli zemin, tavsan baslangicta, havuc hedefte')"
    )
    scene_elements: dict = Field(
        default_factory=dict,
        description=(
            "Sahne ogeleri. Anahtar-deger yapisi YAML gorsel tipine gore degisir. "
            "Grid tipi icin: grid_size, start_position, target_position, obstacles vb."
        ),
    )
    scenario_character: Optional[str] = Field(
        default=None,
        description="Senaryodaki karakter (orn: 'tavsan', 'robot')"
    )
    scenario_target_object: Optional[str] = Field(
        default=None,
        description="Senaryodaki hedef nesne (orn: 'havuc', 'paket')"
    )
    color_palette: str = Field(
        default="sade, pastel renkler",
        description="Renk onerisi"
    )

    # --- Senaryo ---
    scenario_text: str = Field(description="Senaryo / baglam metni")

    # --- Gizli hesaplama (opsiyonel) ---
    hidden_computation: Optional[dict] = Field(
        default=None,
        description="Gizli hesaplamalar (dogrulama icin, soru tipine gore degisir)"
    )

    # --- Gorsel uretim verileri ---
    visual_layout: dict = Field(
        default_factory=dict,
        description="Gorsel duzen bilgisi (grid boyutu, kart yerlesimi, sahne boyutu vb.)"
    )
    visual_elements: list[dict] = Field(
        default_factory=list,
        description="Gorseldeki tum ogeler (nesneler, etiketler, vurgular, isaretler)"
    )

    # --- Soru(lar) — siklar dahil ---
    questions: list[QuestionItem] = Field(
        description="Uretilen soru(lar)"
    )

    # --- Sik sahneleri (KOSULLU: sadece has_visual_options ise uretilir) ---
    option_scenes: Optional[dict[str, str]] = Field(
        default=None,
        description=(
            "Gorsel siklar icin her sikin sahne aciklamasi. "
            "Sadece YAML'da siklar gorsel ise LLM tarafindan uretilir. "
            "Ornek: {'A': 'Kirmizi top gorseli', 'B': 'Mavi top gorseli', 'C': 'Yesil top gorseli'}"
        ),
    )

    # --- Ilk cozum denemesi (uretici LLM'in kendi cozumu) ---
    self_solution: Optional[dict] = Field(
        default=None,
        description=(
            "Uretici LLM'in soruyu kendi cozmesi. "
            "Ornek: {'chosen_answer': 'B', 'reasoning': 'Adim adim cozum...'}"
        ),
    )

    # --- HTML sablonu ---
    html_content: str = Field(description="Uretilen HTML sablonu")

    # --- Kullanilan sayilar (sayi gecmisi icin LLM tarafindan doldurulur) ---
    used_numbers: list[int] = Field(
        default_factory=list,
        description=(
            "Bu soruda kullanilan ana tam sayilar. "
            "Ornek: [4, 5, 20] veya [6, 3, 18]. "
            "Sayi gecmisine kaydedilir; ayni sablonun sonraki uretimlerinde tekrar secilmez."
        ),
    )

    # --- Kullanilan nesneler (nesne gecmisi icin LLM tarafindan doldurulur) ---
    used_objects: list[str] = Field(
        default_factory=list,
        description=(
            "Bu soruda kullanilan ana sayilabilir nesnelerin Turkce isimleri. "
            "Ornek: ['elma', 'sepet'] veya ['kitap', 'raf', 'ogrenci']. "
            "Nesne gecmisine kaydedilir; ayni sablonun sonraki uretimlerinde tekrar secilmez."
        ),
    )

    # --- Zorluk ---
    difficulty_level: str = Field(
        default="orta",
        description="Zorluk seviyesi: kolay, orta, zor"
    )


# ---------------------------------------------------------------------------
# Chain 2 ciktisi: Batch Dogrulama
# ---------------------------------------------------------------------------

class BatchValidation(BaseModel):
    """LLM-2 ciktisi: toplu dogrulama sonucu."""

    curriculum_compliance: bool = Field(description="Kural uyumu")
    answer_consistency_check: bool = Field(description="Dogru cevap tutarliligi")
    distractor_quality_check: bool = Field(description="Celdirici kalitesi")
    format_check: bool = Field(description="Format uygunlugu")
    language_check: bool = Field(description="Dil uygunlugu")
    self_solution_check: bool = Field(
        default=True,
        description="Uretici LLM'in kendi cozumu dogru cevapla uyumlu mu?"
    )
    tymm_compliance: bool = Field(
        default=True,
        description="TYMM uyum kurallarina uygunluk (varsa)"
    )
    reference_compliance: bool = Field(
        default=True,
        description="Referans soru tanimlarina yapisal uyum (baglamli YAML'larda)"
    )
    numeric_consistency_check: bool = Field(
        default=True,
        description="Senaryo sayilari ile visual_elements sayilari ve dogru cevap birebir tutarli mi?"
    )
    overall_status: Literal["gecerli", "revizyon_gerekli"] = Field(
        description="Genel durum"
    )
    feedback: Optional[str] = Field(
        default=None,
        description="Sorun varsa geri bildirim detayi"
    )
    failed_checks: list[str] = Field(
        default_factory=list,
        description="Basarisiz kontrol isimleri"
    )


# ---------------------------------------------------------------------------
# Chain 3 ciktisi: Bagimsiz Soru Cozumu
# ---------------------------------------------------------------------------

class QuestionSolutionLLM(BaseModel):
    """LLM-3'un ureteceği sema — sadece LLM ciktisi icin.

    matches_expected bu semanin DISINDADIR; chain fonksiyonu hesaplar.
    """

    chosen_answer: str = Field(description="Secilen sik: A, B veya C")
    reasoning: str = Field(description="Adim adim cozum mantigi")
    confidence: Literal["yuksek", "orta", "dusuk"] = Field(
        description="Cozucunun guven seviyesi"
    )


class QuestionSolution(QuestionSolutionLLM):
    """Tam cozum sonucu — LLM ciktisi + hesaplanan uyusma alani."""

    matches_expected: bool = Field(
        default=False,
        description="Cozucunun cevabi beklenen dogru cevapla uyusur mu? (chain tarafindan hesaplanir)"
    )


# ---------------------------------------------------------------------------
# Chain 4 ciktisi: Gorsel Uretimi
# ---------------------------------------------------------------------------

class GeneratedImages(BaseModel):
    """LLM-4b ciktisi: uretilen gorseller."""

    main_image_path: str = Field(description="Ana gorsel dosya yolu")
    option_images: Optional[dict[str, str]] = Field(
        default=None,
        description="Sik gorselleri: {'A': path, 'B': path, 'C': path} (gorselli ise)"
    )
    generation_notes: Optional[str] = Field(
        default=None,
        description="Gorsel uretim notlari"
    )


# ---------------------------------------------------------------------------
# Chain 5 ciktisi: Gorsel Dogrulama
# ---------------------------------------------------------------------------

class VisualValidation(BaseModel):
    """LLM-5 ciktisi: 6 boyutlu gorsel dogrulama."""

    content_accuracy: bool = Field(
        description="Gorsel soru verileriyle uyumlu mu?"
    )
    visual_clarity: bool = Field(
        description="Okunaklı ve net mi? Ogeler kolayca ayirt edilebilir mi?"
    )
    age_appropriateness: bool = Field(
        description="Sinif seviyesine uygun sadelikte mi?"
    )
    language_correctness: bool = Field(
        description="Gorseldeki tum yazilar Turkce mi?"
    )
    label_check: bool = Field(
        description="Gorseldeki etiketler ve vurgular dogru mu?"
    )
    layout_quality: bool = Field(
        description="Ogeler ust uste binmiyor mu? Sinirlar icinde mi?"
    )
    pedagogical_support: bool = Field(
        default=True,
        description=(
            "Gorsel, sorunun olcmeyi amacladigi beceriyi destekliyor mu? "
            "Ogrenci gorselden dogru cevaba ulasabilir mi? "
            "Gorsel yanlislikla celdirici stratejilerinden birini destekliyor mu?"
        ),
    )
    overall_status: Literal["uygun", "revizyon_zorunlu"] = Field(
        description="Genel durum"
    )
    feedback: Optional[str] = Field(
        default=None,
        description="Sorun varsa geri bildirim detayi"
    )
    failed_dimensions: list[str] = Field(
        default_factory=list,
        description="Basarisiz boyut isimleri"
    )
    failed_targets: list[str] = Field(
        default_factory=list,
        description="Basarisiz gorsel hedefleri: 'main', 'option_A', 'option_B', ..."
    )


# ---------------------------------------------------------------------------
# Chain 6 ciktisi: Gorsel Uzerinden Bagimsiz Cozum
# ---------------------------------------------------------------------------

class VisualQuestionSolutionLLM(BaseModel):
    """LLM-6'nin ureteceği sema — sadece LLM ciktisi icin.

    matches_expected bu semanin DISINDADIR; chain fonksiyonu hesaplar.
    """

    chosen_answer: str = Field(description="Secilen sik: A, B veya C")
    reasoning: str = Field(description="Gorsel inceleme ile adim adim cozum")
    visual_issues: list[str] = Field(
        default_factory=list,
        description="Gorselde fark edilen sorunlar (yanlis etiket, belirsiz oge vb.)"
    )
    issues_affect_solution: bool = Field(
        default=False,
        description=(
            "Gorseldeki sorunlar ogrencinin dogru cevaba ulasmasini veya "
            "gorselden guvenilir sayim/islem yapmasini etkiliyor mu?"
        ),
    )


class VisualQuestionSolution(VisualQuestionSolutionLLM):
    """Tam gorsel cozum sonucu — LLM ciktisi + hesaplanan uyusma alani."""

    matches_expected: bool = Field(
        default=False,
        description="Cozucunun cevabi beklenen dogru cevapla uyusur mu? (chain tarafindan hesaplanir)"
    )
