"""
Batch Validator - runs multiple validation checks in 2 LLM calls instead of 7-8.

Optimization:
- Batch 1: Non-PDF checks (html_technical, question_format, grade_level, distractors, turkish, solvability)
- Batch 2: PDF-required checks (accuracy, curriculum_alignment)
- Both batches run in parallel using asyncio.gather()

This reduces validation time from ~14-20 seconds to ~3-5 seconds.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from typing import Literal

from pydantic import BaseModel, Field

from .prompts.validator_prompts import VALIDATOR_SYSTEM_PROMPT

if TYPE_CHECKING:
    from .client import GeminiClient

__all__ = [
    "BatchValidator",
    "BatchValidationResult",
    "BatchCheckResult",
    "PDF_REQUIRED_CHECKS",
    "DEFAULT_REQUIRED_CHECKS",
    "enrich_validation_feedback",
]

logger = logging.getLogger(__name__)


# ============================================================================
# CONSTANTS
# ============================================================================

# Checks that require the MEB PDF context
PDF_REQUIRED_CHECKS = frozenset({"accuracy", "curriculum_alignment"})

# Default validation checks (all available)
DEFAULT_REQUIRED_CHECKS = [
    "html_technical",  # NEW - check HTML structure first (fail fast)
    "question_format",
    "grade_level",
    "accuracy",
    "distractors",
    "turkish",
    "solvability",
    "curriculum_alignment",
]


# ============================================================================
# PYDANTIC SCHEMAS FOR BATCH VALIDATION
# ============================================================================


class SingleCheckResult(BaseModel):
    """Result of a single validation check within a batch."""

    status: Literal["PASS", "FAIL"] = Field(
        ...,
        description="Whether the check passed or failed",
    )
    score: int = Field(
        ...,
        ge=0,
        le=100,
        description="Quality score from 0-100",
    )
    feedback: str = Field(
        ...,
        description="Detailed feedback about the check result",
    )
    issues: list[str] = Field(
        default_factory=list,
        description="List of specific issues found (empty if passed)",
    )
    suggestions: list[str] = Field(
        default_factory=list,
        description="List of suggestions for improvement",
    )
    affected_components: list[Literal["paragraph", "question_stem", "options"]] = Field(
        default_factory=list,
        description="Which component(s) have issues",
    )


class NonPDFBatchOutput(BaseModel):
    """Output schema for non-PDF checks batch (6 checks in 1 call)."""

    html_technical: SingleCheckResult = Field(
        ...,
        description="HTML yapı kontrolü",
    )
    question_format: SingleCheckResult = Field(
        ...,
        description="Soru formatı kontrolü",
    )
    grade_level: SingleCheckResult = Field(
        ...,
        description="Sınıf seviyesi uygunluğu kontrolü",
    )
    distractors: SingleCheckResult = Field(
        ...,
        description="Çeldirici kalitesi kontrolü",
    )
    turkish: SingleCheckResult = Field(
        ...,
        description="Türkçe dil bilgisi kontrolü",
    )
    solvability: SingleCheckResult = Field(
        ...,
        description="Çözülebilirlik kontrolü",
    )


class PDFBatchOutput(BaseModel):
    """Output schema for PDF-required checks batch (2 checks in 1 call)."""

    accuracy: SingleCheckResult = Field(
        ...,
        description="Bilimsel doğruluk kontrolü",
    )
    curriculum_alignment: SingleCheckResult = Field(
        ...,
        description="Müfredat uyumu kontrolü",
    )


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class BatchCheckResult:
    """Result of a single validation check."""

    check_type: str
    check_name: str
    status: Literal["PASS", "FAIL"]
    score: int
    feedback: str
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    affected_components: list[str] = field(default_factory=list)


@dataclass
class BatchValidationResult:
    """Complete validation result from batch processing."""

    passed: bool
    overall_score: float
    checks: dict[str, BatchCheckResult] = field(default_factory=dict)

    @property
    def failed_checks(self) -> list[BatchCheckResult]:
        """Return list of failed checks."""
        return [c for c in self.checks.values() if c.status == "FAIL"]

    def get_feedback_summary(self) -> str:
        """Get a summary of all feedback."""
        lines = []
        for check in self.checks.values():
            status_marker = "[PASS]" if check.status == "PASS" else "[FAIL]"
            lines.append(f"{status_marker} {check.check_name}: {check.feedback}")
            for issue in check.issues:
                lines.append(f"  - Sorun: {issue}")
            for suggestion in check.suggestions:
                lines.append(f"  - Öneri: {suggestion}")
        return "\n".join(lines)

    def get_affected_components(self) -> set[str]:
        """Get all affected components from failed checks."""
        components: set[str] = set()
        for check in self.failed_checks:
            components.update(check.affected_components)
        return components


# ============================================================================
# BATCH PROMPTS
# ============================================================================

# Smart validator prompt - detects question type automatically
NON_PDF_BATCH_PROMPT = """GÖREV: Aşağıdaki soruyu 5 farklı açıdan değerlendir.

═══════════════════════════════════════════════════════════════════
⚠️ ÖNEMLİ - İLK ADIM: SORU TİPİNİ BELİRLE!
═══════════════════════════════════════════════════════════════════

Soruyu değerlendirmeden ÖNCE tipini belirle:

📌 STANDART FORMAT:
   - Ana paragraf VAR (dolu metin)
   - Soru paragrafı soruyor ("Bu metnin konusu nedir?" gibi)
   - Seçenekler kısa (2-6 kelime)

📌 TERS MANTIK FORMAT (INVERSE):
   - Ana paragraf YOK veya BOŞ (bu normal, tasarım gereği!)
   - Soru kökünde bir KONU verilir ("X konulu bir metin..." gibi)
   - Seçenekler uzun mini-paragraflar (25-45 kelime)
   - "yer almaz", "olamaz", "getirilemez" gibi olumsuz ifade var
   - 3 seçenek konuya UYAR, 1 seçenek UYMAZ (doğru cevap)

═══════════════════════════════════════════════════════════════════

PARAGRAF:
{paragraph}

SORU: {question}
{options_text}
Doğru Cevap: {correct_answer}

SINIF SEVİYESİ: {grade}. sınıf

═══════════════════════════════════════════════════════════════════
                    DEĞERLENDİRME KRİTERLERİ
═══════════════════════════════════════════════════════════════════

1. HTML TEKNİK KONTROLÜ (html_technical)

   BASİT KONTROL: Rendering'i bozacak yasak HTML tag'leri var mı?

   YASAK TAG'LER: <ol>, <li>, <ul>, <div>, <span>, <p>, <strong>, <em>
   İZİN VERİLEN: Sadece <b>, <u>, <br> (<strong> yerine <b>, <em> yerine <u> kullanılmalı)

   🔢 RAKAM KURALI (4. SINIF): Seçeneklerde ve paragrafta yalnızca ARAP RAKAMLARI
   (1, 2, 3, 4, 5, 6, 7, 8, 9, 10) kullanılmalı. ROMA RAKAMI (I, II, III, IV, V)
   4. sınıf sorularında ASLA kullanılmaz. Roma rakamı görürsen → FAIL, score: 0.

   KONTROL:
   - Soru kökünde yasak tag var mı kontrol et
   - SORU KÖKÜNDEKİ <u> etiketi SADECE olumsuz/dışlayıcı kelimeler için mi kullanılmış?
     Ornekler (tam liste degil — semantik olarak olumsuz/dislayici olan tum fiiller dahildir):
     olamaz, olmaz, değildir, değil, yoktur, beklenemez, çıkarılamaz, söylenemez, bulunmaz,
     getirilemez, yer almaz, yapılamaz, ulaşılamaz, yer verilmemiştir, verilmemiştir,
     kullanılmamıştır, -mez/-maz/-memiştir/-mamıştır ile biten olumsuz fiiller
   - SORU KÖKÜNDEKİ pozitif/nötr kelimelerde <u> varsa → FAIL (örn: <u>başlık</u>, <u>en uygun</u> YASAK)
   - Varsa → status: FAIL, score: 0
   - Yoksa → status: PASS, score: 100

   ⚠️ ÖNEMLİ: <u> kontrolü SADECE soru kökü (question) alanı için geçerlidir!
   PARAGRAF alanında <u> etiketi SERBESTTIR — bazı soru tipleri (zıt anlamlı kelime soruları, sözcükte anlam soruları) paragraftaki kelimeleri <u> ile vurgular. Bu TASARIM GEREĞİDİR, hata DEĞİLDİR. Paragraftaki <u> kullanımını FAIL YAPMA!

   NOT: Bu sadece rendering kontrolü. Içerik kalitesini değil, sadece HTML yapısını kontrol eder.

   feedback: Hangi yasak tag bulundu (varsa)
   issues: ["<ol> tag'i bulundu"] veya boş
   affected_components: ["question_stem"] veya boş

2. SORU FORMATI (question_format)

   STANDART FORMAT için:
   - Soru cümlesi paragrafı içermiyor mu?
   - Soru alanı SADECE soru cümlesinden mi oluşuyor?
   - {option_count} şık ({option_labels_str}) var mı?
   - Doğru cevap {option_labels_str} seçeneklerinden biri mi?
   - Soru "?" ile bitiyor mu?
   - Soru kökü TEK SATIRDA mı? (gereksiz \n veya <br> var mı? Öncüllü sorular hariç)
   - Soru numarası (1., 2. gibi) ile mi başlıyor? (YASAK! Soru numarası olmamalı)
   - Paragrafta soru cümlesi var mı? Paragraf HİÇBİR YERDE soru işareti (?) içermemeli! "Hiç düşündünüz mü?", "Neden böyledir?" gibi soru cümleleri YASAK. Herhangi bir yerde ? varsa → score -= 25, FAIL, feedback ver.

   TERS MANTIK FORMAT için:
   - Soru kökünde bir konu belirtilmiş mi?
   - "yer almaz", "olamaz", "getirilemez" gibi olumsuz ifade var mı?
   - {option_count} şık ({option_labels_str}) var mı?
   - Her şık mini-paragraf formatında mı (2-4 cümle)?

2. SINIF SEVİYESİ (grade_level)
   - Kelime hazinesi {grade}. sınıf için uygun mu?
   - Kavram karmaşıklığı yaşa uygun mu?
   - Cümle yapısı çok karmaşık değil mi?
   - Ön bilgi gereksinimleri makul mü?

   {paraphrase_policy}

3. ÇELDİRİCİ KALİTESİ (distractors)

   STANDART FORMAT için:
   a) YAKIN ANLAM TESTİ (ZORUNLU!):
      - En az 1 çeldirici doğru cevaba ÇOK YAKIN olmalı
      - Doğru cevabın kapsamını hafifçe kaydıran bir şık olmalı
      - Yakın anlam çeldirici yoksa → score <= 55, FAIL
   b) AŞIRI GENİŞ TESTİ:
      - "Çok geniş" çeldirici doğru cevapla AYNI ALANDA olmalı
      - Tamamen farklı konuya ait çeldirici → score <= 55, FAIL
   c) AÇIK MARKER TESTİ (YENİ!):
      - Hiçbir çeldirici "direkt elenebilir" olmamalı
      - Farklı gezegen/cisim adı (paragraf Ay → şık Mars) → FAIL
      - Tamamen alakasız organ/tür/kategori → FAIL
      - Paragrafla HIÇBIR İLİŞKİSİ olmayan ifade → FAIL
   d) STRATEJİ ÇEŞİTLİLİĞİ:
      - Farklı tuzak tipleri kullanılmış mı?
      - Tüm çeldiriciler aynı tipte olmamalı
   e) UZUNLUK DENGESİ (KRİTİK!):
      - Doğru cevabın kelime sayısını say.
      - Her çeldiricinin kelime sayısını say.
      - Doğru cevap diğer şıklardan %20+ daha uzunsa → score -= 30, FAIL
      - Doğru cevap diğer şıklardan %20+ daha kısaysa → score -= 25, FAIL
      - Doğru cevap TÜM şıkların EN UZUNU ise → score -= 20, FAIL (öğrenciler en uzun şıkkı seçme eğiliminde)
      - İdeal: Tüm şıklar ±1-2 kelime fark içinde olmalı
      - ÖRNEK FAIL: Doğru="Depremlere karşı korunma yöntemlerini bilmek gerekir" (8 kelime), Çeldiriciler="Deprem" (1), "Sel" (1), "Yangın" (1)
      - ÖRNEK PASS: A="Deprem korunması" (2), B="Sel önlemleri" (2), C="Yangın güvenliği" (2), D="Fırtına hazırlığı" (2)

   f) ANLAMSAL AĞIRLIK PARİTESİ:
      - Tüm seçenekler (doğru cevap dahil) aynı soyutluk/somutluk seviyesinde mi?
      - Bir seçenek "genel/soyut kavram" diğerleri "spesifik/somut terim" değil mi?
      - Örnek FAIL: A) uyku  B) kalite  C) hafıza  D) sağlık
        → "kalite" ve "sağlık" soyut, "uyku" ve "hafıza" somut — DENGESİZ
      - Örnek PASS: A) uyku  B) hafıza  C) karanlik  D) bagisiklik
        → Hepsi somut kavramlar — DENGELİ
      - RETORİK AĞIRLIK: Tüm seçenekler benzer ikna gücünde olmalı
        * Bir seçenek güçlü retorik ifade (kesinlikle, mutlaka, her zaman) içerip diğerleri nötr → DENGESİZ
        * Bir seçenek duygusal/vurgulu, diğerleri düz ifade → DENGESİZ
        * Tüm seçenekler aynı ton ve ikna düzeyinde olmalı
      - Eğer soyutluk VEYA retorik dengesizlik varsa → score -= 15, issues'a ekle

   g) SEÇENEK BENZERSİZLİK KONTROLÜ (KRİTİK!):
      - Tüm 4 şık birbirinden FARKLI mı? (Kopyala-yapıştır tespit et!)
      - Hiçbir iki şık %80+ benzer olmamalı (aynı cümle, küçük fark hariç)
      - Öncüllü sorularda (I, II, III, IV) seçenek kombinasyonları benzersiz mi?
      - Seçeneklerin başlangıç kelimeleri hep aynı mı? (monotonluk → score -= 10)
      - FAIL koşulu: İki veya daha fazla şık neredeyse aynıysa → score -= 30, FAIL

   h) ANAHTAR SÖZCÜK SORULARINDA DOĞRU CEVAP KONTROLÜ (TEK KELİME SEÇENEKLERİ İÇİN):
      - Eğer seçenekler tek kelimeden oluşuyorsa VE soru "anahtar sözcük olamaz/değildir" tipindeyse:
        * Doğru cevap olarak işaretlenen sözcük paragrafta GEÇİYOR MU?
        * Doğru cevap konuyla tematik akrabalığı olan ama anahtar olmayan bir sözcük mü?
        * Doğru cevap diğer şıklardan yapısal olarak ayrışmıyor mu (uzunluk, tür)?
      - Doğru cevap paragrafta geçmiyorsa → score <= 50, FAIL
      - Doğru cevap konuyla hiç ilgisi yoksa → score <= 55, FAIL

   i) SEÇENEK DİL YAPISI EŞİTLİĞİ (KRİTİK!):
      - 4 seçenek AYNI dilbilgisel yapıda mı? (hepsi isim tamlaması, hepsi cümle, hepsi sıfat+isim vb.)
      - Bir seçenek cümle, diğerleri tek kelime → FAIL
      - Bir seçenek fiil içeriyor, diğerleri isim tamlaması → FAIL
      - Doğru cevap seçeneklerden dilsel olarak ayırt edilebilir mi? (olmamalı)
      - Örnek FAIL: A) "Güneşle ısınma" B) "Rutubet" C) "Toprak kayması" D) "Yağmur suyunu biriktirerek tasarruf etmek"
        → D bariz uzun ve farklı yapı (fiilimsi cümlesi vs isim tamlaması)
      - Örnek PASS: A) "Isı yalıtımı" B) "Su tasarrufu" C) "Enerji verimliliği" D) "Geri dönüşüm"
        → Hepsi isim tamlaması, benzer uzunluk
      - Yapı uyumsuzluğu varsa → score -= 20, issues'a ekle

   j) METİN DIŞI BİLGİ YASAĞI:
      - Hiçbir çeldirici paragrafta/metinde OLMAYAN dış bilgi içermemeli
      - Çeldirici paragraftaki kavramlardan türetilmiş olmalı
      - Metinde bahsedilmeyen isim, yer, olay → score -= 20, FAIL
      - "Metin okunmadan elenebilir" çeldirici = kalitesiz → FAIL
      - Önemli: Çeldirici paragrafta geçen bilgileri ÇARPITARAK oluşturulmalı, dışarıdan bilgi eklenmemeli

   k) MERKEZ KAVRAM ANAHTAR KELİME KONTROLÜ:
      - Her çeldirici, sorunun hedef kavram ailesinden en az 1 anahtar kelime içermeli
      - Tamamen farklı kavram alanına ait çeldirici → score -= 15, FAIL
      - Örnek: Soru "deprem" hakkında → çeldirici "sel baskını" (farklı kavram ailesi) → FAIL
      - Örnek: Soru "deprem" hakkında → çeldirici "deprem dalgaları" (aynı kavram ailesi) → PASS
      - Tüm çeldiriciler sorunun konusuyla AYNI kavramsal alanda olmalı

   l) SAYISAL VERİ TUTARLILIĞI:
      - Paragrafta sayısal veri (yüzde, oran, miktar, tarih) varsa:
        * Çeldiricilerdeki sayısal ilişkiler mantıklı olmalı
        * Rastgele veya absürt sayılar → score -= 15
        * Sayısal verilerin büyüklük sırası ve bağlamı tutarlı olmalı
      - Paragrafta sayısal veri yoksa bu kriter ATLANIR

   m) BAĞLAM BAĞIMLI ÇELDİRİCİ KONTROLÜ:
      - Bağlam temelli sorularda: her çeldirici bağlamdaki veriye/senaryoya referans içermeli
      - Bağlamla hiç ilişkisi olmayan genel bilgi çeldiricisi → score -= 25, FAIL
      - TEST: Öğrenci bağlamı okumadan çeldiriciyi eleyebilir mi? Evet → ZAYIF
      - Çeldirici bağlamdaki veriyi ÇARPITARAK oluşturulmalı, dışarıdan bilgi eklenmemeli

{distractor_strategies_hint}
{template_semantics_hint}
   TERS MANTIK FORMAT için:
   - 3 şık soru kökündeki konuya gerçekten UYUYOR mu?
   - Doğru cevap (konuya uymayan) "yakın ama farklı bir alan" mı?
   - Doğru cevap tamamen alakasız değil mi?
   - Şıklar benzer uzunlukta mı?

4. TÜRKÇE DİL BİLGİSİ (turkish)

   a) YAZIM KONTROLÜ:
      - Türkçe özel karakterler doğru mu? (ş/s, ç/c, ğ/g, ü/u, ö/o, ı/i karışıklığı)
      - Bileşik sözcükler doğru yazılmış mı? (birleşik/ayrı/tire)
      - Büyük/küçük harf kuralları doğru mu?

   b) NOKTALAMA KONTROLÜ:
      - Noktalama işaretlerinden ÖNCE boşluk YOK, SONRA boşluk VAR mı?
      - Ardışık noktalama yok mu? (.., !!, ?!)
      - Virgül ve nokta kullanımı doğru mu?
      - Soru işareti gereken yerde var mı?

   c) DİLBİLGİSİ KONTROLÜ:
      - Özne-yüklem uyumu var mı?
      - Zaman uyumu tutarlı mı? (geçmiş/geniş/gelecek karışmıyor mu?)
      - Ek yığılması (gereksiz ekler) var mı?
      - Devrik cümle gereksiz yere kullanılmış mı?

   d) AKICILIK ve DOĞALLIK:
      - Kelimeler doğal sırada mı?
      - Tekrar eden kelimeler var mı? (aynı kelime aynı cümlede)
      - Cümle yapısı {grade}. sınıf öğrencisi için doğal mı?

5. ÇÖZÜLEBİLİRLİK (solvability)

   ⚠️ BU KRİTER SORU TİPİNE GÖRE DEĞİŞİR!

   STANDART FORMAT için:
   - Soru SADECE paragrafı okuyarak cevaplanabilir mi?
   - Dış bilgi gerektirir mi? (gerektirmemeli)
   - Yanlış şıklar paragrafla çelişiyor mu? (çelişmeli)
   - Birden fazla şık doğru olabilir mi? (olmamalı)

   TERS MANTIK FORMAT için (paragraf BOŞ olması NORMAL!):
   - Soru SADECE soru kökündeki konuyu ve seçenekleri okuyarak çözülebilir mi?
   - 3 şık verilen konuya açıkça UYUYOR mu?
   - 1 şık (doğru cevap) konuyla aynı alanda ama FARKLI bir konuda mı?
   - Öğrenci "hangisi konuya ait değil?" sorusunu cevaplayabilir mi?
   - Birden fazla şık "konuya uymaz" kategorisinde mi? (olmamalı)

   ⚠️ ANSWER-CRITICAL GÖRSEL FORMATI için (visual_requirement="answer_critical"):
   {visual_requirement_hint}
   - Bu şablon türünde, soru SADECE paragrafla çözülMEMELİDİR — bu TASARIM GEREĞİ!
   - Soru kökü "Görseldeki sembol...", "Şekle göre...", "Tabloya göre..." gibi GÖRSELE ATIFTA bulunmalıdır → bu DOĞRU davranıştır, PASS ver.
   - Görsel henüz üretilmemiş olsa bile soru kökü görsele atıf yapıyorsa ve seçenekler görsele uygun sınıfta ise → PASS.
   - FAIL sadece şu durumda: Soru kökü görsele HİÇ atıf yapmıyor VE paragraf+seçenekler birlikte çözüm imkansız.
   - "Görsel yok, soru çözülemez" gibi FAIL VERME — görsel pipeline tarafından sonradan üretilecek.

═══════════════════════════════════════════════════════════════════
                         DEĞERLENDİRME
═══════════════════════════════════════════════════════════════════

Her kriter için:
- status: PASS veya FAIL
- score: 0-100 arası puan
- feedback: Kısa açıklama
- issues: Tespit edilen sorunlar listesi (FAIL ise)
- suggestions: İyileştirme önerileri
- affected_components: Sorunlu bileşenler ("paragraph", "question_stem", "options")
"""


PDF_BATCH_PROMPT = """GÖREV: Aşağıdaki soruyu MEB ders kitabına göre 2 açıdan değerlendir.

Sana MEB ders kitabı PDF'i verildi. Bu kitabı referans olarak kullan.

PARAGRAF:
{paragraph}

SORU: {question}
{options_text}
Doğru Cevap: {correct_answer}

SINIF SEVİYESİ: {grade}. sınıf

═══════════════════════════════════════════════════════════════════
                    DEĞERLENDİRME KRİTERLERİ
═══════════════════════════════════════════════════════════════════

1. BİLİMSEL DOĞRULUK (accuracy)
   - Paragraftaki bilgiler doğru mu?
   - MEB kitabındaki bilgilerle tutarlı mı?
   - Yanıltıcı veya yanlış ifadeler var mı?
   - Kavramlar doğru açıklanmış mı?
   - Örnekler gerçekçi mi?

2. MÜFREDAT UYUMU (curriculum_alignment)
   - Kitaptaki terimler mi kullanılmış?
   - Açıklamalar kitaptaki anlatımla uyumlu mu?
   - Kitapta olmayan ileri seviye kavramlar var mı?
   - Bilgiler kitapla çelişiyor mu?
   - Hangi sayfa/bölümle karşılaştırdığını belirt

═══════════════════════════════════════════════════════════════════
                         DEĞERLENDİRME
═══════════════════════════════════════════════════════════════════

Her kriter için:
- status: PASS veya FAIL
- score: 0-100 arası puan
- feedback: Kısa açıklama (kitap referansı dahil)
- issues: Tespit edilen sorunlar listesi (FAIL ise)
- suggestions: İyileştirme önerileri
- affected_components: Sorunlu bileşenler ("paragraph", "question_stem", "options")
"""


class ContextDependencyOutput(BaseModel):
    """Output schema for context dependency check."""

    context_dependency: SingleCheckResult = Field(
        ...,
        description="Baglam bagimliligi kontrolu",
    )


CONTEXT_DEPENDENCY_PROMPT = """GÖREV: Bu sorunun bağlam metnine gerçekten bağımlı olup olmadığını kontrol et.

BAĞLAM METNİ:
{context_text}

SORU: {question}
{options_text}
Doğru Cevap: {correct_answer}

KRİTER (context_dependency):
- Bu soruyu SADECE genel bilgiyle (bağlam metni olmadan) çözebilir misiniz?
- Bağlamdaki tablo/veri/senaryo soruyu çözmek için GEREKLİ mi?
- Eğer bağlam olmadan çözülebiliyorsa → FAIL (soru bağlam temelli değil)
- Eğer bağlam zorunluysa → PASS

EK KRİTERLER (CEVAP AÇIKLIĞI):
- Doğru cevap bağlamdan AÇIKÇA çıkarılabilir mi?
  * Tablo var ama soru tablodaki veriyle cevaplanamıyor → FAIL
  * Paragraf var ama soru paragraftaki bilgiyle cevaplanamıyor → FAIL
  * Doğru cevap bağlamdaki veri/bilgiyle ÇELİŞİYORSA → FAIL
  * Doğru cevap bağlamdan mantıksal ÇIKARIM gerektiriyorsa → PASS (bu iyi)

DİKKAT: Bağlamda verilen SPESİFİK veri/tablo/senaryo OLMADAN cevaplanamıyorsa PASS.
Genel kültür bilgisiyle cevaplanabiliyorsa FAIL.

Değerlendirme:
- status: PASS veya FAIL
- score: 0-100 arası puan
- feedback: Kısa açıklama
- issues: Tespit edilen sorunlar listesi (FAIL ise)
- suggestions: İyileştirme önerileri
- affected_components: ["question_stem", "options"]
"""


class EthicsCheckOutput(BaseModel):
    """Output schema for ethics and impartiality check."""

    ethics_check: SingleCheckResult = Field(
        ...,
        description="Etik ve tarafsizlik kontrolu",
    )


ETHICS_CHECK_PROMPT = """GÖREV: Aşağıdaki soruyu ETİK VE TARAFSIZLIK açısından değerlendir.

DERS: {subject}

PARAGRAF:
{paragraph}

SORU: {question}
{options_text}

KRİTERLER (ethics_check):
1. OLUMSUZ ÇAĞRIŞIM: Herhangi bir birey veya grup hakkında olumsuz çağrışım var mı?
   - Cinsiyet, ırk, etnisite, din, engellilik, sosyo-ekonomik durum
   - Stereotipleştirme veya genelleme
2. DIŞLAYICI İFADE: Herhangi bir grubu dışlayan veya küçümseyen ifade var mı?
3. POLİTİK/İDEOLOJİK YÖNLENDİRME: Siyasi, dini veya ideolojik yönlendirme var mı?
4. TRAVMATİK İÇERİK: Yaş grubuna ({grade}. sınıf, {age_range} yaş) uygun olmayan içerik var mı?
   - Şiddet, korku, kaygı yaratan içerik
   - Yetişkin temaları
5. PEDAGOJİK UYGUNLUK: İçerik öğrencinin gelişimine uygun mu?

DERS BAZLI İSTİSNA:
- "Din Kültürü" dersinde dini şahsiyetler (Hz. Muhammed, Hz. Hatice vb.) hakkında
  "Peygamberimiz", "en güvenilir insan", "El-Emin", "örnek ahlak" gibi ifadeler
  MEB müfredatının doğal parçasıdır ve dini yönlendirme SAYILMAZ.
  Bu derste yalnızca diğer dinlere/inançlara hakaret, şiddete teşvik veya
  yaş grubuna uygunsuz detaylar FAIL sebebidir.
- Diğer derslerde (Türkçe, Fen, Sosyal, Matematik) dini içerik tarafsız
  ve nesnel olmalıdır; öznel yüceltme veya sahiplenici dil FAIL sebebidir.

ÖNEMLİ: Bu kontrol çok hassas. Küçük bir şüphe bile FAIL tetiklemeli.
Ancak DERS BAZLI İSTİSNA kurallarını mutlaka uygula.
Etik ihlal → "Revizyon Zorunlu" etiketi anlamına gelir.

Değerlendirme:
- status: PASS veya FAIL
- score: 0-100 arası puan
- feedback: Kısa açıklama
- issues: Tespit edilen sorunlar listesi (FAIL ise)
- suggestions: İyileştirme önerileri
- affected_components: ["paragraph", "question_stem", "options"]
"""


# Check name mapping (Turkish)
CHECK_NAMES = {
    "html_technical": "HTML Yapı Kontrolü",
    "question_format": "Soru Formatı",
    "grade_level": "Sınıf Seviyesi Uygunluğu",
    "accuracy": "Bilimsel Doğruluk",
    "distractors": "Çeldirici Kalitesi",
    "turkish": "Türkçe Dil Bilgisi",
    "solvability": "Çözülebilirlik",
    "curriculum_alignment": "Müfredat Uyumu",
    "context_dependency": "Bağlam Bağımlılığı",
    "hint_chain_check": "İpucu Zinciri Kontrolü",
    "ethics_check": "Etik ve Tarafsızlık",
    "cognitive_progression_check": "Bilişsel Aşamalılık",
}


# ============================================================================
# BATCH VALIDATOR CLASS
# ============================================================================


class BatchValidator:
    """
    Batch validator that runs multiple validation checks efficiently.

    Optimization: Instead of 6-7 sequential LLM calls, this validator
    batches checks into 2 parallel calls:
    - Batch 1: Non-PDF checks (5 checks)
    - Batch 2: PDF-required checks (2 checks)

    Both batches run concurrently using asyncio.gather().
    """

    def __init__(
        self,
        client: "GeminiClient",
        model: str,
        cache_name: str | None = None,
    ):
        """
        Initialize the batch validator.

        Args:
            client: GeminiClient instance for API calls.
            model: Gemini model ID to use.
            cache_name: Cache name for PDF-required checks (optional).
                       If None, PDF-required checks will be skipped.
        """
        self.client = client
        self.model = model
        self.cache_name = cache_name

    async def validate(
        self,
        paragraph: str,
        question: str,
        options: dict[str, str],
        correct_answer: str,
        grade: int,
        required_checks: list[str] | None = None,
        distractor_strategies: list[str] | list[dict[str, str]] | None = None,
        is_context_template: bool = False,
        option_style: str | None = None,
        visual_requirement: str | None = None,
        template_semantics: str | None = None,
    ) -> BatchValidationResult:
        """
        Run validation checks in 2 batched LLM calls.

        The validator automatically detects the question format (standard vs inverse)
        and applies appropriate validation criteria.

        Args:
            paragraph: The educational paragraph (may be empty for inverse format).
            question: The question text.
            options: Dict with A, B, C, D options.
            correct_answer: The correct option letter.
            grade: Target grade level.
            required_checks: List of check types to run (default: all).
            distractor_strategies: Optional list of expected distractor strategy names
                                  from the template (e.g., ["yakin_anlam", "detay_tuzagi", "cok_genis"]).
            is_context_template: If True, paragraph may contain <table> HTML tags (allowed).
            option_style: Option style from template (e.g., "image_description").
                         When "image_description", validation is relaxed for visual options.

        Returns:
            BatchValidationResult with all check results.
        """
        if required_checks is None:
            required_checks = DEFAULT_REQUIRED_CHECKS
        self._distractor_strategies = distractor_strategies
        self._is_context_template = is_context_template
        self._option_style = option_style
        self._visual_requirement = visual_requirement
        self._template_semantics = template_semantics

        # Split checks into PDF vs non-PDF groups
        pdf_checks = [c for c in required_checks if c in PDF_REQUIRED_CHECKS]
        non_pdf_checks = [c for c in required_checks if c not in PDF_REQUIRED_CHECKS]

        logger.info(
            f"[BATCH_VALIDATOR] Running {len(required_checks)} checks: "
            f"{len(non_pdf_checks)} non-PDF, {len(pdf_checks)} PDF-required"
        )

        # Build options text dynamically (supports 4 or 5 options)
        options_text = "\n".join(
            f"{label}) {options.get(label, '')}"
            for label in sorted(options.keys())
        )

        # Determine option count and labels
        option_labels = sorted(options.keys())
        option_count = len(option_labels)
        option_labels_str = ", ".join(option_labels)

        # Prepare common data
        prompt_data = {
            "paragraph": paragraph,
            "question": question,
            "options_text": options_text,
            "correct_answer": correct_answer,
            "grade": grade,
            "option_count": option_count,
            "option_labels_str": option_labels_str,
        }

        # Build tasks for parallel execution
        tasks = []

        if non_pdf_checks:
            tasks.append(self._run_non_pdf_batch(prompt_data, non_pdf_checks))

        if pdf_checks and self.cache_name:
            tasks.append(self._run_pdf_batch(prompt_data, pdf_checks))
        elif pdf_checks and not self.cache_name:
            logger.warning(
                "[BATCH_VALIDATOR] PDF checks requested but no cache_name provided. "
                "Skipping PDF-required checks."
            )

        # Run batches in parallel
        if not tasks:
            return BatchValidationResult(passed=True, overall_score=100.0, checks={})

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge results
        all_checks: dict[str, BatchCheckResult] = {}

        for result in results:
            if isinstance(result, Exception):
                logger.error(f"[BATCH_VALIDATOR] Batch failed: {result}")
                continue
            if isinstance(result, dict):
                all_checks.update(result)

        if not all_checks:
            return BatchValidationResult(
                passed=False,
                overall_score=0.0,
                checks={},
            )

        # Calculate overall result
        passed = all(c.status == "PASS" for c in all_checks.values())
        avg_score = sum(c.score for c in all_checks.values()) / len(all_checks)

        result = BatchValidationResult(
            passed=passed,
            overall_score=avg_score,
            checks=all_checks,
        )

        logger.info(
            f"[BATCH_VALIDATOR] Result: passed={result.passed}, "
            f"score={result.overall_score:.1f}"
        )

        return result

    def _build_strategy_hint(self, strategies: list[dict], is_inverse: bool) -> str:
        """Build strategy hint for validator prompt.

        Args:
            strategies: List of strategy dicts with keys: ad, aciklama, tip, nasil
            is_inverse: Whether this is an INVERSE template (no paragraph)

        Returns:
            Formatted hint string for the validator prompt
        """
        if is_inverse:
            hint_lines = ["\n   BEKLENEN ÇELDİRİCİ STRATEJİLERİ (TERS MANTIK):"]
            hint_lines.append("")
            hint_lines.append("   DOĞRU CEVAP için (konuya UYMAYAN şık):")
            for s in strategies:
                ad = s.get("ad", "?")
                aciklama = s.get("aciklama", "")
                hint_lines.append(f"   - {ad.upper()}: {aciklama}")
            hint_lines.append("")
            hint_lines.append("   YANLIŞ CEVAPLAR için (konuya UYAN 3 şık):")
            hint_lines.append("   - Konuya doğrudan uygun mini-paragraflar")
            hint_lines.append("")
            hint_lines.append(
                "   NOT: TERS MANTIK - Doğru cevap konuya UYMAYAN, "
                "yanlış cevaplar konuya UYAN şıklardır!"
            )
            return "\n".join(hint_lines) + "\n"
        else:
            # Standard format - list all strategies together
            hint_lines = ["\n   BEKLENEN ÇELDİRİCİ STRATEJİLERİ (template'den):"]
            for s in strategies:
                ad = s.get("ad", "?")
                aciklama = s.get("aciklama", "")
                tip = s.get("tip", "")
                nasil = s.get("nasil", "")
                kacinilacaklar = s.get("kacinilacaklar", "")
                tip_label = f" [{tip}]" if tip else ""
                hint_lines.append(f"   - {ad.upper()}{tip_label}: {aciklama}")
                if nasil:
                    hint_lines.append(f"     Nasil: {nasil}")
                if kacinilacaklar:
                    hint_lines.append(f"     Kacinilacaklar: {kacinilacaklar}")
            hint_lines.append("")
            hint_lines.append("   NOT: Bir şıkta birden fazla strateji KOMBİNE edilebilir.")
            hint_lines.append("   Örnek: strategy: [\"KAVRAM_YANILGISI\", \"EKSIK_ANALIZ\"]")
            return "\n".join(hint_lines) + "\n"

    async def _run_batch(
        self,
        prompt: str,
        output_schema: type[BaseModel],
        checks: list[str],
        cache_name: str | None = None,
        system_instruction: str | None = None,
        label: str = "BATCH",
    ) -> dict[str, BatchCheckResult]:
        """Run a batch of validation checks via a single LLM call.

        Shared core for both PDF and non-PDF batches.
        """
        try:
            kwargs: dict = {
                "model": self.model,
                "prompt": prompt,
                "output_schema": output_schema,
            }
            if cache_name:
                kwargs["cache_name"] = cache_name
            if system_instruction:
                kwargs["system_instruction"] = system_instruction

            output = await self.client.generate(**kwargs)

            logger.debug(
                f"[{label} BATCH RESULT]\n{'='*60}\n"
                f"Checks evaluated: {checks}\n"
                f"Raw output model: {type(output).__name__}\n"
                f"{'='*60}"
            )

            results: dict[str, BatchCheckResult] = {}
            for check_type in checks:
                if hasattr(output, check_type):
                    check_result: SingleCheckResult = getattr(output, check_type)
                    results[check_type] = BatchCheckResult(
                        check_type=check_type,
                        check_name=CHECK_NAMES.get(check_type, check_type),
                        status=check_result.status,
                        score=check_result.score,
                        feedback=check_result.feedback,
                        issues=check_result.issues,
                        suggestions=check_result.suggestions,
                        affected_components=list(check_result.affected_components),
                    )
                    logger.debug(
                        f"[CHECK: {check_type}] {check_result.status} "
                        f"(score={check_result.score})\n"
                        f"  Feedback: {check_result.feedback}\n"
                        f"  Issues: {check_result.issues}\n"
                        f"  Suggestions: {check_result.suggestions}\n"
                        f"  Affected: {check_result.affected_components}"
                    )
            return results

        except Exception as e:
            logger.error(f"[BATCH_VALIDATOR] {label} batch failed: {e}")
            return {
                check: BatchCheckResult(
                    check_type=check,
                    check_name=CHECK_NAMES.get(check, check),
                    status="FAIL",
                    score=0,
                    feedback=f"API hatası: {e}",
                    issues=["Doğrulama sırasında hata oluştu"],
                    suggestions=["Tekrar deneyin"],
                )
                for check in checks
            }

    async def _run_non_pdf_batch(
        self,
        prompt_data: dict,
        checks: list[str],
    ) -> dict[str, BatchCheckResult]:
        """Run the non-PDF batch (6 checks in 1 call)."""
        is_inverse = not prompt_data.get("paragraph")

        # Build distractor strategies hint for the prompt
        strategies = getattr(self, "_distractor_strategies", None)
        if strategies:
            if isinstance(strategies[0], dict):
                hint = self._build_strategy_hint(strategies, is_inverse)
            else:
                strategy_strs = []
                for s in strategies:
                    if isinstance(s, list):
                        strategy_strs.append(" + ".join(s))
                    else:
                        strategy_strs.append(s)
                hint = (
                    "\n   BEKLENEN STRATEJİLER "
                    f"(template'den): {', '.join(strategy_strs)}\n"
                )
        else:
            hint = ""
        template_semantics_hint = getattr(self, "_template_semantics", None) or ""

        # Paraphrase policy: grade-aware. 2. sınıfta birebir kopya kabul edilebilir
        # (şablon aksini söylemiyorsa). 3+ sınıflarda eş anlamlı yeniden yazım beklenir.
        _grade = prompt_data.get("grade", 5)
        try:
            _grade_num = int(_grade)
        except Exception:
            _grade_num = 5
        if _grade_num <= 2:
            paraphrase_policy = (
                "EŞ ANLAMLI KULLANIM KONTROLÜ (2. SINIF — GEVŞEK):\n"
                "   - 2. sınıf seviyesinde doğru cevap metindeki bir cümleyle AYNI olabilir.\n"
                "   - Birebir örtüşme TEK BAŞINA FAIL sebebi DEĞİLDİR.\n"
                "   - Sadece çeldiriciler metinle çelişmelidir."
            )
        else:
            paraphrase_policy = (
                "EŞ ANLAMLI KULLANIM KONTROLÜ (MEB-ÖSYM TARZI — SERT KURAL):\n"
                "   - Doğru cevap paragraftaki/tablodaki/bağlamdaki herhangi bir cümleyle NEREDEYSE kelimesi kelimesine aynı mı?\n"
                "   - %85+ kelime örtüşmesi varsa → score -= 40, status: FAIL, feedback: \"Doğru cevap birebir kopyalanmış — YASAK\"\n"
                "   - %70-84 kelime örtüşmesi varsa → score -= 15, feedback ver ama FAIL YAPMA (uyarı seviyesi)\n"
                "   - NOT: Özel isimler ve bilimsel terimler örtüşme hesabına DAHİL EDİLMEMELİ.\n"
                "   - Bilimsel terim korunmalı (teleskop→mercekli araç YANLIŞ)."
            )

        # Visual requirement hint for answer_critical templates
        visual_req = getattr(self, "_visual_requirement", None)
        if visual_req == "answer_critical":
            visual_requirement_hint = (
                "⚠️ BU SORU ANSWER-CRITICAL GÖRSEL ŞABLONU! Soru ancak görsel + paragraf birlikte "
                "çözülür. 'Görsel yok, soru eksik' gibi FAIL VERME — görsel pipeline tarafından "
                "daha sonra üretilecek. Soru kökü görsele atıf yapıyorsa (örn 'görseldeki', "
                "'şekle göre') bu DOĞRU tasarımdır."
            )
        else:
            visual_requirement_hint = "(bu soru answer-critical değil — klasik çözülebilirlik kriteri uygula)"

        prompt = NON_PDF_BATCH_PROMPT.format(
            **prompt_data,
            distractor_strategies_hint=hint,
            visual_requirement_hint=visual_requirement_hint,
            paraphrase_policy=paraphrase_policy,
            template_semantics_hint=template_semantics_hint,
        )

        # For context templates: inject note that table tags are allowed in paragraph
        if getattr(self, "_is_context_template", False):
            context_note = (
                "\n\n⚠️ BAĞLAM TEMELLİ SORU: Bu soru bir BAĞLAM (senaryo+tablo) üzerinden "
                "sorulmaktadır. Paragraf alanında <table>, <tr>, <th>, <td> gibi HTML tablo "
                "etiketleri NORMALDIR ve html_technical kontrolünde PASS verilmelidir. "
                "html_technical kontrolünde SADECE soru kökündeki yasak tag'leri kontrol et, "
                "paragraftaki tablo etiketlerini GÖRMEZDEN GEL.\n"
                "Ayrıca question_format kontrolünde: paragraf alanı bir BAĞLAM metnidir "
                "(senaryo + veri tablosu), standart paragraf formatında olmayabilir — bu normaldir."
            )
            prompt = prompt + context_note

        # For headline_title / short_title style: relax verbatim/similarity checks
        # Title options naturally share words with the paragraph (e.g., "Çiçeklerin Büyümesi")
        if getattr(self, "_option_style", None) in ("headline_title", "short_title"):
            title_note = (
                "\n\n⚠️ BAŞLIK SORUSU: Bu soruda şıklar KISA BAŞLIK ifadeleridir (1-5 kelime). "
                "Başlıklar doğal olarak paragraftaki anahtar kelimelerle örtüşür — bu beklenen "
                "bir durumdur ve birebir kopyalama SAYILMAZ.\n"
                "- grade_level kontrolünde: Eş anlamlı/birebir kopyalama kontrolünü başlık "
                "şıklarına UYGULAMA. Başlık 1-5 kelime olduğundan paragrafla kelime paylaşımı "
                "normaldir. Bu kriteri PASS ver.\n"
                "- distractors kontrolünde: Başlıkların kısa olması nedeniyle kelime bazlı "
                "benzerlik yerine ANLAMSAL farkı değerlendir."
            )
            prompt = prompt + title_note

        # For image_description style: relax language/similarity checks
        if getattr(self, "_option_style", None) == "image_description":
            image_note = (
                "\n\n⚠️ GÖRSEL ŞIKLI SORU: Bu soruda şıklar GÖRSEL TASVİRDİR — öğrenciye "
                "metin olarak gösterilmez, her şık bir GÖRSEL (grafik/tablo/fotoğraf/mockup) "
                "olarak üretilecektir. Bu nedenle:\n"
                "- distractors kontrolünde: 'yakın anlam çeldirici' ve 'dil yapısı eşitliği' "
                "kontrollerini ESNEK uygula. Şıklar veri listesi veya görsel tasvir olduğundan "
                "metin bazlı benzerlik bekleme. Veriler/içerikler arasındaki KAVRAMSAL farkı "
                "değerlendir.\n"
                "- grade_level kontrolünde: Şık metinleri görsel üretim talimatıdır, öğrenci "
                "dili olması gerekmez — şık dil seviyesini KONTROL ETME.\n"
                "- solvability kontrolünde: Şıklar görsel olarak sunulacak, metin olarak değil. "
                "Görsel farklılıkları değerlendir."
            )
            prompt = prompt + image_note

        logger.debug(
            f"[NON-PDF BATCH PROMPT]\n"
            f"{'='*80}\n"
            f"Checks: {checks}\n"
            f"Strategy hint included: {bool(hint)}\n"
            f"{'-'*80}\n"
            f"FULL VALIDATION PROMPT:\n{prompt}\n"
            f"{'='*80}"
        )

        return await self._run_batch(
            prompt=prompt,
            output_schema=NonPDFBatchOutput,
            checks=checks,
            system_instruction=VALIDATOR_SYSTEM_PROMPT,
            label="Non-PDF",
        )

    async def cross_validate_group(
        self,
        context_text: str,
        questions: list[dict],
    ) -> dict[str, BatchCheckResult]:
        """Run LLM-based cross-question validation for a context group.

        Args:
            context_text: The shared context text.
            questions: List of question dicts with keys:
                question, options (dict), correct_answer.

        Returns:
            Dict of check results keyed by check type.
        """
        # Build questions text
        q_lines = []
        for i, q in enumerate(questions, 1):
            q_lines.append(f"Soru {i}: {q.get('question', '')}")
            opts = q.get("options", {})
            for letter in ["A", "B", "C", "D"]:
                marker = " (DOGRU)" if letter == q.get("correct_answer") else ""
                q_lines.append(f"  {letter}) {opts.get(letter, '')}{marker}")
            q_lines.append("")

        prompt = CROSS_QUESTION_PROMPT.format(
            context_text=context_text,
            questions_text="\n".join(q_lines),
        )

        return await self._run_batch(
            prompt=prompt,
            output_schema=CrossQuestionCheckOutput,
            checks=["overlap_check", "diversity_check", "hint_chain_check"],  # cognitive_progression_check pasife alındı
            system_instruction=VALIDATOR_SYSTEM_PROMPT,
            label="Cross-Q",
        )

    async def check_context_dependency(
        self,
        context_text: str,
        question: str,
        options: dict[str, str],
        correct_answer: str,
    ) -> dict[str, BatchCheckResult]:
        """Check if a question truly depends on the context text.

        Uses a single LLM call to verify that the question cannot be
        answered with general knowledge alone.

        Args:
            context_text: The shared context text (scenario + data).
            question: The question stem.
            options: Dict with A, B, C, D option texts.
            correct_answer: The correct option letter.

        Returns:
            Dict with 'context_dependency' check result.
        """
        # Build options text dynamically (supports 3, 4, or 5 options)
        options_lines = [f"{l}) {options.get(l, '')}" for l in sorted(options.keys()) if options.get(l)]
        options_text = "\n".join(options_lines)

        prompt = CONTEXT_DEPENDENCY_PROMPT.format(
            context_text=context_text,
            question=question,
            options_text=options_text,
            correct_answer=correct_answer,
        )

        return await self._run_batch(
            prompt=prompt,
            output_schema=ContextDependencyOutput,
            checks=["context_dependency"],
            system_instruction=VALIDATOR_SYSTEM_PROMPT,
            label="CtxDep",
        )

    # Mapping from normalized subject codes to display names for ethics prompt
    _SUBJECT_DISPLAY_NAMES: dict[str, str] = {
        "din_kültürü": "Din Kültürü",
        "fen_bilimleri": "Fen Bilimleri",
        "sosyal_bilgiler": "Sosyal Bilgiler",
        "türkçe": "Türkçe",
        "turkce": "Türkçe",
        "matematik": "Matematik",
    }

    async def check_ethics(
        self,
        paragraph: str,
        question: str,
        options: dict[str, str],
        subject: str = "",
        grade: int = 5,
    ) -> dict[str, BatchCheckResult]:
        """Check question for ethical issues and impartiality.

        Uses a single LLM call to verify that the question does not contain
        negative associations, exclusionary language, political/ideological
        bias, traumatic content, or pedagogically inappropriate material.

        Args:
            paragraph: The paragraph text (may be empty for inverse templates).
            question: The question stem.
            options: Dict with A, B, C, D option texts.
            subject: The school subject (e.g. "Din Kültürü", "din_kültürü").
            grade: Target grade level (used for age-appropriate content check).

        Returns:
            Dict with 'ethics_check' check result.
        """
        from .generators.html_generator import grade_to_age_range
        # Convert normalized subject code to display name
        display_subject = self._SUBJECT_DISPLAY_NAMES.get(subject, subject)
        # Build options text dynamically (supports 3, 4, or 5 options)
        options_lines = []
        for label in sorted(options.keys()):
            opt_text = options.get(label, "")
            if opt_text:  # skip empty options
                options_lines.append(f"{label}) {opt_text}")
        options_text = "\n".join(options_lines)

        prompt = ETHICS_CHECK_PROMPT.format(
            paragraph=paragraph or "(paragraf yok — ters mantık formatı)",
            question=question,
            options_text=options_text,
            subject=display_subject or "(belirtilmemiş)",
            grade=grade,
            age_range=grade_to_age_range(grade),
        )

        return await self._run_batch(
            prompt=prompt,
            output_schema=EthicsCheckOutput,
            checks=["ethics_check"],
            system_instruction=VALIDATOR_SYSTEM_PROMPT,
            label="Ethics",
        )

    async def _run_pdf_batch(
        self,
        prompt_data: dict,
        checks: list[str],
    ) -> dict[str, BatchCheckResult]:
        """Run the PDF-required batch (2 checks in 1 call)."""
        prompt = PDF_BATCH_PROMPT.format(**prompt_data)
        logger.debug(
            f"[PDF BATCH PROMPT]\n"
            f"{'='*80}\n"
            f"Checks: {checks}\n"
            f"Cache: {self.cache_name}\n"
            f"{'-'*80}\n"
            f"FULL VALIDATION PROMPT:\n{prompt}\n"
            f"{'='*80}"
        )

        return await self._run_batch(
            prompt=prompt,
            output_schema=PDFBatchOutput,
            checks=checks,
            cache_name=self.cache_name,
            label="PDF",
        )


# ============================================================================
# CROSS-QUESTION VALIDATION (for context groups)
# ============================================================================


class CrossQuestionCheckOutput(BaseModel):
    """Output schema for cross-question validation."""

    overlap_check: SingleCheckResult = Field(
        ...,
        description="Sorular arasi icerik ortusme kontrolu",
    )
    diversity_check: SingleCheckResult = Field(
        ...,
        description="Soru cesitliligi kontrolu",
    )
    hint_chain_check: SingleCheckResult = Field(
        ...,
        description="Sorular arasi ipucu zinciri kontrolu",
    )
    cognitive_progression_check: SingleCheckResult = Field(
        ...,
        description="Bilissel asamalilik kontrolu",
    )


CROSS_QUESTION_PROMPT = """GÖREV: Aşağıdaki soru grubunu ÇAPRAZ kontrol et.

Bu sorular AYNI bağlam metni üzerinden üretilmiştir.
Her sorunun FARKLI bir yönü sorgulaması ve cevapların çakışmaması gerekir.

BAĞLAM METNİ:
{context_text}

SORULAR:
{questions_text}

═══════════════════════════════════════════════════════════════════
                    DEĞERLENDİRME KRİTERLERİ
═══════════════════════════════════════════════════════════════════

1. İÇERİK ÖRTÜŞME KONTROLÜ (overlap_check)
   - Farklı sorulardaki doğru cevaplar BİREBİR AYNI bilgiyi mi soruyor? (Aynı konunun farklı yönlerini sormak KABUL EDİLEBİLİR)
   - Bir sorunun çeldiricisi başka bir sorunun doğru cevabının BİREBİR AYNISI mı?
   - NOT: Aynı tablo/grafikten farklı sorular sormak NORMAL — önemli olan soruların farklı beceri/açıdan yaklaşması
   - FAIL sadece: İki soru TAMAMEN aynı şeyi soruyorsa (aynı soru kökü + aynı doğru cevap)

2. ÇEŞİTLİLİK KONTROLÜ (diversity_check)
   - Sorular en az 2 FARKLI beceri seviyesinden mi? (ör: veri okuma + çıkarım, veya karşılaştırma + değerlendirme)
   - NOT: 3-4 soruluk gruplarda bazı soruların benzer beceri ölçmesi NORMAL — hepsinin tamamen farklı olması beklenmez
   - FAIL sadece: TÜM sorular birebir aynı beceriyi ölçüyorsa (ör: hepsi "en büyük hangisi" sorusu)
   - PASS: En az 1 soru diğerlerinden farklı bir beceri ölçüyorsa

3. İPUCU ZİNCİRİ KONTROLÜ (hint_chain_check)
   - 1. sorunun doğru cevabını bilmek 2. soruyu DOĞRUDAN çözmeye yeter mi?
   - NOT: Dolaylı ilişki KABUL EDİLEBİLİR — sorunlar birbirinden bağımsız cevaplanabiliyorsa PASS
   - FAIL sadece: Bir sorunun cevabı doğrudan başka sorunun cevabını ELE VERİYORSA

4. BİLİŞSEL AŞAMALILIK KONTROLÜ (cognitive_progression_check)
   - Sorular basit → karmaşık sırayla ilerliyor mu?
   - 1. soru: veri okuma/çıkarım (KB1-KB2 alt seviye) olmalı
   - Son soru: değerlendirme/sentez (KB2 üst seviye veya KB3) olmalı
   - Kolay soru en sonda, zor soru en başta ise → FAIL
   - Tüm sorular aynı zorlukta ise → PASS (uyarı vermek yeterli)
   - Örnek PASS: 1. soru tablodan veri okuma, 2. soru karşılaştırma/yorum
   - Örnek FAIL: 1. soru sentez/değerlendirme, 2. soru basit veri okuma

Her kriter için:
- status: PASS veya FAIL
- score: 0-100 arası puan
- feedback: Kısa açıklama
- issues: Tespit edilen sorunlar listesi
- suggestions: İyileştirme önerileri
- affected_components: ["question_stem", "options"]
"""


# ============================================================================
# ACTIONABLE VALIDATION FEEDBACK
# ============================================================================


def enrich_validation_feedback(
    validation_result: BatchValidationResult,
    options: dict[str, str],
    correct_answer: str,
    question: str,
    grade: int,
    paragraph: str = "",
) -> str:
    """
    Enrich validation feedback with option-specific repair instructions.

    Instead of generic "distractor quality failed", produces actionable
    guidance like "Option B is too broad, narrow it to match the topic scope".

    Args:
        validation_result: The batch validation result.
        options: Dict with A, B, C, D option texts.
        correct_answer: The correct option letter (e.g., "A").
        question: The question stem text.
        grade: Target grade level.
        paragraph: The paragraph text (may be empty for inverse templates).

    Returns:
        Enriched feedback string with option-specific repair instructions.
        Empty string if all checks passed.
    """
    failed_checks = validation_result.failed_checks
    if not failed_checks:
        return ""

    correct_text = options.get(correct_answer, "")
    distractor_letters = [l for l in sorted(options.keys()) if l != correct_answer]

    sections: list[str] = []

    for check in failed_checks:
        ct = check.check_type
        lines: list[str] = []

        if ct == "distractors":
            lines.append(f"[FAIL] {check.check_name} — Secenek bazli analiz:")
            lines.append(f"  Dogru cevap: {correct_answer}) {correct_text}")
            for letter in distractor_letters:
                text = options.get(letter, "")
                lines.append(f"  Celdirici {letter}) {text}")
            for issue in check.issues:
                lines.append(f"  - Sorun: {issue}")
            # Add option-specific guidance based on issues
            for issue in check.issues:
                issue_lower = issue.lower()
                for letter in distractor_letters:
                    opt_text = options.get(letter, "")
                    if opt_text.lower() in issue_lower or letter.lower() in issue_lower:
                        if any(w in issue_lower for w in ["genis", "genel", "soyut", "broad"]):
                            lines.append(
                                f"  → Sik {letter} '{opt_text}' cok genis — "
                                f"dogru cevapla ayni ozgulluk seviyesine daralt: "
                                f"'{correct_text}'"
                            )
                        elif any(w in issue_lower for w in ["kolay", "bariz", "acik", "elenir"]):
                            lines.append(
                                f"  → Sik {letter} '{opt_text}' kolayca elenebilir — "
                                f"paragrafla daha iliskili ve inandirici yap"
                            )
                        elif any(w in issue_lower for w in ["benzer", "ayni", "tekrar"]):
                            lines.append(
                                f"  → Sik {letter} '{opt_text}' dogru cevaba cok benzer — "
                                f"farkli bir celdirici stratejisi kullan"
                            )
            for suggestion in check.suggestions:
                lines.append(f"  - Oneri: {suggestion}")

        elif ct == "grade_level":
            lines.append(f"[FAIL] {check.check_name} — {grade}. sinif icin uygun degil:")
            for issue in check.issues:
                lines.append(f"  - Sorun: {issue}")
            lines.append(
                f"  → {grade}. sinif kelime hazinesine uygun daha basit "
                f"ifadeler kullan. Karmasik akademik terimleri gunluk dile cevir."
            )
            for suggestion in check.suggestions:
                lines.append(f"  - Oneri: {suggestion}")

        elif ct == "solvability":
            lines.append(f"[FAIL] {check.check_name} — Cozulebilirlik sorunu:")
            lines.append(f"  Soru: {question}")
            for letter in sorted(options.keys()):
                text = options.get(letter, "")
                marker = " (dogru)" if letter == correct_answer else ""
                lines.append(f"  {letter}) {text}{marker}")
            for issue in check.issues:
                lines.append(f"  - Sorun: {issue}")
            if any("birden fazla" in i.lower() or "belirsiz" in i.lower() for i in check.issues):
                lines.append(
                    "  → Birden fazla dogru cevap olasiligi var. "
                    "Celdiricileri dogru cevaptan net sekilde ayir."
                )
            if any("dis bilgi" in i.lower() or "paragraf" in i.lower() for i in check.issues):
                lines.append(
                    "  → Soru sadece paragraftaki bilgiyle cevaplanabilir olmali. "
                    "Dis bilgi gerektiren unsurlari kaldir."
                )
            for suggestion in check.suggestions:
                lines.append(f"  - Oneri: {suggestion}")

        elif ct == "turkish":
            lines.append(f"[FAIL] {check.check_name} — Dil hatalari:")
            for issue in check.issues:
                lines.append(f"  - Hata: {issue}")
            for suggestion in check.suggestions:
                lines.append(f"  - Duzeltme onerisi: {suggestion}")

        elif ct == "html_technical":
            lines.append(f"[FAIL] {check.check_name} — Yasak HTML tag'leri:")
            for issue in check.issues:
                lines.append(f"  - {issue}")
            lines.append(
                "  → Sadece <b>, <u>, <br> tag'leri kullan. "
                "<ol>, <li>, <ul>, <div>, <span>, <p> YASAK."
            )
            for suggestion in check.suggestions:
                lines.append(f"  - Oneri: {suggestion}")

        elif ct == "context_dependency":
            lines.append(f"[FAIL] {check.check_name} — Baglam bagimliligi:")
            for issue in check.issues:
                lines.append(f"  - {issue}")
            lines.append(
                "  → Soru baglam metnindeki SPESIFIK veriye dayanan "
                "bir soru olmali. Genel bilgiyle cevaplanabilecek sorular YASAK."
            )
            for suggestion in check.suggestions:
                lines.append(f"  - Oneri: {suggestion}")

        elif ct == "ethics_check":
            lines.append(f"[FAIL] {check.check_name} — Etik/tarafsizlik ihlali:")
            for issue in check.issues:
                lines.append(f"  - {issue}")
            lines.append(
                "  → Icerik TAMAMEN tarafsiz ve yas grubuna uygun olmali. "
                "Olumsuz cagrisim, dislayici ifade, politik yonlendirme "
                "ve travmatik icerik YASAKTIR."
            )
            for suggestion in check.suggestions:
                lines.append(f"  - Oneri: {suggestion}")

        else:
            # Generic fallback for other check types (question_format, accuracy, etc.)
            lines.append(f"[FAIL] {check.check_name}:")
            lines.append(f"  {check.feedback}")
            for issue in check.issues:
                lines.append(f"  - Sorun: {issue}")
            for suggestion in check.suggestions:
                lines.append(f"  - Oneri: {suggestion}")

        if lines:
            sections.append("\n".join(lines))

    result = "\n\n".join(sections) + "\n" if sections else ""
    logger.debug(
        f"[ENRICH FEEDBACK]\n{'='*60}\n"
        f"Failed checks: {[c.check_type for c in failed_checks]}\n"
        f"Correct answer: {correct_answer}) {options.get(correct_answer, '')}\n"
        f"Generated enriched feedback:\n{result}\n"
        f"{'='*60}"
    )
    return result
