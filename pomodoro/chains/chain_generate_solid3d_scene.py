"""3D geometrik cisim sahne grafi chain'i."""
from __future__ import annotations

from typing import Optional

from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.prompts import PromptTemplate

from pomodoro.models import GeneratedVisualQuestion
from pomodoro.solid3d_scene import Solid3DScene
from pomodoro.yaml_loader import ParsedTemplate
from utils.llm import ModelRole, get_model


_parser = PydanticOutputParser(pydantic_object=Solid3DScene)
_model = get_model(ModelRole.QUESTION_GENERATOR)


PROMPT_TEMPLATE = """3D geometrik cisim sorusu icin yalnizca Solid3DScene JSON'u uret.

## AMAC
- Kup, kare prizma, dikdortgen prizma, ucgen prizma, silindir ve kure gibi 3D cisimleri deterministik renderer icin yapilandir.
- Ayrik sik gorseli URETILMEYECEK. Secenekler gerekiyorsa A/B/C panelleri TEK ana gorsel icinde yer alacak.
- Dogru cevabi ele veren tik, vurgu, yildiz, renk avantaji veya ekstra sembol kullanma.

## CISIM ESLESTIRME
- "kup" -> kind="cube"
- "kare prizma" -> kind="square_prism"
- "dikdortgen prizma" -> kind="rectangular_prism"
- "ucgen prizma" -> kind="triangular_prism"
- "silindir" / "dik dairesel silindir" -> kind="cylinder"
- "kure" -> kind="sphere"

## PANEL KURALLARI
- Soru gorsel secenek istiyorsa panel etiketleri TAM OLARAK secenek etiketleriyle ayni olmali: {option_labels}
- option_scenes verildiyse her sahneyi ayni etiketli panele cevir.
- Her panelde ayni olcek ve benzer renk mantigi kullan; yalniz dizilis/sira/tur farki sorunun gerektirdigi kadar olsun.
- Ust-orta-alt veya katman bilgisi varsa layout="vertical_stack" kullan ve solids listesini ALTTAN USTE sirala.
- Yan yana karsilastirma gerekiyorsa layout="side_by_side"; daginik tanima gerekiyorsa layout="loose_group".
- Kureleri vertical_stack icinde kullanma; gerekiyorsa loose_group sec.
- Dikey yiginda cisimler merkezli ve dengeli gorunmeli; ustteki cisimleri alta gore asiri saga/sola kaydirma.
- Cisimleri panelin asiri koselerine veya en uc noktalarina itme; orta alanda, sayilabilir ve dogal bir kompozisyon kur.
- Ustte duran cisimler alttaki cisim tarafindan fiziksel olarak destekleniyormus gibi gorunmeli.

## BASE VISUAL KARAKTERI
- Base visual cercevesiz, sade, duz renkli ve referans iskelet gibi dusunulmeli.
- Base visual gercekci malzeme, parlama, fotografik doku veya dramatik isik gerektirmez.
- Panel kompozisyonu 2D geometri base'leri gibi temiz, merkezli ve okuma odakli olmali.

## RENK
- Renkler cocuk dostu ama cevap ipucu vermeyecek kadar dengeli olmali.
- Ayni cisim turu farkli panellerde benzer renkte kalsin.

## BAGLAM / TEMA
- theme_object alanini senaryodaki ana nesne veya urune gore doldur: firildak, oyuncak davul standi, maket, kule, sergileme standi vb.
- place_hint alanini sahneye gore doldur: masaustu, calisma masasi, sinif, atolye, sergileme alani vb.
- material_hint alanini final estetik icin yararli olacak sekilde doldur: duz illustratif egitsel materyal, renkli sinif materyali, sade boyali blok, kitap ilustrasyonu hissi vb.
- scenario_hint tek kisa cumle olmali; yalnizca ana duzeni ozetlesin ve 80 karakteri gecmesin.
- Bu alanlar sadece final estetikte yol gostericidir; geometriyi degistirmek icin kullanilmayacak.

## SORU VERILERI
Sinif: {sinif_seviyesi} | Gorsel tipi: {image_type}
Sahne: {scene_description}
Senaryo: {scenario_text}
Duzen: {visual_layout}
Gorsel ogeler: {visual_elements}
Hesaplama: {hidden_computation}
Soru/cevap: {questions_block}
Sik sahneleri: {option_scenes}

## YAML KURALLARI
{gorsel_rules}

## ONCEKI GERI BILDIRIM
{feedback_section}

## CIKTI
Sadece Solid3DScene JSON. Aciklama yazma.
theme_object, place_hint, material_hint ve kisa scenario_hint alanlarini mumkunse doldur.
{format_instructions}
"""


def _format_questions_block(question: GeneratedVisualQuestion) -> str:
    if not question.questions:
        return "(yok)"
    lines: list[str] = []
    for q in question.questions:
        correct_key = (q.correct_answer or "").strip().upper()
        correct_val = q.options.get(correct_key, "")
        lines.append(f"- Soru: {q.question_stem}")
        lines.append(f"  Secenekler: {q.options}")
        if correct_key:
            lines.append(f"  Dogru cevap: {correct_key}) {correct_val}")
        if q.solution_explanation:
            lines.append(f"  Cozum: {q.solution_explanation}")
    return "\n".join(lines)


def _format_gorsel_rules(template: ParsedTemplate) -> str:
    generation = template.context.get("generation", {})
    ana = generation.get("ana_gorsel") or template.gorsel.get("ana_gorsel") or {}
    parts: list[str] = []
    structure = generation.get("structure", [])
    if structure:
        parts.append("Yapisal gereksinimler:")
        for item in structure[:10]:
            parts.append(f"- {item}")
    if isinstance(ana, dict):
        kurallar = ana.get("kurallar") or []
        if kurallar:
            parts.append("Ana gorsel kurallari:")
            for item in kurallar[:10]:
                parts.append(f"- {item}")
        yasaklar = ana.get("yasaklar") or []
        if yasaklar:
            parts.append("Yasaklar:")
            for item in yasaklar[:8]:
                parts.append(f"- {item}")
    return "\n".join(parts) if parts else "(ozel kural yok)"


_prompt = PromptTemplate(
    template=PROMPT_TEMPLATE,
    input_variables=[
        "sinif_seviyesi",
        "image_type",
        "scene_description",
        "scenario_text",
        "visual_layout",
        "visual_elements",
        "hidden_computation",
        "questions_block",
        "option_scenes",
        "option_labels",
        "gorsel_rules",
        "feedback_section",
    ],
    partial_variables={"format_instructions": _parser.get_format_instructions()},
)

_chain = _prompt | _model | _parser


def generate_solid3d_scene(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    feedback: Optional[str] = None,
) -> Solid3DScene:
    labels: list[str] = []
    if question.questions:
        labels = list(question.questions[0].options.keys())
    labels = labels or template.option_labels

    payload = {
        "sinif_seviyesi": str(template.sinif_seviyesi),
        "image_type": template.image_type,
        "scene_description": question.scene_description or "(yok)",
        "scenario_text": question.scenario_text or "(yok)",
        "visual_layout": str(question.visual_layout or {})[:700],
        "visual_elements": str(question.visual_elements or [])[:900],
        "hidden_computation": str(question.hidden_computation or {})[:900],
        "questions_block": _format_questions_block(question),
        "option_scenes": str(question.option_scenes or {})[:1200],
        "option_labels": ", ".join(labels),
        "gorsel_rules": _format_gorsel_rules(template),
        "feedback_section": (
            "Onceki denemede su sorunlar tespit edildi (duzelt):\n" + feedback
            if feedback else "(yok)"
        ),
    }
    return _chain.invoke(payload)
