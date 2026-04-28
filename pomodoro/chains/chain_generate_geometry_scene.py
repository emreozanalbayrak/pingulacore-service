"""
Geometri sahne grafi chain'i.

Girdi: GeneratedVisualQuestion + ParsedTemplate (geometri tipi)
Cikti: GeometryScene — deterministik SVG renderer icin yapisal JSON.

LLM'den gorsel uretmek yerine, tek koordinat sisteminde calismis kisa bir scene
graph istiyoruz. Scene graph downstream'de deterministik olarak SVG'ye
donusturuluyor. Raster ambient arka plan kapali tutulur; geometri gorseli hizli,
net ve foto-real olmayan SVG katmanlariyla uretilir.
"""
from __future__ import annotations

from typing import Optional

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate

from pomodoro.geometry_scene import GeometryScene
from pomodoro.models import GeneratedVisualQuestion
from pomodoro.yaml_loader import ParsedTemplate
from utils.llm import ModelRole, get_model


_parser = PydanticOutputParser(pydantic_object=GeometryScene)
_model = get_model(ModelRole.QUESTION_GENERATOR)


PROMPT_TEMPLATE = """Geometri sorusu icin yalnizca GeometryScene JSON'u uret. Koordinat: (0,0)=sol-alt, birim=1.

## KISA KURALLAR
- Once basit ama matematiksel olarak kesin dogru bir referans iskelet uret: sekiller, dogru parcalari, etiketler ve olcu iliskileri sorunun cevabiyla bire bir tutmali.
- Grid/noktali zemin gerekiyorsa tum vertex'ler TAM SAYI; polygon basit, kapali ve grid icinde olsun.
- Grid gerekmiyorsa background.type plain veya soft_grid olabilir; yine tum geometri tek koordinat sisteminde, temiz ve olculebilir dursun.
- Alan sorusunda expected_area dogru olsun; grid alan sorusunda polygon grid alaninin yaklasik %55-80'ini kullansin.
- Opaklik: fill 0.25-0.45, stroke 0.85-1.0, grid 0.30-0.55; soft_grid 0.20-0.30.
- Etiketler koseye yakin ama cizgiye degmeden offsetli dursun.
- Foto/raster arka plan ve dekorasyon YOK: ambient_image_prompt null olsun.

## GEOMETRI ISKELETI
- Bu JSON nihai estetik gorsel degil, dogrulugu koruyan referans iskelettir.
- Bu motor tum geometri sorularinda "once base visual, sonra final uretim" akisi icindir; referans iskelet sade, ucuz ve kesin dogru olmali.
- YAML kareli/noktali/birimkare istiyorsa unit_square, dotted, dashed_grid veya soft_grid kullan. YAML istemiyorsa plain/soft_grid daha uygundur.
- Beyaz zemin kullanma; acik kagit tonu, net polygon rengi ve okunur stroke sec.
- Duz dikdortgeni yalnizca soru bunu zorunlu kiliyorsa kullan. Aksi halde soruya uygun ucgen, kare, dikdortgen, L/T/basamakli sekil, trapez, besgen/altigen veya bilesik ama sayilabilir polygonlar sec.
- Bilesik sekil/sayma sorularinda her temel parcayi ayri polygon olarak ciz; gizli/ust uste binen parca olmasin ve sayim dogru olsun.
- Ucgen turu/kenar uzunlugu sorularinda gecersiz ucgen cizme; uzunluk etiketleri ilgili kenara yakin ve okunur olsun. Es kenarlar gerekiyorsa ayni kisa cizgi isaretleri kullanabilirsin.
- Aci sorularinda dogru parcasi/segmentlerle aciyi net kur; derece veya aci etiketi YAML/soru gerektiriyorsa ekle, yoksa cevabi ele veren fazla olcu yazma.
- Simetri sorularinda sekiller net ve karsilastirilabilir olsun; simetri eksenlerini ancak soru/yaml istiyorsa ciz, aksi halde cevabi ele veren eksen ekleme.
- YAML/soru yarim birim, kosegen, ucgen parca, diagonal/eğik kenar veya 1/2 alan kullanimina izin veriyorsa polygon kosegen kenarlar icerebilir. Bu durumda vertex'ler yine grid kesişimlerinde TAM SAYI olmali; alan 0.5'li deger olabilir ve expected_area bunu aynen yansitmali.
- Yarim birim alan kullaniyorsan kosegen sade kalsin: kosegenin iki tarafina eslik/tick cizgisi, "1/2" etiketi veya ekstra aciklama etiketi koyma. Esit iki yarim fikrini gerekirse soru metni/cozumde sezdir; base gorselde sadece dogru kosegen ve sekil yerlesimi gorunsun.
- YAML "yalnız yatay-dikey", "çapraz/eğik kullanılmamalı" veya benzer bir yasak veriyorsa kosegen/yarim alan kullanma.
- Yardimci segmentleri sadece soru gerektiriyorsa ekle: olcu oku, kesikli yukseklik, ic bolme, diagonal, taban/yukseklik rehberi, aci kollari, simetri ekseni. Sirf cesitlilik icin cizgi ekleme.
- Etiketleri yalnizca soru gerektiriyorsa kullan: kose harfi, kenar olcusu, derece, birim sayisi gibi. Cevabi ele veren yazilar koyma.
- scenario_hint kisa olsun ve sadece geometri baglamini anlatsin; renderer bunu dekor icin kullanmaz.

## SORU VERILERI
Sinif: {sinif_seviyesi} | Gorsel tipi: {image_type}
Sahne: {scene_description}
Senaryo: {scenario_text}
Duzen: {visual_layout}
Ogeler: {scene_elements}
Gorsel ogeler: {visual_elements}
Hesaplama: {hidden_computation}
Soru/cevap: {questions_block}

## YAML KURALLARI
{gorsel_rules}

## ONCEKI GERI BILDIRIM
{feedback_section}

## CIKTI
Sadece GeometryScene JSON. Aciklama yazma.
Zorunlu alanlar: background(type/cols/rows/paper_color/grid_color), color_theme, scenario_hint. En az bir polygon veya segment kullan; alan sorusuysa expected_area ver.
ambient_image_prompt null olsun; ambient_opacity onemsiz.

{format_instructions}
"""


def _format_questions_block(question: GeneratedVisualQuestion) -> str:
    if not question.questions:
        return "(yok)"
    lines = []
    for q in question.questions:
        correct_key = (q.correct_answer or "").strip().upper()
        correct_val = q.options.get(correct_key, "")
        lines.append(f"- Soru: {q.question_stem}")
        if correct_key:
            lines.append(f"  Dogru cevap: {correct_key}) {correct_val}")
        if q.solution_explanation:
            lines.append(f"  Cozum: {q.solution_explanation}")
    return "\n".join(lines)


def _format_gorsel_rules(template: ParsedTemplate) -> str:
    generation = template.context.get("generation", {})
    ana = generation.get("ana_gorsel") or template.gorsel.get("ana_gorsel") or {}
    parts = []
    if isinstance(ana, dict):
        kurallar = ana.get("kurallar") or []
        if kurallar:
            parts.append("Ana gorsel kurallari:")
            for k in kurallar[:6]:
                parts.append(f"- {k}")
        yasaklar = ana.get("yasaklar") or []
        if yasaklar:
            parts.append("Yasaklar:")
            for y in yasaklar[:4]:
                parts.append(f"- {y}")
    structure = generation.get("structure", [])
    if structure:
        parts.append("Yapisal gereksinimler:")
        for s in structure[:4]:
            parts.append(f"- {s}")
    return "\n".join(parts) if parts else "(ozel kural yok)"


_prompt = PromptTemplate(
    template=PROMPT_TEMPLATE,
    input_variables=[
        "sinif_seviyesi",
        "image_type",
        "scene_description",
        "scenario_text",
        "visual_layout",
        "scene_elements",
        "visual_elements",
        "hidden_computation",
        "questions_block",
        "gorsel_rules",
        "feedback_section",
    ],
    partial_variables={
        "format_instructions": _parser.get_format_instructions(),
    },
)

_chain = _prompt | _model | _parser


def generate_geometry_scene(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    feedback: Optional[str] = None,
) -> GeometryScene:
    """LLM'den GeometryScene JSON'u alir."""
    feedback_section = ""
    if feedback:
        feedback_section = (
            "Onceki denemede su sorunlar tespit edildi (duzelt):\n" + feedback
        )

    payload = {
        "sinif_seviyesi": str(template.sinif_seviyesi),
        "image_type": template.image_type,
        "scene_description": question.scene_description or "(yok)",
        "scenario_text": question.scenario_text or "(yok)",
        "visual_layout": str(question.visual_layout or {})[:700],
        "scene_elements": str(question.scene_elements or {})[:700],
        "visual_elements": str(question.visual_elements or [])[:700],
        "hidden_computation": str(question.hidden_computation or {})[:900],
        "questions_block": _format_questions_block(question),
        "gorsel_rules": _format_gorsel_rules(template),
        "feedback_section": feedback_section or "(yok)",
    }
    scene: GeometryScene = _chain.invoke(payload)
    return scene
