"""
7 baslikli YAML sablonlarini yukleyen ve her chain icin
gerekli basliklari paketleyen modul.

Referans yapi: kareli_zeminde_baslangic_hedef_rota_secme.yaml
7 baslik: meta, context, header_template, format, dogru_cevap, distractors, use_shared_strategies

Ek olarak:
- tymm_uyum_kurallari (opsiyonel ust-baslik)
- context.generation.ana_gorsel / sik_gorseli (gorsel kurallari ayristirmasi)
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# ParsedTemplate: 7 basligin normalize edilmis hali
# ---------------------------------------------------------------------------

class ParsedTemplate(BaseModel):
    """7 baslikli YAML sablonunun normalize edilmis temsili."""

    raw: dict = Field(description="Orijinal YAML verisi")

    # 7 ust-duzey baslik
    meta: dict = Field(default_factory=dict)
    context: dict = Field(default_factory=dict)
    header_template: str = Field(default="")
    format_spec: dict = Field(default_factory=dict)
    dogru_cevap: dict = Field(default_factory=dict)
    distractors: dict = Field(default_factory=dict)
    use_shared_strategies: bool = Field(default=False)

    # Opsiyonel: TYMM uyum kurallari
    tymm_uyum_kurallari: dict = Field(default_factory=dict)

    # Opsiyonel: gorsel kurallari (YAML'daki gorsel ust-basligi)
    gorsel: dict = Field(default_factory=dict)

    # Opsiyonel: izinli icerikler (kavramlar, beceriler, soru_islemleri)
    izinli_icerikler: dict = Field(default_factory=dict)

    # Turetilen kolaylik alanlari (parse sirasinda hesaplanir)
    sinif_seviyesi: int = Field(default=2)
    image_type: str = Field(default="ortak_gorsel")
    has_visual_options: bool = Field(default=False)
    requires_visual: bool = Field(default=True)
    question_count: int = Field(default=1)
    option_count: int = Field(default=3)
    option_labels: list[str] = Field(default_factory=lambda: ["A", "B", "C"])
    options_style: str = Field(default="numeric_only")

    # Gorsel motoru: "generative" (Gemini Image), "geometric_deterministic"
    # veya "solid_3d_deterministic"
    # Auto-detect: 3D cisim sinyalleri "solid_3d_deterministic"; kareli/birimkare/noktali
    # veya acik 2D geometri sinyalleri "geometric_deterministic" olur.
    # YAML'da gorsel.ana_gorsel.engine veya top-level visual_engine ile ezilebilir.
    visual_engine: str = Field(default="generative")

    # Baglamli soru ayristirma parametreleri
    has_reference_questions: bool = Field(default=False)
    referans_sorular: list[dict] = Field(default_factory=list)
    varyant_tanimlari: dict = Field(default_factory=dict)
    ozel_kurallar: list[str] = Field(default_factory=list)
    havuzlar: dict = Field(default_factory=dict)
    sabit_ve_degisen: dict = Field(default_factory=dict)
    ornek_senaryolar: list[dict] = Field(default_factory=list)
    celdirici_notlari: list[str] = Field(default_factory=list)
    gorsel_notlari: list[str] = Field(default_factory=list)

    model_config = {"arbitrary_types_allowed": True}


# Tum sablonlara uygulanacak ortak tutarlilik guvenceleri.
SHARED_CRITICAL_CONSISTENCY_RULES = [
    (
        "Artis, azalis, eksilme, ekleme, cikarma, transfer, esitleme veya donusum "
        "iceren sorularda; cozum icin gerekli tum kritik miktarlar gorselde ve/veya "
        "metinde eksiksiz, izlenebilir ve birbiriyle tutarli gosterilmelidir. "
        "Yalnizca sorulan bilinmez gizli kalabilir."
    ),
    (
        "Ozellikle sayma gerektiren artis-azalis sorularinda; her asamadaki onceki, "
        "sonraki, eklenen, cikarilan, aktarılan, esitlenen veya kalan miktarlarin "
        "tamami ogrencinin takip edebilecegi bicimde temsil edilmelidir. Ara adimlar "
        "atlanamaz, tek bir asama bile muğlak birakilamaz."
    ),
    (
        "Dogru cevap; gorsel ve metindeki miktar, sira, yon ve degisim bilgileriyle "
        "bire bir uyusmali; cevapla celisen, eksik birakan veya farkli sonuca goturen "
        "hicbir temsil bulunmamali."
    ),
    (
        "Ust metin tamamen bos veya yalnizca susleyici olmamali; cozum yoluna katki veren "
        "en az bir sayisal ya da iliskisel ipucu vermelidir. Ancak butun cozum verisini "
        "acik etmemeli; ogrencinin sonuca ulasmak icin mutlaka gorsele de bakmasi gerekmelidir."
    ),
    (
        "Soru, yalnizca ust metin veya paragraf okunarak cozulur hale gelmemelidir. "
        "Dogru cevaba ulasmak icin gorseldeki konum, etiket, sekil, parcalanis, sayi yerlesimi "
        "veya iliski mutlaka gerekli olmalidir; metin tek basina yeterli ipucu vermemelidir."
    ),
    (
        "Senaryo ve soru metinlerinde varsayilan kip genis/simdiki zaman olmalidir "
        "(ornek: 'tasiyor', 'ikram ediyor'). Ozel bir zaman vurgusu gerekmiyorsa "
        "gecmis zaman anlatimi (ornek: 'tasidi', 'ikram etti') tercih edilmemelidir."
    ),
    (
        "Geometri gorsellerinde nokta, kose veya dogru parcasi etiketleri (A, B, C, K, L, M gibi) "
        "ilgili noktayi acikca gosterecek kadar yakin olmali; ancak yazilar tam kose ustune "
        "oturmamali, cizgilere degmemeli ve kenarlardan az bir bosluk birakacak sekilde "
        "disariya offsetli yerlestirilmelidir."
    ),
    (
        "Aci olcusu sayisal olarak veriliyorsa metinde, gorselde ve seceneklerde derece sembolu "
        "(°) mutlaka kullanilmalidir. Ornek: 40 yerine 40° yazilmalidir."
    ),
    (
        "Gorseller fotografik veya gercekci render yerine ilkokul ogrencilerine uygun, sade, temiz ve "
        "acikca ilustratif bir egitsel dilde uretilmelidir. Amac siyah, duz, kupkuru cizgilerden uzaklasmak; "
        "ama gereksiz kadar renkli, suslu veya karmasik bir gorunum olusturmamak olmalidir. Renk kullanimi "
        "olculu, dengeli ve okunurlugu destekleyici olmali; nesneler kolay ayirt edilir kalmali. Asiri detay, "
        "dramatik isik, sinematik efekt, yetiskinlere yonelik gercekcilik veya dikkat dagitan dekoratif asirilik "
        "kullanilmamalidir."
    ),
]


def _append_shared_consistency_rules(sections: list[str]) -> None:
    sections.append("## ORTAK KRITIK TUTARLILIK KURALLARI")
    for rule in SHARED_CRITICAL_CONSISTENCY_RULES:
        sections.append(f"- {rule}")
    sections.append("")


# ---------------------------------------------------------------------------
# YAML tolerans / normalize yardimcilari
# ---------------------------------------------------------------------------

def _normalize_varyantlar(value: Any) -> list[Any]:
    """Farkli varyant yazimlarini tek bir liste formatina toplar."""
    if value is None:
        return []

    if isinstance(value, list):
        return value

    if isinstance(value, str):
        return [value]

    if isinstance(value, dict):
        # Bazi YAML'larda varyant basligi altinda dogrudan ad/tip/aciklama gibi
        # alanlar aciliyor. Bunu tek varyantlik liste olarak kabul ederiz.
        if any(key in value for key in ("ad", "tip", "aciklama", "odak")):
            return [dict(value)]

        # Varyant bilgisi bir katman daha derine acilmissa yine bulup normalize et.
        for alias in ("varyantlar", "varyant"):
            nested = _normalize_varyantlar(value.get(alias))
            if nested:
                return nested

    return []


def _first_non_empty_varyantlar(*candidates: Any) -> list[Any]:
    """Ilk dolu varyant kaynagini bulur."""
    for candidate in candidates:
        normalized = _normalize_varyantlar(candidate)
        if normalized:
            return normalized
    return []


def _normalize_question_variants(context: dict, data: dict) -> dict:
    """varyant/varyantlar alanlarini toleransli bicimde ilk soruya tasir."""
    questions = list(context.get("questions", []))
    if not questions:
        return context

    first_question = dict(questions[0])
    normalized_varyantlar = _first_non_empty_varyantlar(
        first_question.get("varyantlar"),
        first_question.get("varyant"),
        context.get("varyantlar"),
        context.get("varyant"),
        data.get("varyantlar"),
        data.get("varyant"),
    )

    if not normalized_varyantlar:
        return context

    first_question["varyantlar"] = normalized_varyantlar
    first_question.pop("varyant", None)
    questions[0] = first_question

    normalized_context = dict(context)
    normalized_context["questions"] = questions
    return normalized_context


# ---------------------------------------------------------------------------
# Normalizasyon yardimcilari
# ---------------------------------------------------------------------------

_TURKISH_TO_ASCII = str.maketrans({
    "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
    "Ç": "C", "Ğ": "G", "İ": "I", "Ö": "O", "Ş": "S", "Ü": "U",
})


def _normalize_soru_kokleri(questions: list[dict]) -> list[dict]:
    """soru_koku (tekil) varsa soru_kokleri (cogul) listesine sarar."""
    for q in questions:
        if "soru_kokleri" not in q and "soru_koku" in q:
            q["soru_kokleri"] = [q.pop("soru_koku")]
            logger.info("soru_koku → soru_kokleri donusumu uygulandi")
    return questions


def _normalize_image_type(val: str) -> str:
    """image_type Turkce karakter ve eski enum degerlerini normalize eder."""
    normalized = val.translate(_TURKISH_TO_ASCII)
    mapping = {
        "gorsel_gerekli": "ortak_gorsel",
        "tek_gorsel": "ortak_gorsel",
    }
    return mapping.get(normalized, normalized)


def _normalize_difficulty(val: Any) -> Any:
    """zorluk_seviyesi object/list ise scalar string'e donusturur."""
    if isinstance(val, dict):
        return val.get("duzey", val.get("genel", "orta"))
    if isinstance(val, list):
        # list of dicts: ilk ogedeki duzey veya genel deger
        for item in val:
            if isinstance(item, dict):
                if "duzey" in item:
                    return item["duzey"]
                if "genel" in item:
                    return item["genel"]
        return "orta"
    return val


def _normalize_option_labels(labels: list[str]) -> list[str]:
    """Parantezli etiketleri temizler: A) → A"""
    return [label.rstrip(")").strip() for label in labels]


def _find_key(data: dict, *candidates: str) -> Any:
    """Birden fazla key adayindan ilk bulunani dondurur, bulamazsa None."""
    for key in candidates:
        if key in data:
            return data[key]
    return None


# Gorsel gerektirmeyen (metin tabanli) option style'lari icin anahtar kelimeler.
_NON_VISUAL_STYLE_KEYWORDS = ("text", "numeric", "name", "symbolic", "sequence", "label", "reference")


# ---------------------------------------------------------------------------
# YAML yukleme ve parse
# ---------------------------------------------------------------------------

def _extract_baglamli_params(
    data: dict, context: dict, format_spec: dict,
) -> dict:
    """Baglamli YAML'lardaki zengin soru, varyant ve havuz verilerini extract eder.

    7 kavramsal parametre dondurur:
      referans_sorular, varyant_tanimlari, ozel_kurallar, havuzlar,
      sabit_ve_degisen, ornek_senaryolar, celdirici_notlari, gorsel_notlari,
      has_reference_questions
    """
    # ── 1. referans_sorular ──────────────────────────────────────────────
    referans_sorular: list[dict] = []
    for q in context.get("questions", []):
        ref: dict[str, Any] = {}
        for key in ("senaryo", "soru_koku", "secenekler", "dogru_cevap", "cozum", "varyant_adi"):
            if q.get(key):
                ref[key] = q[key]
        if ref:
            ref["slot"] = q.get("slot")
            ref["type"] = q.get("type")
            referans_sorular.append(ref)

    has_reference_questions = any(
        r.get("senaryo") or r.get("secenekler") or r.get("dogru_cevap")
        for r in referans_sorular
    )

    # ── 2. varyant_tanimlari ─────────────────────────────────────────────
    varyant_tanimlari: dict = {}

    top_varyantlar = data.get("varyantlar", {}) or data.get("varyant", {})
    if top_varyantlar:
        varyant_tanimlari["varyantlar"] = top_varyantlar

    varyant_bicimleri = format_spec.get("varyant_bicimleri", {})
    if varyant_bicimleri:
        varyant_tanimlari["varyant_bicimleri"] = varyant_bicimleri

    # ── 3. ozel_kurallar ─────────────────────────────────────────────────
    ozel_kurallar: list[str] = []
    for v_key, v_val in (top_varyantlar if isinstance(top_varyantlar, dict) else {}).items():
        if isinstance(v_val, dict) and v_val.get("ozel_kural"):
            ozel_kurallar.append(f"[{v_key}] {v_val['ozel_kural']}")
    for v_key, v_val in (varyant_bicimleri or {}).items():
        if isinstance(v_val, dict) and v_val.get("kritik_kural"):
            ozel_kurallar.append(f"[{v_key}] {v_val['kritik_kural']}")

    # ── 4. havuzlar ──────────────────────────────────────────────────────
    havuzlar: dict = {}
    if isinstance(top_varyantlar, dict):
        for v_val in top_varyantlar.values():
            if not isinstance(v_val, dict):
                continue
            if v_val.get("baglam_havuzu"):
                havuzlar.setdefault("baglam_havuzu", []).extend(v_val["baglam_havuzu"])
            if v_val.get("uygun_nesne_havuzu"):
                havuzlar.setdefault("nesne_havuzu", {}).update(v_val["uygun_nesne_havuzu"])
            if v_val.get("soru_koku_havuzu"):
                havuzlar.setdefault("soru_koku_havuzu", []).extend(v_val["soru_koku_havuzu"])
            if v_val.get("soru_koku_ornekleri"):
                havuzlar.setdefault("soru_koku_havuzu", []).extend(v_val["soru_koku_ornekleri"])

    # ── 5. sabit_ve_degisen ──────────────────────────────────────────────
    sabit_ve_degisen: dict = {"sabit": [], "degisen": []}
    if isinstance(top_varyantlar, dict):
        for v_key, v_val in top_varyantlar.items():
            if not isinstance(v_val, dict):
                continue
            for s in v_val.get("sabit_kalanlar", []):
                sabit_ve_degisen["sabit"].append(f"[{v_key}] {s}")
            for d in v_val.get("degisenler", []):
                sabit_ve_degisen["degisen"].append(f"[{v_key}] {d}")
    if not sabit_ve_degisen["sabit"] and not sabit_ve_degisen["degisen"]:
        sabit_ve_degisen = {}

    # ── 6. ornek_senaryolar ──────────────────────────────────────────────
    ornek_senaryolar: list[dict] = []
    for q in context.get("questions", []):
        if q.get("senaryo"):
            ornek_senaryolar.append({
                "kaynak": f"Slot {q.get('slot', '?')}",
                "senaryo": q["senaryo"],
            })
    if isinstance(top_varyantlar, dict):
        for v_key, v_val in top_varyantlar.items():
            if isinstance(v_val, dict) and v_val.get("ornek_senaryo"):
                ornek_senaryolar.append({
                    "kaynak": v_key,
                    "senaryo": v_val["ornek_senaryo"],
                })

    # ── 7. celdirici_notlari + gorsel_notlari ────────────────────────────
    celdirici_notlari: list[str] = []
    gorsel_notlari: list[str] = []
    if isinstance(top_varyantlar, dict):
        for v_key, v_val in top_varyantlar.items():
            if not isinstance(v_val, dict):
                continue
            for n in v_val.get("celdirici_notu", []):
                celdirici_notlari.append(f"[{v_key}] {n}")
            if v_val.get("gorsel_notu"):
                gorsel_notlari.append(f"[{v_key}] {v_val['gorsel_notu']}")

    return {
        "has_reference_questions": has_reference_questions,
        "referans_sorular": referans_sorular,
        "varyant_tanimlari": varyant_tanimlari,
        "ozel_kurallar": ozel_kurallar,
        "havuzlar": havuzlar,
        "sabit_ve_degisen": sabit_ve_degisen,
        "ornek_senaryolar": ornek_senaryolar,
        "celdirici_notlari": celdirici_notlari,
        "gorsel_notlari": gorsel_notlari,
    }


def _parse_sinif_seviyesi(val) -> int:
    """sinif_seviyesi alanini int'e donusturur. '2. Sinif', '2', 2 gibi formatlari destekler."""
    import re as _re
    if isinstance(val, int):
        return val
    m = _re.search(r'\d+', str(val))
    return int(m.group()) if m else 2


def load_and_parse_template(yaml_path: str | Path) -> ParsedTemplate:
    """7 baslikli YAML sablonunu yukler ve ParsedTemplate'e donusturur."""
    path = Path(yaml_path)
    if not path.exists():
        raise FileNotFoundError(f"YAML bulunamadi: {path}")

    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError(f"YAML ust duzey dict olmali: {path}")

    meta = dict(data.get("meta", {})) if isinstance(data.get("meta"), dict) else {}
    context = dict(data.get("context", {})) if isinstance(data.get("context"), dict) else {}
    # context.generation'ı normalize et
    if "generation" in context and not isinstance(context["generation"], dict):
        context["generation"] = {}
    _raw_format = data.get("format", {})
    format_spec = _raw_format if isinstance(_raw_format, dict) else {}
    # Alt alanları da dict'e normalize et
    for _key in ("options", "paragraph", "soru_koku"):
        if _key in format_spec and not isinstance(format_spec[_key], dict):
            format_spec[_key] = {}
    generation = dict(context.get("generation", {}))
    gorsel = data.get("gorsel", {})
    top_level_difficulty = data.get("difficulty")
    top_level_zorluk = _find_key(
        data, "zorluk_seviyesi", "Zorluk_Seviyesi", "Zorluk Seviyesi",
    )
    top_level_varyantlar = _find_key(
        data, "varyantlar", "Varyantlar",
    )
    top_level_varyant = _find_key(
        data, "varyant", "Varyant",
    )

    if top_level_zorluk is not None and "difficulty" not in meta:
        meta["difficulty"] = _normalize_difficulty(top_level_zorluk)
    elif top_level_difficulty is not None and "difficulty" not in meta:
        meta["difficulty"] = top_level_difficulty

    # questions: once context icinde ara, yoksa top-level'dan al (fallback)
    questions = list(context.get("questions", []))
    if not questions:
        top_level_questions = data.get("questions", [])
        if top_level_questions:
            questions = list(top_level_questions)
            logger.info("questions top-level'dan context'e tasinarak yuklendi")
    questions = _normalize_soru_kokleri(questions)
    context["questions"] = questions
    context = _normalize_question_variants(context, data)

    # question_count ile gercek questions sayisi uyumsuzsa otomatik duzelt
    declared_qcount = context.get("question_count", 1)
    actual_qcount = len(questions)
    if actual_qcount > 0 and declared_qcount != actual_qcount:
        logger.warning(
            "question_count (%d) ile gercek soru sayisi (%d) uyumsuz, "
            "gercek sayiya duzeltiliyor: %s",
            declared_qcount, actual_qcount, path.name,
        )
        context["question_count"] = actual_qcount

    # Eski/top-level gorsel tanimlarini zincirlerin bekledigi generation alanina tasir.
    # Boylece mevcut butun YAML'lar ortak gorsel kurallarindan ayni sekilde yararlanir.
    if isinstance(gorsel, dict):
        if "ana_gorsel" not in generation and isinstance(gorsel.get("ana_gorsel"), dict):
            generation["ana_gorsel"] = gorsel["ana_gorsel"]
        if "sik_gorseli" not in generation and isinstance(gorsel.get("sik_gorseli"), dict):
            generation["sik_gorseli"] = gorsel["sik_gorseli"]
    if generation != context.get("generation", {}):
        context = dict(context)
        context["generation"] = generation
    options = format_spec.get("options", {})
    if not isinstance(options, dict):
        options = {}

    # has_visual_options: siklar gorsel mi?
    options_style = options.get("style", "numeric_only")
    # text / numeric / name / symbolic / sequence iceren style'lar metin tabanlidir;
    # bu durumda sik gorseli uretilmez.
    style_lower = options_style.lower()
    # sik_gorseli.gerekli: false ise gorsel sik uretilmez
    sik_gorseli = generation.get("sik_gorseli") or gorsel.get("sik_gorseli", {})
    sik_gorseli_gerekli = sik_gorseli.get("gerekli", True) if isinstance(sik_gorseli, dict) else True
    has_visual_options = (
        sik_gorseli_gerekli
        and not any(kw in style_lower for kw in _NON_VISUAL_STYLE_KEYWORDS)
        and not str(options_style).startswith("text_only")
    )

    # requires_visual: birden fazla kaynaktan belirlenir (herhangi biri False yaparsa False)
    requires_visual = True

    # 1. gorsel.ana_gorsel.gerekli: false → görselsiz
    if isinstance(gorsel, dict):
        ana_gorsel_conf = gorsel.get("ana_gorsel", {})
        if isinstance(ana_gorsel_conf, dict) and ana_gorsel_conf.get("gerekli") is False:
            requires_visual = False

    # 2. image_type "gorselsiz" ile başlıyorsa veya tam olarak "gorselsiz" ise → görselsiz
    raw_image_type_check = str(generation.get("image_type", "ortak_gorsel")).lower().strip()
    if requires_visual and (
        raw_image_type_check == "gorselsiz"
        or raw_image_type_check.startswith("gorselsiz")
    ):
        requires_visual = False

    # 3. gorsel.ana_gorsel.stil: "gorselsiz" → görselsiz
    if requires_visual and isinstance(gorsel, dict):
        ana_gorsel_conf = gorsel.get("ana_gorsel", {})
        if isinstance(ana_gorsel_conf, dict):
            stil = str(ana_gorsel_conf.get("stil", "")).lower().strip()
            if stil == "gorselsiz":
                requires_visual = False

    # Normalizasyonlar
    raw_image_type = generation.get("image_type", "ortak_gorsel")
    normalized_image_type = _normalize_image_type(raw_image_type)
    raw_labels = options.get("labels", ["A", "B", "C"])
    normalized_labels = _normalize_option_labels(raw_labels)

    # Visual engine: auto-detect kareli/noktali/birimkare; YAML override varsa oncelikli
    visual_engine = _determine_visual_engine(
        data=data,
        gorsel=gorsel if isinstance(gorsel, dict) else {},
        image_type=normalized_image_type,
        requires_visual=requires_visual,
    )

    # Baglamli soru parametrelerini extract et
    baglamli = _extract_baglamli_params(data, context, format_spec)

    return ParsedTemplate(
        raw=data,
        meta=meta,
        context=context,
        header_template=data.get("header_template", ""),
        format_spec=format_spec,
        dogru_cevap=data.get("dogru_cevap", {}),
        distractors=data.get("distractors", {}),
        use_shared_strategies=data.get("use_shared_strategies", False),
        tymm_uyum_kurallari=data.get("tymm_uyum_kurallari", {}),
        gorsel=data.get("gorsel", {}),
        izinli_icerikler=data.get("izinli_icerikler", {}),
        # Turetilen alanlar
        sinif_seviyesi=_parse_sinif_seviyesi(meta.get("sinif_seviyesi", 2)),
        image_type=normalized_image_type,
        has_visual_options=has_visual_options,
        requires_visual=requires_visual,
        question_count=context.get("question_count", 1),
        option_count=options.get("count", 3),
        option_labels=normalized_labels,
        options_style=options_style,
        visual_engine=visual_engine,
        # Baglamli soru parametreleri
        **baglamli,
    )


# ---------------------------------------------------------------------------
# Visual engine tespiti
# ---------------------------------------------------------------------------

# image_type / sinyal alanlari: bunlardan biri varsa deterministik renderer kullanilir.
_SOLID_3D_PATTERNS = (
    r"\b3d\b", r"\buc\s+boyutlu\b", r"\b3\s+boyutlu\b",
    r"\bcisim\b", r"\bcisimler\b", r"\bgeometrik\s+cisim\b",
    r"\bkup\b", r"\bkure\b", r"\bprizma\b", r"\bsilindir\b",
    r"\bkare\s+prizma\b", r"\bdikdortgen\s+prizma\b", r"\bucgen\s+prizma\b",
    r"\bdik\s+dairesel\s+silindir\b",
    r"\bust\s+uste\s+yapi\b", r"\byapi\s+olusturma\b",
    r"\bkatman\b", r"\bkatmanli\b",
)

_GEOMETRIC_STRONG_PATTERNS = (
    r"\bgeometri\b", r"\bgeometrik\b",
    r"\bkareli\b", r"\bbirimkare\b", r"\bbirim\s+kare\b",
    r"\bnoktali\b", r"\bnoktali\s+duzlem\b",
    r"\bucgen\b", r"\bdikdortgen\b", r"\bkare\b",
    r"\bsimetri\b", r"\bkosegen\b",
    r"\baci\b", r"\bacilar\b", r"\bdar\s+aci\b", r"\bdik\s+aci\b", r"\bgenis\s+aci\b",
    r"\bcember\b", r"\bdaire\b",
    r"\bdogru\s+parcasi\b",
    r"\bsekil\s+sayma\b", r"\bgeometrik\s+sekil\b",
)

_GEOMETRIC_WEAK_PATTERNS = (
    r"\bcevre\b", r"\balan\b", r"\bkenar\b", r"\bkose\b",
    r"\bsekil\b", r"\bsekli\b", r"\bseklin\b", r"\bsekiller\b",
)


def _search_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        return " ".join(_search_text(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_search_text(v) for v in value)
    return str(value)


def _normalize_search_text(text: str) -> str:
    text = text.translate(_TURKISH_TO_ASCII).lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return f" {text.strip()} "


def _has_pattern(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text) for pattern in patterns)


def _determine_visual_engine(
    *,
    data: dict,
    gorsel: dict,
    image_type: str,
    requires_visual: bool,
) -> str:
    """Gorsel motorunu secer: 'generative' veya 'geometric_deterministic'.

    Oncelik sirasi:
      1. gorsel.ana_gorsel.engine (YAML explicit override)
      2. Top-level visual_engine (YAML explicit override)
      3. image_type / meta / context / gorsel stilinde geometri sinyali varsa otomatik geometric
      4. Varsayilan: generative
    """
    if not requires_visual:
        return "generative"  # Onemsiz — gorsel uretilmeyecek

    # 1. YAML explicit override — gorsel.ana_gorsel.engine
    ana = gorsel.get("ana_gorsel") if isinstance(gorsel, dict) else None
    if isinstance(ana, dict):
        override = ana.get("engine")
        if isinstance(override, str) and override.strip():
            return override.strip().lower()

    # 2. Top-level override
    top_override = data.get("visual_engine")
    if isinstance(top_override, str) and top_override.strip():
        return top_override.strip().lower()

    # 3. Auto-detect geometri / 3D cisim sinyali.
    # Bilerek tum YAML'i taramiyoruz: cok sayida sablon "tema disi geometri" gibi
    # yasaklarda geometri kelimesi geciriyor. Sadece sablon kimligi ve gorsel stilini
    # anlatan alanlar sinyal kabul edilir.
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    context = data.get("context") if isinstance(data.get("context"), dict) else {}
    generation = context.get("generation") if isinstance(context.get("generation"), dict) else {}
    format_spec = data.get("format") if isinstance(data.get("format"), dict) else {}

    ana = gorsel.get("ana_gorsel") if isinstance(gorsel, dict) else {}
    ana = ana if isinstance(ana, dict) else {}

    signal_text = _normalize_search_text(" ".join([
        str(image_type),
        _search_text({
            "meta_id": meta.get("id"),
            "meta_ad": meta.get("ad"),
            "meta_aciklama": meta.get("aciklama"),
            "context_type": context.get("type"),
            "generation_image_type": generation.get("image_type"),
            "generation_visual_layout": generation.get("visual_layout"),
            "format_type": format_spec.get("type"),
            "ana_gorsel_stil": ana.get("stil"),
            "ana_gorsel_tur": ana.get("type"),
        }),
    ]))
    if _has_pattern(signal_text, _SOLID_3D_PATTERNS):
        return "solid_3d_deterministic"

    if _has_pattern(signal_text, _GEOMETRIC_STRONG_PATTERNS):
        return "geometric_deterministic"

    weak_hits = sum(1 for pattern in _GEOMETRIC_WEAK_PATTERNS if re.search(pattern, signal_text))
    if weak_hits >= 2:
        return "geometric_deterministic"

    return "generative"


# ---------------------------------------------------------------------------
# Yardimci fonksiyonlar
# ---------------------------------------------------------------------------

def _dict_to_yaml_str(d: Any, indent: int = 0) -> str:
    """dict/list'i okunabilir YAML-benzeri metin formatina cevirir."""
    if isinstance(d, dict):
        lines = []
        for k, v in d.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{'  ' * indent}{k}:")
                lines.append(_dict_to_yaml_str(v, indent + 1))
            else:
                lines.append(f"{'  ' * indent}{k}: {v}")
        return "\n".join(lines)
    elif isinstance(d, list):
        lines = []
        for item in d:
            if isinstance(item, dict):
                lines.append(f"{'  ' * indent}-")
                lines.append(_dict_to_yaml_str(item, indent + 1))
            else:
                lines.append(f"{'  ' * indent}- {item}")
        return "\n".join(lines)
    else:
        return f"{'  ' * indent}{d}"


def _beceri_to_pedagogical_note(bilesenler: list[str], surec: str, katman: str) -> str:
    """Beceri bilesenlerinden otomatik pedagojik odak ozeti uretir."""
    bilesen_notlari = {
        "ters_sira_izleme": "TERS SIRA — öğrenci görseldeki sıranın tersini takip etmeli",
        "celdirici_ayiklama": "ÇELDİRİCİ AYIKLAMA — güçlü çeldiricileri eleyerek doğru cevaba ulaşmalı",
        "uygun_arac_secme": "Doğrudan uygun araç seçimi",
        "puan_hesaplama": "Puan hesabı — doğru/yanlış değerini sayısal hesaplamalı",
        "dogru_yanlis_sayma": "Doğru-yanlış SAYIMI — her satırı kontrol edip saymalı",
        "eksik_bilgi_tamamlama": "EKSİK BİLGİ TAMAMLAMA — boşluğa doğru birimi bulmalı",
        "hata_analizi": "HATA ANALİZİ — yanlış satırı bulmalı",
        "duzeltme": "DÜZELTME — hatalı eşleştirmeyi tespit edip doğrusunu yazmalı",
        "karsilastirma": "Seçenekler arası karşılaştırma",
    }
    surec_notlari = {
        "bilgiyi_cikartma": "Bilgi çıkartma süreci",
        "cozumleme": "Analitik çözümleme süreci",
        "bilgiyi_tamamlama": "Bilgi tamamlama — eksik parçayı mantıkla doldurmalı",
        "yanlisi_bulma_ve_duzeltme": "Yanlışı bulup düzeltme",
        "denetleme": "Denetleme — her öğeyi tek tek kontrol etmeli",
    }
    notes = []
    for b in bilesenler:
        if b in bilesen_notlari:
            notes.append(bilesen_notlari[b])
    if surec in surec_notlari:
        notes.append(surec_notlari[surec])
    if katman == "KB3":
        notes.append("KB3 — analitik düşünme zorunlu")
    return " | ".join(notes[:3]) if notes else ""


def get_soru_kokleri(t: ParsedTemplate) -> list[str]:
    """context.questions'dan tum soru koklerini cikarir."""
    stems = []
    for q in t.context.get("questions", []):
        stems.extend(q.get("soru_kokleri", []))
    return stems


# ---------------------------------------------------------------------------
# Chain bazli extract fonksiyonlari
# Her chain'e sadece ihtiyaci olan basliklari verir.
# ---------------------------------------------------------------------------

def extract_for_question_chain(t: ParsedTemplate) -> str:
    """Chain 1 (Mega Soru Uretimi) icin prompt metni olusturur.
    Kaynaklar: meta, context (generation + questions), format_spec, dogru_cevap, distractors, tymm
    Sahne tasarimi bilgileri de dahil (artik ayri chain yok).
    """
    sections = []
    generation = t.context.get("generation", {})

    # META
    sections.append("## META")
    sections.append(_dict_to_yaml_str(t.meta))
    sections.append("")

    # BAGLAM VE URETIM
    sections.append("## BAĞLAM VE ÜRETİM KURALLARI")
    sections.append(f"Soru tipi: {t.context.get('type', '?')}")
    sections.append(f"Soru sayısı: {t.question_count}")
    word_min = generation.get("word_count_min", "?")
    word_max = generation.get("word_count_max", "?")
    sections.append(f"Kelime sayısı: {word_min}-{word_max}")
    sections.append(f"Görsel tipi: {t.image_type}")

    # Coklu soru vurgusu
    if t.question_count > 1:
        sections.append("")
        sections.append(
            f"⚠️ ÇOKLU SORU: Bu şablon {t.question_count} soru gerektirir. "
            f"TEK senaryo ve TEK görsel üzerinden {t.question_count} FARKLI soru üretilecek. "
            f"Her soru kendi kökü, şıkları ve doğru cevabıyla questions listesinde "
            f"ayrı QuestionItem olarak yer almalı."
        )

    sections.append("")

    # URETIM YAPISI (structure)
    structure = generation.get("structure", [])
    if structure:
        sections.append("## ÜRETİM YAPISI")
        for item in structure:
            sections.append(f"- {item}")
        sections.append("")

    # KURALLAR
    kurallar = generation.get("kurallar", [])
    if kurallar:
        sections.append("## KURALLAR")
        for item in kurallar:
            sections.append(f"- {item}")
        sections.append("")

    _append_shared_consistency_rules(sections)

    # GORSEL TIPI VE GORSEL KURALLARI (sahne tasarimi icin)
    sections.append("## GÖRSEL TİPİ")
    sections.append(f"Tür: {t.image_type}")
    ana_gorsel = t.gorsel.get("ana_gorsel", {}) or generation.get("ana_gorsel", {})
    if ana_gorsel:
        sections.append("Ana görsel kuralları:")
        sections.append(_dict_to_yaml_str(ana_gorsel))
    # Varyant bazli gorsel notlari
    if t.gorsel_notlari:
        sections.append("Varyant görsel notları:")
        for note in t.gorsel_notlari:
            sections.append(f"  - {note}")
    sections.append("")

    # SORU KOKLERI + BECERI HEDEFLERI
    questions = t.context.get("questions", [])
    if questions:
        sections.append("## SORU KÖKLERİ VE BECERİ HEDEFLERİ")
        if t.question_count > 1:
            sections.append(
                f"Her slot FARKLI bir bilişsel hedefi temsil eder. "
                f"{t.question_count} soru üretilirken her slot'un kendine özgü beceri yapısı korunmalı."
            )
        for q in questions:
            slot = q.get("slot", "?")
            q_type = q.get("type", "?")
            sections.append(f"\nSlot {slot} (tip: {q_type}):")
            sections.append("  Soru kökleri:")
            for stem in q.get("soru_kokleri", []):
                sections.append(f"    - {stem}")
            beceri = q.get("beceri", {})
            if not isinstance(beceri, dict):
                beceri = {}
            if beceri:
                katman = beceri.get("katman", "?")
                bilesenler = beceri.get("bilesenler", [])
                surec = beceri.get("surec_bileseni", "")
                sections.append(f"  Beceri katmanı: {katman}")
                if bilesenler:
                    sections.append(f"  Bileşenler: {', '.join(bilesenler)}")
                if surec:
                    sections.append(f"  Süreç bileşeni: {surec}")
                # Pedagojik odak notu
                pedagojik_not = _beceri_to_pedagogical_note(bilesenler, surec, katman)
                if pedagojik_not:
                    sections.append(f"  ⮕ Pedagojik odak: {pedagojik_not}")
        sections.append("")

    # FORMAT
    sections.append("## FORMAT")
    sections.append(_dict_to_yaml_str(t.format_spec))
    sections.append("")

    # DOGRU CEVAP
    if t.dogru_cevap:
        sections.append("## DOĞRU CEVAP KURALI")
        sections.append(_dict_to_yaml_str(t.dogru_cevap))
        sections.append("")

    # CELDIRICI STRATEJILERI
    if t.distractors:
        sections.append("## ÇELDİRİCİ STRATEJİLERİ")
        sections.append(_dict_to_yaml_str(t.distractors))
        # Varyant bazli celdirici notlari
        if t.celdirici_notlari:
            sections.append("Varyant çeldirici notları:")
            for note in t.celdirici_notlari:
                sections.append(f"  - {note}")
        sections.append("")

    # TYMM UYUM KURALLARI (varsa)
    if t.tymm_uyum_kurallari:
        sections.append("## TYMM UYUM KURALLARI")
        sections.append(_dict_to_yaml_str(t.tymm_uyum_kurallari))
        sections.append("")

    # IZINLI ICERIKLER (varsa)
    if t.izinli_icerikler:
        sections.append("## İZİNLİ İÇERİKLER")
        sections.append(_dict_to_yaml_str(t.izinli_icerikler))
        sections.append("")

    # ── BAGLAMLI SORU PARAMETRELERI (kosullu) ────────────────────────────

    # REFERANS SORU TANIMLARI
    if t.referans_sorular:
        questions_data = t.context.get("questions", [])
        sections.append("## REFERANS SORU TANIMLARI")
        sections.append(
            "Bu referans tanımlar, üretilecek soruların yapısal şablonudur. "
            "Senaryo yapısı, seçenek formatı ve çözüm mantığına sadık kal; "
            "birebir kopyalama ama aynı mantıksal yapıda üret."
        )
        if t.question_count > 1:
            sections.append(
                "⚠️ Her slot'un bilişsel hedefi FARKLDIR — referans senaryolardaki "
                "yapısal farklar (sıra değişimi, beceri katmanı, çeldirici yapısı) korunmalı."
            )
        for ref in t.referans_sorular:
            slot = ref.get("slot", "?")
            r_type = ref.get("type", "?")
            sections.append(f"\n### Slot {slot} (tip: {r_type})")
            q_data = next((q for q in questions_data if q.get("slot") == slot), {})
            beceri = q_data.get("beceri", {})
            if not isinstance(beceri, dict): beceri = {}
            if beceri:
                katman = beceri.get("katman", "?")
                bilesenler = beceri.get("bilesenler", [])
                surec = beceri.get("surec_bileseni", "")
                pedagojik_not = _beceri_to_pedagogical_note(bilesenler, surec, katman)
                if pedagojik_not:
                    sections.append(f"⮕ DİKKAT: {pedagojik_not}")
                    sections.append(f"   Beceri: {', '.join(bilesenler)} | Süreç: {surec}")
            if ref.get("varyant_adi"):
                sections.append(f"Varyant adı: {ref['varyant_adi']}")
            if ref.get("senaryo"):
                sections.append(f"Referans senaryo: {ref['senaryo']}")
            if ref.get("soru_koku"):
                sections.append(f"Referans soru kökü: {ref['soru_koku']}")
            if ref.get("secenekler"):
                sections.append("Referans seçenekler:")
                secenekler = ref["secenekler"]
                if isinstance(secenekler, dict):
                    for label, text in secenekler.items():
                        sections.append(f"  {label}: {text}")
                elif isinstance(secenekler, list):
                    for item in secenekler:
                        if isinstance(item, dict):
                            label = item.get("etiket", "?")
                            text = item.get("metin", "?")
                            sections.append(f"  {label}: {text}")
                        else:
                            sections.append(f"  - {item}")
            if ref.get("dogru_cevap"):
                sections.append(f"Referans doğru cevap: {ref['dogru_cevap']}")
            if ref.get("cozum"):
                sections.append(f"Referans çözüm: {ref['cozum']}")
        sections.append("")

    # VARYANT TANIMLARI
    if t.varyant_tanimlari:
        sections.append("## VARYANT TANIMLARI")
        if t.varyant_tanimlari.get("varyantlar"):
            sections.append("### Top-level Varyantlar")
            sections.append(_dict_to_yaml_str(t.varyant_tanimlari["varyantlar"]))
            sections.append("")
        if t.varyant_tanimlari.get("varyant_bicimleri"):
            sections.append("### Varyant Biçimleri")
            sections.append(_dict_to_yaml_str(t.varyant_tanimlari["varyant_bicimleri"]))
        sections.append("")

    # OZEL KURALLAR
    if t.ozel_kurallar:
        sections.append("## ÖZEL KURALLAR")
        for kural in t.ozel_kurallar:
            sections.append(f"- {kural}")
        sections.append("")

    # HAVUZLAR
    if t.havuzlar:
        sections.append("## HAVUZLAR")
        if t.havuzlar.get("baglam_havuzu"):
            sections.append("### Bağlam Havuzu")
            for item in t.havuzlar["baglam_havuzu"]:
                sections.append(f"  - {item}")
        if t.havuzlar.get("nesne_havuzu"):
            sections.append("### Nesne Havuzu")
            sections.append(_dict_to_yaml_str(t.havuzlar["nesne_havuzu"], indent=1))
        if t.havuzlar.get("soru_koku_havuzu"):
            sections.append("### Soru Kökü Havuzu")
            for item in t.havuzlar["soru_koku_havuzu"]:
                sections.append(f"  - {item}")
        sections.append("")

    # SABIT KALANLAR VE DEGISENLER
    if t.sabit_ve_degisen:
        sections.append("## SABİT KALANLAR VE DEĞİŞENLER")
        sabitler = t.sabit_ve_degisen.get("sabit", [])
        if sabitler:
            sections.append("### Sabit kalanlar (bunlar DEĞİŞMEMELİ)")
            for s in sabitler:
                sections.append(f"  - {s}")
        degisenler = t.sabit_ve_degisen.get("degisen", [])
        if degisenler:
            sections.append("### Değişenler (bunlar değişebilir)")
            for d in degisenler:
                sections.append(f"  - {d}")
        sections.append("")

    return "\n".join(sections)


def extract_for_validation_chain(t: ParsedTemplate) -> str:
    """Chain 2 (Batch Dogrulama) icin prompt metni olusturur.
    Kaynaklar: meta, context.generation (kurallar + structure), format_spec, dogru_cevap,
    distractors, tymm, beceri, paragraf kisitlari
    """
    sections = []
    generation = t.context.get("generation", {})

    # META
    sections.append("## META")
    sections.append(f"Sınıf: {t.sinif_seviyesi}")
    sections.append(f"Soru tipi: {t.context.get('type', '?')}")
    sections.append(f"Açıklama: {t.meta.get('aciklama', '?')}")
    sections.append(f"Görsel tipi: {t.image_type}")
    sections.append("")

    # URETIM YAPISI (validator yapisal uyumu kontrol etmeli)
    structure = generation.get("structure", [])
    if structure:
        sections.append("## ÜRETİM YAPISI (kontrol edilecek)")
        for item in structure:
            sections.append(f"- {item}")
        sections.append("")

    # DOGRU CEVAP KURALLARI
    if t.dogru_cevap:
        sections.append("## DOĞRU CEVAP KURALLARI")
        sections.append(_dict_to_yaml_str(t.dogru_cevap))
        sections.append("")

    # FORMAT KURALLARI
    options = t.format_spec.get("options", {})
    if not isinstance(options, dict): options = {}
    if options:
        sections.append("## FORMAT VE SEÇENEK KURALLARI")
        sections.append(_dict_to_yaml_str(t.format_spec))
        sections.append("")

    # URETIM KURALLARI
    kurallar = generation.get("kurallar", [])
    if kurallar:
        sections.append("## ÜRETİM KURALLARI")
        for item in kurallar:
            sections.append(f"- {item}")
        sections.append("")

    _append_shared_consistency_rules(sections)

    # BECERI HEDEFLERI (pedagojik uyum kontrolu)
    questions = t.context.get("questions", [])
    any_beceri = any(q.get("beceri") for q in questions)
    if any_beceri:
        sections.append("## BECERİ HEDEFLERİ (pedagojik uyum kontrolü)")
        for q in questions:
            beceri = q.get("beceri", {})
            if not isinstance(beceri, dict): beceri = {}
            if beceri:
                sections.append(f"  Katman: {beceri.get('katman', '?')}")
                bilesenler = beceri.get("bilesenler", [])
                if bilesenler:
                    sections.append(f"  Bileşenler: {', '.join(bilesenler)}")
                surec = beceri.get("surec_bileseni", "")
                if surec:
                    sections.append(f"  Süreç: {surec}")
        sections.append("")

    # CELDIRICI STRATEJILERI
    if t.distractors:
        sections.append("## ÇELDİRİCİ STRATEJİLERİ")
        sections.append(_dict_to_yaml_str(t.distractors))
        sections.append("")

    # TYMM UYUM KURALLARI (varsa)
    if t.tymm_uyum_kurallari:
        sections.append("## TYMM UYUM KURALLARI")
        sections.append(_dict_to_yaml_str(t.tymm_uyum_kurallari))
        sections.append("")

    return "\n".join(sections)


def extract_for_solver_chain(t: ParsedTemplate) -> str:
    """Chain 3 (Bagimsiz Soru Cozumu) icin prompt metni olusturur.
    Kaynaklar: meta.sinif_seviyesi, context.type, context.generation.kurallar (cevapsiz baglam)
    KRITIK: dogru_cevap KESINLIKLE dahil edilmez.
    """
    sections = []

    sections.append("## BAĞLAM")
    sections.append(f"Sınıf seviyesi: {t.sinif_seviyesi}")
    sections.append(f"Soru tipi: {t.context.get('type', '?')}")
    sections.append(f"Açıklama: {t.meta.get('aciklama', '?')}")
    sections.append("")

    # Cevapsiz baglamsal kurallar (sorunun ne test ettigini anlamak icin)
    kurallar = t.context.get("generation", {}).get("kurallar", [])
    if kurallar:
        sections.append("## SORU KURALLARI (bağlam için)")
        for k in kurallar:
            sections.append(f"- {k}")
        sections.append("")

    _append_shared_consistency_rules(sections)

    return "\n".join(sections)


def extract_for_main_image_chain(t: ParsedTemplate) -> str:
    """Chain 4 - Ana Gorsel Uretimi icin prompt metni olusturur.
    Kaynaklar: context.generation (ana_gorsel, structure, kurallar),
    dogru_cevap (gorsel destegi), beceri, distractors (farkindalilik), paragraf
    """
    sections = []
    generation = t.context.get("generation", {})

    # GORSEL TIPI
    sections.append("## GÖRSEL TİPİ")
    sections.append(f"Tür: {t.image_type}")
    sections.append("")

    # ANA GORSEL KURALLARI
    ana_gorsel = generation.get("ana_gorsel", {})
    if ana_gorsel:
        sections.append("## ANA GÖRSEL KURALLARI")
        sections.append(_dict_to_yaml_str(ana_gorsel))
        sections.append("")

    # URETIM YAPISI
    structure = generation.get("structure", [])
    if structure:
        sections.append("## ÜRETİM YAPISI")
        for item in structure:
            sections.append(f"- {item}")
        sections.append("")

    # GENEL KURALLAR
    kurallar = generation.get("kurallar", [])
    if kurallar:
        sections.append("## KURALLAR")
        for item in kurallar:
            sections.append(f"- {item}")
        sections.append("")

    _append_shared_consistency_rules(sections)

    # DOGRU CEVAP ICIN GORSEL DESTEGI
    if t.dogru_cevap:
        sections.append("## DOĞRU CEVAP İÇİN GÖRSEL DESTEĞİ")
        tanim = t.dogru_cevap.get("tanim", "")
        if tanim:
            sections.append(f"Tanım: {tanim}")
        for k in t.dogru_cevap.get("kurallar", []):
            sections.append(f"- {k}")
        sections.append("")

    # BECERI HEDEFI (gorsel bu beceriyi desteklemeli)
    questions = t.context.get("questions", [])
    for q in questions:
        beceri = q.get("beceri", {})
        if beceri:
            sections.append("## BECERİ HEDEFİ (görsel bu beceriyi desteklemeli)")
            sections.append(f"Katman: {beceri.get('katman', '?')}")
            bilesenler = beceri.get("bilesenler", [])
            if bilesenler:
                sections.append(f"Bileşenler: {', '.join(bilesenler)}")
            sections.append("")

    # CELDIRICI FARKINDALIGI (goerselde bunlardan kacin)
    if t.distractors:
        sections.append("## ÇELDİRİCİ FARKINDALIGI (görselde bunlardan kaçın)")
        for s in t.distractors.get("stratejiler", []):
            sections.append(f"- {s.get('ad', '?')}: {s.get('aciklama', '?')}")
            ornek = s.get("ornek", "")
            if ornek:
                sections.append(f"  Örnek hata: {ornek}")
        sections.append("")

    # GÖRSELDE YAZISAL İÇERİK YASAĞI
    sections.append("## GÖRSELDE YAZISAL İÇERİK YASAĞI (KRİTİK)")
    sections.append("- Görselde senaryo metni, üst metin, soru kökü veya soru cümlesi KESİNLİKLE yer almamalıdır.")
    sections.append("- Senaryo paragrafı ve soru kökü HTML şablonunda görselin dışında ayrıca gösterilmektedir; görselde TEKRAR edilmemelidir.")
    sections.append("- Görselde yalnızca kısa etiketler (kişi adları, şekil adları, sayılar, adım numaraları, harf etiketleri) bulunabilir.")
    sections.append("- Görselin üstüne, altına veya herhangi bir yerine cümle, paragraf veya açıklama metni YAZILMAMALIDIR.")
    sections.append("- Görsel prompt'unda scenario_text veya soru kökü ifadeleri prompt'a dahil edilmemelidir.")
    sections.append("")

    return "\n".join(sections)


def extract_for_option_image_chain(t: ParsedTemplate) -> str:
    """Chain 4 - Sik Gorseli Uretimi icin prompt metni olusturur.
    Kaynaklar: context.generation.sik_gorseli (kurallar, stil)
    """
    sections = []
    generation = t.context.get("generation", {})

    sik_gorseli = generation.get("sik_gorseli", {})
    if sik_gorseli:
        sections.append("## ŞIK GÖRSELİ KURALLARI")
        sections.append(_dict_to_yaml_str(sik_gorseli))
        sections.append("")

    return "\n".join(sections)


def extract_for_visual_validation_chain(t: ParsedTemplate) -> str:
    """Chain 5 (Gorsel Dogrulama) icin prompt metni olusturur.
    Kaynaklar: meta, context.generation (image_type, kurallar, structure, ana_gorsel),
    format_spec, dogru_cevap, beceri, distractors
    """
    sections = []
    generation = t.context.get("generation", {})

    # META
    sections.append("## META")
    sections.append(f"Sınıf: {t.sinif_seviyesi}")
    sections.append("")

    # GORSEL TIPI
    sections.append("## GÖRSEL TİPİ")
    sections.append(f"Tür: {t.image_type}")
    sections.append("")

    # YAPISAL GEREKSINIMLER (goerselde bulunmali)
    structure = generation.get("structure", [])
    if structure:
        sections.append("## YAPISAL GEREKSİNİMLER (görselde bulunmalı)")
        for item in structure:
            sections.append(f"- {item}")
        sections.append("")

    # ANA GORSEL KURALLARI
    ana_gorsel = generation.get("ana_gorsel", {})
    if ana_gorsel:
        sections.append("## ANA GÖRSEL KURALLARI")
        sections.append(_dict_to_yaml_str(ana_gorsel))
        sections.append("")

    # GENEL KURALLAR
    kurallar = generation.get("kurallar", [])
    if kurallar:
        sections.append("## GÖRSEL KURALLARI")
        for item in kurallar:
            sections.append(f"- {item}")
        sections.append("")

    _append_shared_consistency_rules(sections)

    # DOGRU CEVAP KURALLARI (gorsel bu kurallari desteklemeli)
    if t.dogru_cevap:
        sections.append("## DOĞRU CEVAP KURALLARI (görsel bu kuralları desteklemeli)")
        sections.append(_dict_to_yaml_str(t.dogru_cevap))
        sections.append("")

    # BECERI HEDEFI
    questions = t.context.get("questions", [])
    for q in questions:
        beceri = q.get("beceri", {})
        if beceri:
            sections.append("## BECERİ HEDEFİ (görsel bu beceriyi desteklemeli)")
            sections.append(f"Katman: {beceri.get('katman', '?')}")
            bilesenler = beceri.get("bilesenler", [])
            if bilesenler:
                sections.append(f"Bileşenler: {', '.join(bilesenler)}")
            sections.append("")

    # CELDIRICI KONTROLU (gorsel bunlari yanlislikla desteklememeli)
    if t.distractors:
        sections.append("## ÇELDİRİCİ KONTROLÜ (görsel bunları yanlışlıkla desteklememeli)")
        for s in t.distractors.get("stratejiler", []):
            sections.append(f"- {s.get('ad', '?')}: {s.get('aciklama', '?')}")
        sections.append("")

    # FORMAT
    if t.format_spec:
        sections.append("## FORMAT")
        sections.append(_dict_to_yaml_str(t.format_spec))
        sections.append("")

    return "\n".join(sections)


def extract_for_visual_solver_chain(t: ParsedTemplate) -> str:
    """Chain 6 (Gorsel Uzerinden Bagimsiz Cozum) icin prompt metni olusturur.
    Kaynaklar: meta.sinif_seviyesi, context.generation (image_type, kurallar — cevapsiz baglam)
    KRITIK: dogru_cevap KESINLIKLE dahil edilmez.
    """
    sections = []

    sections.append("## BAĞLAM")
    sections.append(f"Sınıf seviyesi: {t.sinif_seviyesi}")
    sections.append(f"Soru tipi: {t.context.get('type', '?')}")
    sections.append(f"Görsel tipi: {t.image_type}")
    sections.append("")

    # Cevapsiz baglamsal kurallar
    kurallar = t.context.get("generation", {}).get("kurallar", [])
    if kurallar:
        sections.append("## SORU KURALLARI (bağlam için)")
        for k in kurallar:
            sections.append(f"- {k}")
        sections.append("")

    _append_shared_consistency_rules(sections)

    return "\n".join(sections)
