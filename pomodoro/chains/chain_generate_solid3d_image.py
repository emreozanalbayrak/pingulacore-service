"""Solid 3D deterministik gorsel uretimi."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Optional

from google.genai import types

from pomodoro.chains.chain_generate_solid3d_scene import generate_solid3d_scene
from pomodoro.models import GeneratedImages, GeneratedVisualQuestion
from pomodoro.pipeline_log import pipeline_log
from pomodoro.solid3d_scene import Solid3DScene
from pomodoro.solid3d_validator import validate_solid3d_scene
from pomodoro.yaml_loader import ParsedTemplate
from src.render_solid3d_scene import render_solid3d_scene_to_file, render_solid3d_scene_to_png
from utils.llm import MODEL_REGISTRY, ModelRole, get_image_client


MAX_SCENE_ATTEMPTS = 3
KEEP_SOLID3D_DEBUG = os.getenv("PINGULA_KEEP_SOLID3D_DEBUG", "").lower() in {
    "1", "true", "yes", "on"
}


def _expected_option_labels(question: GeneratedVisualQuestion, template: ParsedTemplate) -> set[str] | None:
    if not template.has_visual_options:
        return None
    if not question.questions:
        return set(template.option_labels)
    return {label.strip().upper() for label in question.questions[0].options.keys()}


def _save_scene_json(scene: Solid3DScene, output_dir: Path) -> None:
    if not KEEP_SOLID3D_DEBUG:
        return
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "solid3d_scene.json").write_text(
        json.dumps(scene.model_dump(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _format_questions(question: GeneratedVisualQuestion) -> str:
    lines: list[str] = []
    for q in question.questions[:3]:
        lines.append(f"- {q.question_stem}")
        if q.correct_answer:
            lines.append(f"  Dogru cevap: {q.correct_answer}) {q.options.get(q.correct_answer, '')}")
    return "\n".join(lines) if lines else "(yok)"


def _previous_visual_variation_feedback(output_dir: Path) -> str | None:
    previous_main = output_dir / "main_visual.png"
    previous_base = output_dir / "main_visual_base.png"
    if not previous_main.exists() and not previous_base.exists():
        return None
    return (
        "ONCEKI 3D GORSEL VARYASYON NOTU:\n"
        "- Bu kez final gorsel base'in renklerini ve kaplama hissini birebir kopyalamasin.\n"
        "- En az ikisini degistir: genel palet, yuzey boyama dili, zemin tonu, ortam atmosferi, cevresel ayrinti yogunlugu.\n"
        "- Ayni geometrik yapi korunurken final, onceki denemeden ilk bakista ayirt edilebilir olsun."
    )


def _infer_theme_object(question: GeneratedVisualQuestion, scene: Solid3DScene) -> str:
    if getattr(scene, "theme_object", None):
        return str(scene.theme_object)
    if getattr(question, "scenario_target_object", None):
        return str(question.scenario_target_object)
    objects = getattr(question, "used_objects", None) or []
    if objects:
        return str(objects[0])
    if scene.scenario_hint:
        return str(scene.scenario_hint)
    return ""


def _infer_place_hint(question: GeneratedVisualQuestion) -> str:
    # Scene'de explicit place hint varsa onu tercih etmek icin wrapper asagida var.
    text = " ".join(
        filter(
            None,
            [
                getattr(question, "scenario_text", "") or "",
                getattr(question, "scene_description", "") or "",
            ],
        )
    ).lower()
    if any(k in text for k in ("masa", "çalışma mas", "calisma mas", "sıra", "sira", "desk")):
        return "masaustu / calisma masasi"
    if any(k in text for k in ("sınıf", "sinif", "ders", "atolye", "atölye", "laboratuvar")):
        return "sinif / atolye"
    if any(k in text for k in ("sahne", "stand", "sergile", "vitrin")):
        return "sergileme / stand alani"
    if any(k in text for k in ("mutfak", "raf", "tezgah", "tezgâh")):
        return "ev ici / tezgah"
    return "notr egitsel mekan"


def _scene_place_hint(question: GeneratedVisualQuestion, scene: Solid3DScene) -> str:
    if getattr(scene, "place_hint", None):
        return str(scene.place_hint)
    return _infer_place_hint(question)


def _scene_material_hint(scene: Solid3DScene) -> str:
    return str(getattr(scene, "material_hint", None) or "duz illustratif egitsel materyal")


def _object_detail_hint(theme_object: str, place_hint: str, material_hint: str) -> str:
    obj = theme_object.lower()
    if "fırıldak" in obj or "firildak" in obj:
        return (
            "Tema nesnesi firildaksa oyun-atolyesi hissi hafifce sezilebilir; ana geometri korunmali."
        )
    if "davul" in obj:
        return (
            "Tema nesnesi davul veya davul standiysa ritim/stant hissi hafifce sezilebilir; yeni cisim ekleme."
        )
    if "uçurtma" in obj or "ucurtma" in obj:
        return "Tema nesnesi ucurtmaysa hafif ve acik hava hissi sezilebilir; geometriyi degistirme."
    if "stand" in obj or "kaide" in obj:
        return "Tema nesnesi stand/kaide ise sergileme hissi hafifce sezilebilir; yapiyi yeniden kurma."
    if any(k in obj for k in ("oyuncak", "maket", "model")):
        return "Tema nesnesi oyuncak/maket/model ise sade egitsel sunum hissi olabilir."
    return f"Tema nesnesi '{theme_object}' ise bu nesnenin hissi hafifce sezilebilir; yeni obje ekleme."


def _build_restyle_prompt(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    scene: Solid3DScene,
    feedback: Optional[str],
) -> str:
    theme_object = _infer_theme_object(question, scene)
    place_hint = _scene_place_hint(question, scene)
    material_hint = _scene_material_hint(scene)
    object_hint = _object_detail_hint(theme_object, place_hint, material_hint) if theme_object else ""
    return f"""Ekteki PNG, 3D geometrik cisim sorusu icin kodla uretilmis referans/base gorseldir. Bu referansi 2D geometri akisindaki gibi "yapi sabit, stil serbest" mantigiyla daha estetik, temiz ve cocuklara uygun egitsel bir ana gorsele donustur.

MUTLAK KORUMA:
- Referanstaki cisim sayisi, cisim turleri, katman sirasi ve panel duzeni korunmali.
- Dikdortgen prizma, kare prizma, kup, ucgen prizma, silindir ve kure ayrimi bozulmamalidir.
- Ucgen prizmanin tum gorunur yuzleri perspektif kurallarina uygun kalmali; yuz eksiltme veya siluet bozma yapma.
- Referansta tek yapi varsa tek yapi olarak kalmali; panel varsa panel duzeni aynen korunmali.
- Yeni cisim, yeni katman, yeni metin, yeni etiket, tik, yildiz, cevap ipucu veya dekoratif obje ekleme.
- Cevabi degistirecek bicimde cisim turunu, oranini, yonunu veya ust-orta-alt sirayi degistirme.
- Cisimler panel icinde birebir ayni piksel konumunda olmak zorunda degil; fakat destek iliskisi, ust-alt sirasi ve genel dizilim korunmali.

ESTETIK HEDEF:
- Geometri disi 2D uretimlerdeki gibi temiz, renkli, modern egitim materyali hissi ver.
- Ders kitabi, calisma kagidi veya cocuklara uygun modern egitim illustrasyonu gibi gorunebilir.
- Cartoony olabilir ama hafif kalsin; asiri sevimli oyuncak reklami, 3D render katalogu veya fotogercekci obje fotografi gibi gorunme.
- Cok hafif hacim ayrimi olabilir ama guclu isik-golge, parlama, yansima, ahsap damari, plastik parlaklik, seramik doku, fotografik masa yuzeyi veya lens efekti kullanma.
- Fotogercekci, dramatik isik, asiri doku, karmasik arka plan veya sinematik sahne yapma.
- Zemin sakin kalsin; cisimler ana odak olsun.
- Base gorsel bilerek sade bir referans iskeletidir; final gorsel sadece base'in duz boyali kopyasi gibi gorunmemeli.
- 2D geometri hybrid akisindaki mantikla, ana geometriyi bozmadan baglam hissini yansit.
- Final gorsel base'den belirgin bicimde ayrisabilir; cevresel detaylara model karar verebilir.
- Base'teki govde renkleri, yuzey kaplamalari ve ton gecisleri zorunlu olarak aynen tasinmamalidir.
- Final, base'i yapisal referans olarak kullanmali; renk, atmosfer, malzeme dili ve sahne yorumu olarak daha ozgur davranabilir.
- Gerekiyorsa daha zengin bir illustratif palet, farkli bir zemin tonu ve daha canli bir ortam hissi sec; ama geometriyi bozma.
- Tematik yorum sadece ana yapi DISINDA veya cisim yuzey malzemesinde hissedilmeli; yeni nesne ekleyerek soruyu degistirme.
- Base visual'daki kart/cerceve estetiklerini geri getirme; final daha dogal ve baglama yakin gorunebilir.
- Gercek fotograf cekilmis nesne gibi degil, iyi cizilmis modern bir illustrasyon gibi gorun.
- Arka plan hafif ve yumusak olabilir; bokeh, kamera derinligi, stüdyo isigi, gercek masa lekesi gibi fotograf ipuclari olmasin.
{object_hint}

Baglam:
- Sinif seviyesi: {template.sinif_seviyesi}
- Gorsel tipi: {template.image_type}
- Sahne ozeti: {question.scene_description}
- Tema nesnesi: {theme_object or '(yok)'}
- Mekan hissi: {place_hint}
- Malzeme hissi: {material_hint}
- Scenario hint: {scene.scenario_hint or '(yok)'}

Soru ozeti:
{_format_questions(question)}

Geri bildirim:
{feedback or '(yok)'}

Yalnizca tek bir PNG gorseli uret."""


def _generate_restyled_solid3d_image(
    *,
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    scene: Solid3DScene,
    base_png_path: Path,
    output_path: Path,
    feedback: Optional[str],
) -> str | None:
    try:
        client = get_image_client()
        config = MODEL_REGISTRY[ModelRole.IMAGE_GENERATOR]
        prompt = _build_restyle_prompt(template, question, scene, feedback)
        image_part = types.Part.from_bytes(
            data=base_png_path.read_bytes(),
            mime_type="image/png",
        )
        response = client.models.generate_content(
            model=config["model"],
            contents=[image_part, prompt],
            config={"response_modalities": ["TEXT", "IMAGE"]},
        )
        for part in response.candidates[0].content.parts:
            if hasattr(part, "inline_data") and part.inline_data is not None:
                data = part.inline_data.data
                if isinstance(data, str):
                    import base64
                    data = base64.b64decode(data)
                output_path.write_bytes(data)
                pipeline_log("solid3d", f"3D final PNG uretildi: {output_path}")
                return str(output_path)
    except Exception as exc:
        pipeline_log(
            "solid3d",
            f"3D image-conditioned final uretimi basarisiz; base PNG kullanilacak: {type(exc).__name__}: {exc}",
        )
        return None

    pipeline_log("solid3d", "3D image model yaniti gorsel icermiyor; base PNG kullanilacak.")
    return None


def generate_solid3d_image(
    template: ParsedTemplate,
    question: GeneratedVisualQuestion,
    output_dir: str | Path = "output/visual_questions",
    feedback: Optional[str] = None,
) -> GeneratedImages:
    """Tek ana gorselde deterministik 3D cisim/panel render eder.

    Bu motor bilerek `option_images=None` dondurur. Gorsel secenekler gerekiyorsa
    A/B/C panelleri main_visual icine yerlestirilir.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    expected_labels = _expected_option_labels(question, template)
    previous_variation_feedback = _previous_visual_variation_feedback(output_dir)
    collected_feedback = feedback or ""
    if previous_variation_feedback:
        collected_feedback = (
            (collected_feedback + "\n\n") if collected_feedback else ""
        ) + previous_variation_feedback
    scene: Solid3DScene | None = None
    last_issues: list[str] = []

    for attempt in range(1, MAX_SCENE_ATTEMPTS + 1):
        pipeline_log(
            "solid3d",
            f"3D sahne grafi uretimi (deneme {attempt}/{MAX_SCENE_ATTEMPTS})…",
        )
        scene = generate_solid3d_scene(template, question, collected_feedback or None)
        result = validate_solid3d_scene(scene, expected_labels=expected_labels)
        if result.ok:
            pipeline_log("solid3d", f"3D sahne grafi dogrulandi (deneme {attempt}).")
            break

        last_issues = result.issues
        pipeline_log(
            "solid3d",
            f"3D sahne dogrulamasi basarisiz (deneme {attempt}): {len(result.issues)} sorun.",
        )
        collected_feedback = (
            (feedback + "\n\n" if feedback else "")
            + "YAPISAL 3D SAHNE SORUNLARI (duzelt):\n"
            + result.as_feedback()
        )
    else:
        pipeline_log(
            "solid3d",
            f"3D sahne dogrulamasi {MAX_SCENE_ATTEMPTS} denemede gecilmedi; son sahne render ediliyor.",
        )

    assert scene is not None
    _save_scene_json(scene, output_dir)

    svg_path = render_solid3d_scene_to_file(scene, output_dir / "main_visual.svg")
    pipeline_log("solid3d", f"3D SVG yazildi: {svg_path}")

    base_png_path = Path(render_solid3d_scene_to_png(scene, output_dir / "main_visual_base.png"))
    pipeline_log("solid3d", f"3D base PNG yazildi: {base_png_path}")

    final_png_path = output_dir / "main_visual.png"
    final_path = _generate_restyled_solid3d_image(
        template=template,
        question=question,
        scene=scene,
        base_png_path=base_png_path,
        output_path=final_png_path,
        feedback=feedback,
    )
    if final_path is None:
        shutil.copyfile(base_png_path, final_png_path)
        final_path = str(final_png_path)
        pipeline_log("solid3d", f"3D final PNG base kopyasi olarak yazildi: {final_png_path}")

    notes = "solid_3d hybrid render (deterministik base + image-conditioned main, tek ana gorsel)"
    if last_issues:
        notes += f" — acik sorun: {len(last_issues)}"

    return GeneratedImages(
        main_image_path=final_path,
        option_images=None,
        generation_notes=notes,
    )
